import os
import uuid
import base64
import time
import json
import asyncio
import requests
import urllib3
from threading import Thread
from flask import Flask, request
from telegram import Update, Bot, ReplyKeyboardMarkup
from telegram.ext import (
    Application, ApplicationBuilder, CommandHandler,
    MessageHandler, ContextTypes, filters, Dispatcher
)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
CLIENT_ID = os.getenv("GIGACHAT_CLIENT_ID")
CLIENT_SECRET = os.getenv("GIGACHAT_CLIENT_SECRET")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # 👈 укажешь свой Render URL сюда

app = Flask(__name__)
bot = Bot(token=TG_BOT_TOKEN)

user_contexts = {}
user_last_active = {}
user_auto_messages_sent = {}
user_said_thanks = {}

SYSTEM_PROMPT = (
    "Ты — добрый и тёплый психолог, который помогает трейдерам. "
    "Говори простыми словами, как хороший друг. "
    "Избегай сложных фраз. Поддерживай человека, задавай вопросы, если он молчит. "
    "Пиши без форматирования. Используй эмодзи, чтобы было тепло и понятно."
)

keyboard = ReplyKeyboardMarkup(
    keyboard=[[
        "🟢 Начать", "🙏 Спасибо"],
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
    user_id = update.message.chat_id
    user_contexts[user_id] = []
    user_last_active[user_id] = time.time()
    user_auto_messages_sent[user_id] = 0
    user_said_thanks[user_id] = False

    text = (
        "👋 Привет!\n\n"
        "Я — помощник для трейдеров.  \n"
        "Бывает сложно... тревога, страх, выгорание.  \n"
        "Я рядом, чтобы поддержать 💬\n\n"
        "Вот что я умею:\n"
        "🟢 Начать — начать новый разговор\n"
        "🙏 Спасибо — завершить беседу\n"
        "🔁 Продолжить — если не знаешь, что сказать, я сам подскажу вопрос\n\n"
        "👇 Нажми «Начать», и я задам первый вопрос"
    )
    await update.message.reply_text(text, reply_markup=keyboard)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_last_active[update.message.chat_id] = time.time()
    await update.message.reply_text(
        "ℹ️ Я здесь, чтобы поддержать тебя, когда трудно.\n\n"
        "🟢 Начать — начать новый разговор\n"
        "🙏 Спасибо — закончить беседу\n"
        "🔁 Продолжить — если не знаешь, что сказать, я помогу 💛",
        reply_markup=keyboard
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.chat_id
    text = update.message.text.strip()
    user_last_active[user_id] = time.time()
    user_auto_messages_sent[user_id] = 0
    user_said_thanks[user_id] = False

    if user_id not in user_contexts:
        user_contexts[user_id] = []

    if text == "🟢 Начать":
        user_contexts[user_id] = []
        await update.message.reply_text(
            "📝 Расскажи, что у тебя сейчас на душе.\n\n"
            "Можешь коротко описать, что беспокоит:\n"
            "• тревога перед сделкой\n"
            "• чувство вины после потерь\n"
            "• страх снова начать торговать\n"
            "• выгорание или усталость\n\n"
            "Пиши как чувствуешь — можно простыми словами. Я здесь, чтобы поддержать тебя 💛"
        )
        return

    if text == "🙏 Спасибо":
        user_said_thanks[user_id] = True
        await update.message.reply_text(
            "✨ Рад был быть рядом. Помни — ты не один.\n"
            "Если снова понадобится поддержка, просто напиши. Я рядом 💬"
        )
        return

    if text == "🔁 Продолжить":
        return await continue_dialog(user_id, update)

    await continue_conversation(user_id, text, update)

async def continue_conversation(user_id, user_text, update):
    access_token = get_access_token()
    if not access_token:
        await update.message.reply_text("⚠️ Не удалось подключиться к GigaChat.")
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
        reply = f"⚠️ Ошибка GigaChat: {response.status_code}"

    await update.message.reply_text(reply)

async def continue_dialog(user_id, update):
    context_list = user_contexts[user_id]
    if not context_list:
        await update.message.reply_text("Пока что у нас не было беседы. Нажми «Начать», чтобы начать с чистого листа 😊")
        return

    prompt = "Пользователь не знает, что написать. Помоги продолжить разговор, задай простой, добрый вопрос в контексте."
    context_list.append({"role": "user", "content": prompt})
    await continue_conversation(user_id, prompt, update)

async def monitor_silence(app: Application):
    while True:
        now = time.time()
        for user_id, last_active in list(user_last_active.items()):
            if user_said_thanks.get(user_id, False):
                continue
            if now - last_active > 120 and user_auto_messages_sent.get(user_id, 0) < 3:
                user_last_active[user_id] = now
                user_auto_messages_sent[user_id] += 1

                chat_context = user_contexts.get(user_id, [])
                if not chat_context:
                    continue

                prompt = "Пользователь молчит. Спросить добрый, поддерживающий вопрос, чтобы gently продолжить разговор."
                chat_context.append({"role": "user", "content": prompt})

                await bot.send_chat_action(chat_id=user_id, action="typing")
                await continue_conversation(user_id, prompt, Update.de_json({}, bot))
        await asyncio.sleep(30)

# Flask route для Telegram webhook
@app.route("/webhook", methods=["POST"])
def webhook():
    update = Update.de_json(request.get_json(force=True), bot)
    asyncio.run(dispatcher.process_update(update))
    return "ok"

async def setup():
    global dispatcher
    application = ApplicationBuilder().token(TG_BOT_TOKEN).build()
    dispatcher = application

    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CommandHandler("help", help_command))
    dispatcher.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    await bot.set_webhook(url=f"{WEBHOOK_URL}/webhook")
    asyncio.create_task(monitor_silence(application))

if __name__ == "__main__":
    asyncio.run(setup())
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
