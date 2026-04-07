import os, logging, tempfile, threading, json
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes, CommandHandler
from groq import Groq
from notion_client import Client

TELEGRAM_TOKEN     = os.environ["TELEGRAM_TOKEN"]
GROQ_API_KEY       = os.environ["GROQ_API_KEY"]
NOTION_TOKEN       = os.environ["NOTION_TOKEN"]
NOTION_DATABASE_ID = os.environ["NOTION_DATABASE_ID"]

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

def analyze_text(text):
    today = datetime.now().strftime("%Y-%m-%d")
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    prompt = f"""اليوم هو {today}.
حلل هذا النص واستخرج المعلومات التالية بصيغة JSON فقط بدون اي نص اضافي:
{{
  "task": "اسم المهمة بشكل مختصر وواضح",
  "due_date": "تاريخ التسليم بصيغة YYYY-MM-DD او null. غدا = {tomorrow}",
  "priority": "عالية او متوسطة او منخفضة او null",
  "notes": "اي تفاصيل اضافية او null"
}}
النص: {text}"""
    response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0
    )
    return json.loads(response.choices[0].message.content.strip())

def save_to_notion(data):
    props = {}
    for key in ["Name", "title"]:
        try:
            props[key] = {"title": [{"text": {"content": data["task"][:200]}}]}
            break
        except:
            continue
    if data.get("due_date"):
        for key in ["تاريخ الاستحقاق", "Due Date"]:
            try:
                props[key] = {"date": {"start": data["due_date"]}}
                break
            except:
                continue
    if data.get("priority"):
        for key in ["الأولوية", "Priority"]:
            try:
                props[key] = {"select": {"name": data["priority"]}}
                break
            except:
                continue
    children = []
    if data.get("notes"):
        children = [{"object":"block","type":"paragraph","paragraph":{"rich_text":[{"text":{"content":data["notes"]}}]}}]
    try:
        notion.pages.create(parent={"database_id": NOTION_DATABASE_ID}, properties=props, children=children)
        return True
    except:
        for key in ["Name", "title"]:
            try:
                notion.pages.create(parent={"database_id": NOTION_DATABASE_ID}, properties={key: {"title": [{"text": {"content": data["task"][:200]}}]}}, children=children)
                return True
            except:
                continue
    return False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("مرحبا! ارسل رسالة صوتية او نصية وساحفظها في Notion")

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
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    print("Bot is running")
    app.run_polling()

if __name__ == "__main__":
    main()
