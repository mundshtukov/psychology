import os
import uuid
import base64
import time
import requests
import urllib3
import asyncio
from flask import Flask, request
from threading import Thread
from telegram import Update, Bot, ReplyKeyboardMarkup
from telegram.ext import (
    Application, ApplicationBuilder, CommandHandler, MessageHandler,
    ContextTypes, filters
)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

TOKEN = os.getenv("TG_BOT_TOKEN")
CLIENT_ID = os.getenv("GIGACHAT_CLIENT_ID")
CLIENT_SECRET = os.getenv("GIGACHAT_CLIENT_SECRET")
WEBHOOK_URL = os.getenv("RENDER_EXTERNAL_URL")  # from Render env var

bot = Bot(token=TOKEN)
app_flask = Flask(__name__)

user_contexts = {}
user_last_active = {}
user_silence_prompts = {}
dialog_ended = set()

SYSTEM_PROMPT = (
    "Ты — добрый и тёплый психолог, который помогает трейдерам. "
    "Говори простыми словами, как хороший друг. "
    "Избегай сложных фраз. Поддерживай человека, задавай вопросы, если он молчит. "
    "Пиши без форматирования. Используй эмодзи, чтобы было тепло и понятно."
)

keyboard = ReplyKeyboardMarkup(
    keyboard=[
        ["🟢 Начать", "🙏 Спасибо"],
        ["🔁 Продолжить"]
    ],
    resize_keyboard=True
)

def get_access_token():
    auth_string = f"{CLIENT_ID}:{CLIENT_SECRET}"
    auth_base64 = base64.b64encode(auth_string.encode()).decode()

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
        "Authorization": f"Basic {auth_base64}",
        "RqUID": str(uuid.uuid4())
    }

    response = requests.post(
        "https://ngw.devices.sberbank.ru:9443/api/v2/oauth",
        headers=headers,
        data={"scope": "GIGACHAT_API_PERS"},
        verify=False
    )

    return response.json().get("access_token") if response.ok else None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_chat.id
    user_contexts[user_id] = []
    user_last_active[user_id] = time.time()
    user_silence_prompts[user_id] = 0
    dialog_ended.discard(user_id)

    await update.message.reply_text(
        "👋 Привет!\n\n"
        "Я — помощник для трейдеров.\n"
        "Тревога, страх, усталость — я рядом 💬\n\n"
        "🟢 Начать — начать разговор\n"
        "🙏 Спасибо — завершить\n"
        "🔁 Продолжить — если не знаешь, что сказать\n\n"
        "👇 Нажми «Начать»", reply_markup=keyboard
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_last_active[update.effective_chat.id] = time.time()
    await update.message.reply_text(
        "ℹ️ Я поддержу тебя, когда трудно 💛\n\n"
        "🟢 Начать — с начала\n"
        "🙏 Спасибо — закончить беседу\n"
        "🔁 Продолжить — если не знаешь, что сказать\n\n"
        "Пиши, когда будешь готов", reply_markup=keyboard
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_chat.id
    text = update.message.text.strip()
    user_last_active[user_id] = time.time()
    user_silence_prompts[user_id] = 0
    dialog_ended.discard(user_id)

    user_contexts.setdefault(user_id, [])

    if text == "🟢 Начать":
        user_contexts[user_id] = []
        await update.message.reply_text(
            "📝 Расскажи, что у тебя на душе.\n\n"
            "• тревога перед сделкой\n"
            "• чувство вины после потерь\n"
            "• страх снова начать\n"
            "• выгорание\n\n"
            "Пиши простыми словами — я здесь 💛"
        )
        return

    if text == "🙏 Спасибо":
        dialog_ended.add(user_id)
        await update.message.reply_text(
            "✨ Рад был быть рядом. Ты не один.\n"
            "Если понадобится поддержка — напиши 💬"
        )
        return

    if text == "🔁 Продолжить":
        await continue_dialog(user_id, update)
        return

    await continue_conversation(user_id, text, update)

async def continue_conversation(user_id, user_text, update):
    access_token = get_access_token()
    if not access_token:
        await update.message.reply_text("⚠️ Ошибка подключения к GigaChat.")
        return

    context_list = user_contexts[user_id]
    if not context_list:
        context_list.append({"role": "system", "content": SYSTEM_PROMPT})
    context_list.append({"role": "user", "content": user_text})

    response = requests.post(
        "https://gigachat.devices.sberbank.ru/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        },
        json={"model": "GigaChat", "messages": context_list},
        verify=False
    )

    if response.ok:
        reply = response.json()["choices"][0]["message"]["content"]
        for symbol in ["*", "_", "`", "#"]:
            reply = reply.replace(symbol, "")
        context_list.append({"role": "assistant", "content": reply})
    else:
        reply = f"⚠️ GigaChat ошибка: {response.status_code}"

    await update.message.reply_text(reply)

async def continue_dialog(user_id, update):
    context_list = user_contexts[user_id]
    if not context_list:
        await update.message.reply_text("Мы ещё не начали. Нажми «Начать» 😊")
        return

    prompt = "Пользователь не знает, что сказать. Поддержи добрым вопросом."
    context_list.append({"role": "user", "content": prompt})
    await continue_conversation(user_id, prompt, update)

async def monitor_silence(app: Application):
    while True:
        now = time.time()
        for user_id, last_active in list(user_last_active.items()):
            if user_id in dialog_ended:
                continue

            if now - last_active > 120:
                count = user_silence_prompts.get(user_id, 0)
                if count >= 3:
                    continue

                user_last_active[user_id] = now
                user_silence_prompts[user_id] = count + 1
                try:
                    prompt = "Пользователь молчит. Спроси добрый вопрос, чтобы продолжить беседу."
                    user_contexts[user_id].append({"role": "user", "content": prompt})
                    await bot.send_message(chat_id=user_id, text="🤔 Всё ли в порядке? Я рядом, если нужно поговорить 💬")
                except Exception as e:
                    print("⚠️ Автосообщение ошибка:", e)
        await asyncio.sleep(30)

@app_flask.route(f"/webhook/{TOKEN}", methods=["POST"])
def webhook():
    update = Update.de_json(request.get_json(force=True), bot)
    asyncio.run(application.process_update(update))
    return "OK", 200

@app_flask.route("/")
def index():
    return "🤖 Бот работает!"

async def post_init(app: Application):
    await bot.set_webhook(f"{WEBHOOK_URL}/webhook/{TOKEN}")
    app.create_task(monitor_silence(app))

def run_flask():
    app_flask.run(host="0.0.0.0", port=10000)

if __name__ == "__main__":
    application = ApplicationBuilder().token(TOKEN).post_init(post_init).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    Thread(target=run_flask).start()
