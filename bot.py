import os, logging, tempfile, threading, json, time
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes, CommandHandler
from groq import Groq
from notion_client import Client
import httpx

TELEGRAM_TOKEN     = os.environ["TELEGRAM_TOKEN"]
GROQ_API_KEY       = os.environ["GROQ_API_KEY"]
NOTION_TOKEN       = os.environ["NOTION_TOKEN"]
NOTION_DATABASE_ID = os.environ["NOTION_DATABASE_ID"]
RENDER_URL         = os.environ.get("RENDER_URL", "https://telegram-notion-bot-2.onrender.com")

groq_client = Groq(api_key=GROQ_API_KEY)
notion      = Client(auth=NOTION_TOKEN)
logging.basicConfig(level=logging.INFO)

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is running")
    def log_message(self, *args):
        pass

def run_web():
    HTTPServer(("0.0.0.0", 10000), Handler).serve_forever()

def keep_alive():
    while True:
        time.sleep(14 * 60)
        try:
            httpx.get(RENDER_URL, timeout=10)
            logging.info("Ping sent")
        except:
            pass

def analyze_text(text):
    today = datetime.now().strftime("%Y-%m-%d")
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    prompt = f"""اليوم هو {today}.
حلل هذا النص واستخرج المعلومات التالية بصيغة JSON فقط بدون اي نص اضافي:
{{
  "task": "اسم المهمة بشكل مختصر وواضح",
  "due_date": "تاريخ التسليم بصيغة YYYY-MM-DD او null. غدا = {tomorrow}",
  "priority": "عاجل او عالية او متوسطة او منخفضة او null",
  "notes": "اي تفاصيل اضافية او null"
}}
النص: {text}"""
    response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": "انت مساعد يرد فقط بصيغة JSON صحيحة بدون اي نص اضافي"},
            {"role": "user", "content": prompt}
        ],
        temperature=0,
        response_format={"type": "json_object"}
    )
    return json.loads(response.choices[0].message.content.strip())

def save_to_notion(data):
    props = {
        "اسم المهمة": {"title": [{"text": {"content": data["task"][:200]}}]}
    }
    if data.get("due_date"):
        props["تاريخ الاستحقاق"] = {"date": {"start": data["due_date"]}}
    if data.get("priority"):
        props["الأولوية"] = {"select": {"name": data["priority"]}}
    if data.get("notes"):
        props["ملاحظات"] = {"rich_text": [{"text": {"content": data["notes"]}}]}
    try:
        notion.pages.create(
            parent={"database_id": NOTION_DATABASE_ID},
            properties=props
        )
        return True
    except Exception as e:
        logging.error(str(e))
        raise e

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "مرحبا! الاوامر المتاحة:\n\n"
        "ارسل رسالة صوتية او نصية لحفظ مهمة\n"
        "/list - عرض اخر 5 مهام\n"
        "/done - تعليم مهمة كمنجزة"
    )

async def list_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        results = notion.databases.query(
            database_id=NOTION_DATABASE_ID,
            sorts=[{"timestamp": "created_time", "direction": "descending"}],
            page_size=5
        )
        pages = results.get("results", [])
        if not pages:
            await update.message.reply_text("لا توجد مهام بعد!")
            return

        reply = "اخر 5 مهام:\n\n"
        for i, page in enumerate(pages, 1):
            props = page["properties"]
            title = props["اسم المهمة"]["title"]
            name = title[0]["text"]["content"] if title else "بدون اسم"
            done = props.get("منجزة؟", {}).get("checkbox", False)
            status = "✅" if done else "⬜"
            due = props.get("تاريخ الاستحقاق", {}).get("date")
            due_str = f" | {due['start']}" if due else ""
            reply += f"{i}. {status} {name}{due_str}\n"

        await update.message.reply_text(reply)
    except Exception as e:
        await update.message.reply_text("خطا: " + str(e))

async def done_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        results = notion.databases.query(
            database_id=NOTION_DATABASE_ID,
            filter={"property": "منجزة؟", "checkbox": {"equals": False}},
            sorts=[{"timestamp": "created_time", "direction": "descending"}],
            page_size=5
        )
        pages = results.get("results", [])
        if not pages:
            await update.message.reply_text("لا توجد مهام غير منجزة!")
            return

        reply = "اختر رقم المهمة لتعليمها منجزة:\n\n"
        page_ids = []
        for i, page in enumerate(pages, 1):
            props = page["properties"]
            title = props["اسم المهمة"]["title"]
            name = title[0]["text"]["content"] if title else "بدون اسم"
            reply += f"{i}. {name}\n"
            page_ids.append(page["id"])

        context.user_data["pending_done"] = page_ids
        await update.message.reply_text(reply + "\nارسل الرقم:")
    except Exception as e:
        await update.message.reply_text("خطا: " + str(e))

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("جاري التفريغ والتحليل...")
    try:
        voice = update.message.voice or update.message.audio
        file  = await context.bot.get_file(voice.file_id)
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            await file.download_to_drive(tmp.name)
            tmp_path = tmp.name
        with open(tmp_path, "rb") as f:
            t = groq_client.audio.transcriptions.create(file=("audio.ogg", f, "audio/ogg"), model="whisper-large-v3", language="ar")
        text = t.text.strip()
        if not text:
            await update.message.reply_text("لم اتمكن من التفريغ")
            return
        data = analyze_text(text)
        saved = save_to_notion(data)
        reply = "تم الحفظ!\n\nالمهمة: " + data["task"]
        if data.get("due_date"): reply += "\nالتسليم: " + data["due_date"]
        if data.get("priority"): reply += "\nالاولوية: " + data["priority"]
        if data.get("notes"): reply += "\nملاحظات: " + data["notes"]
        await update.message.reply_text(reply if saved else "فشل الحفظ:\n" + text)
    except Exception as e:
        await update.message.reply_text("خطا: " + str(e))

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    # Check if user is selecting a task to mark as done
    if "pending_done" in context.user_data:
        page_ids = context.user_data.get("pending_done", [])
        try:
            num = int(text)
            if 1 <= num <= len(page_ids):
                page_id = page_ids[num - 1]
                notion.pages.update(
                    page_id=page_id,
                    properties={"منجزة؟": {"checkbox": True}}
                )
                del context.user_data["pending_done"]
                await update.message.reply_text("تم تعليم المهمة كمنجزة ✅")
                return
        except ValueError:
            del context.user_data["pending_done"]

    try:
        data = analyze_text(text)
        saved = save_to_notion(data)
        reply = "تم الحفظ!\n\nالمهمة: " + data["task"]
        if data.get("due_date"): reply += "\nالتسليم: " + data["due_date"]
        if data.get("priority"): reply += "\nالاولوية: " + data["priority"]
        if data.get("notes"): reply += "\nملاحظات: " + data["notes"]
        await update.message.reply_text(reply if saved else "فشل الحفظ")
    except Exception as e:
        await update.message.reply_text("خطا: " + str(e))

def main():
    threading.Thread(target=run_web, daemon=True).start()
    threading.Thread(target=keep_alive, daemon=True).start()
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("list", list_tasks))
    app.add_handler(CommandHandler("done", done_task))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    print("Bot is running")
    app.run_polling()

if __name__ == "__main__":
    main()
