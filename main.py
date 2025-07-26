import os
import uuid
import base64
import time
import requests
import urllib3
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, ContextTypes,
    MessageHandler, CommandHandler, filters,
    Application
)
import asyncio

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
CLIENT_ID = os.getenv("GIGACHAT_CLIENT_ID")
CLIENT_SECRET = os.getenv("GIGACHAT_CLIENT_SECRET")

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

    if response.status_code == 200:
        return response.json().get("access_token")
    else:
        print("❌ Ошибка авторизации:", response.status_code, response.text)
        return None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.chat_id
    user_contexts[user_id] = []
    user_last_active[user_id] = time.time()
    user_silence_prompts[user_id] = 0
    if user_id in dialog_ended:
        dialog_ended.remove(user_id)
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
    text = (
        "ℹ️ Я здесь, чтобы поддержать тебя, когда трудно.\n\n"
        "Вот что можно сделать:\n\n"
        "🟢 Начать — начать новый разговор (всё сначала)\n"
        "🙏 Спасибо — закончить беседу, но я всё запомню\n"
        "🔁 Продолжить — если не знаешь, что написать — я сам задам вопрос\n\n"
        "Пиши, когда будешь готов. Я рядом 💛"
    )
    await update.message.reply_text(text, reply_markup=keyboard)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.chat_id
    text = update.message.text.strip()
    user_last_active[user_id] = time.time()
    user_silence_prompts[user_id] = 0
    if user_id in dialog_ended:
        dialog_ended.remove(user_id)

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

    elif text == "🙏 Спасибо":
        dialog_ended.add(user_id)
        await update.message.reply_text(
            "✨ Рад был быть рядом. Помни — ты не один.\n"
            "Если снова понадобится поддержка, просто напиши. Я рядом 💬"
        )
        return

    elif text == "🔁 Продолжить":
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
            if user_id in dialog_ended:
                continue

            if now - last_active > 120:
                count = user_silence_prompts.get(user_id, 0)
                if count >= 3:
                    continue  # больше не писать

                user_last_active[user_id] = now
                user_silence_prompts[user_id] = count + 1
                try:
                    chat_context = user_contexts.get(user_id, [])
                    if not chat_context:
                        continue

                    prompt = "Пользователь молчит. Спросить добрый, поддерживающий вопрос, чтобы gently продолжить разговор."
                    chat_context.append({"role": "user", "content": prompt})

                    class DummyMessage:
                        def __init__(self, chat_id, bot):
                            self.chat_id = chat_id
                            self._bot = bot

                        async def reply_text(self, msg):
                            await self._bot.send_message(self.chat_id, msg)

                    dummy_update = type('dummy', (), {})()
                    dummy_update.message = DummyMessage(user_id, app.bot)

                    await continue_conversation(user_id, prompt, dummy_update)

                except Exception as e:
                    print(f"⚠️ Ошибка при автосообщении: {e}")
        await asyncio.sleep(30)

async def post_init(application: Application):
    application.create_task(monitor_silence(application))

def main():
    app = ApplicationBuilder().token(TG_BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("✅ Бот запущен.")
    app.run_polling()

if __name__ == "__main__":
    main()
