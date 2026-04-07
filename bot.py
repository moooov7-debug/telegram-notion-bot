import os
import logging
import tempfile
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

def save_to_notion(title: str, body: str = ""):
    for key in ["الاسم", "المهمة", "العنوان", "Name", "title"]:
        try:
            notion.pages.create(
                parent={"database_id": NOTION_DATABASE_ID},
                properties={
                    key: {"title": [{"text": {"content": title[:200]}}]}
                },
                children=[{"object": "block","type": "paragraph","paragraph": {"rich_text": [{"text": {"content": body}}]}}] if body else []
            )
            return True
        except Exception:
            continue
    return False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("​​​​​​​​​​​​​​​​
