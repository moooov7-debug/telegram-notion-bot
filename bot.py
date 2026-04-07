import os, logging, tempfile, threading
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

def save_to_notion(title, body=""):
    for key in ["الاسم","المهمة","العنوان","Name","title"]:
        try:
            notion.pages.create(
                parent={"database_id": NOTION_DATABASE_ID},
                properties={key: {"title": [{"text": {"content": title[:200]}}]}},
                children=[{"object":"block","type":"paragraph","paragraph":{"rich_text":[{"text":{"content":body}}]}}] if body else []
            )
            return True
        except: continue
    return False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("مرحباً! 👋\n🎙️ أرسل رسالة صوتية → أحفظها في Notion\n📝 أرسل نصاً → أحفظه في Notion")

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎙️ جاري التفريغ...")
    try:
        voice = update.message.voice or update.message.audio
        file  = await context.bot.get_file(voice.file_id)
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            await file.download_to_drive(tmp.name)
        with open(tmp.name, "rb") as f:
            t = groq_client.audio.transcriptions.create(file=("audio.ogg",f,"audio/ogg"),model="whisper-large-v3",language="ar")
        text = t.text.strip()
        if not text:
            await update.message.reply_text("⚠️ لم أتمكن من التفريغ")
            return
        if save_to_notion(text[:100], text):
            await update.message.reply_text(f"✅ تم الحفظ!\n\n📝 {text}")
        else:
            await update.message.reply_text(f"⚠️ تم التفريغ لكن فشل الحفظ:\n{text}")
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ: {e}")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if save_to_notion(text[:100], text if len(text)>100 else ""):
        await update.message.reply_text("✅ تم الحفظ في Notion!")
    else:
        await update.message.reply_text("❌ فشل الحفظ")

def main():
    threading.Thread(target=run_web, daemon=True).start()
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.VOICE|filters.AUDIO, handle_voice))
    app.add_handler(MessageHandler(filters.TEXT&~filters.COMMAND, handle_text))
    print("البوت يعمل 🚀")
    app.run_polling()

if __name__ == "__main__":
    main()
