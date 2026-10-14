import json
import os
from http.server import BaseHTTPRequestHandler
from urllib import request

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
WEBAPP_URL = os.getenv("WEBAPP_URL", "")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")

BTN_PROFILE = "Профиль"
BTN_SUBSCRIPTION = "Подписка"
BTN_APP = "Мини приложение"


def call(method, payload):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with request.urlopen(req, timeout=10) as resp:
        return json.load(resp)


def menu_markup():
    rows = [[BTN_PROFILE, BTN_SUBSCRIPTION]]
    if WEBAPP_URL:
        rows.append([{"text": BTN_APP, "web_app": {"url": WEBAPP_URL}}])
    else:
        rows.append([BTN_APP])
    return {"keyboard": rows, "resize_keyboard": True, "is_persistent": True}


def send(chat_id, text):
    call("sendMessage", {"chat_id": chat_id, "text": text, "reply_markup": menu_markup()})


def handle_message(message):
    chat_id = message["chat"]["id"]
    user = message.get("from", {})
    text = message.get("text", "")

    if text == "/start":
        send(chat_id, "Главное меню:")
    elif text == BTN_PROFILE:
        username = f"@{user['username']}" if user.get("username") else "не задан"
        send(
            chat_id,
            f"Профиль\nID: {user.get('id')}\nИмя: {user.get('first_name', '')}\nUsername: {username}",
        )
    elif text == BTN_SUBSCRIPTION:
        send(chat_id, "Подписка: активной подписки пока нет. Откройте мини приложение, чтобы выбрать тариф.")
    elif text == BTN_APP:
        if WEBAPP_URL:
            send(chat_id, "Откройте мини приложение кнопкой ниже.")
        else:
            send(chat_id, "Мини приложение не настроено: не задан WEBAPP_URL.")
    else:
        send(chat_id, "Используйте кнопки меню ниже.")


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self._reply(200, "bot is alive")

    def do_POST(self):
        if WEBHOOK_SECRET and self.headers.get("X-Telegram-Bot-Api-Secret-Token") != WEBHOOK_SECRET:
            self._reply(403, "forbidden")
            return

        length = int(self.headers.get("Content-Length", 0))
        try:
            update = json.loads(self.rfile.read(length) or b"{}")
            message = update.get("message")
            if message and "text" in message:
                handle_message(message)
        except Exception as exc:
            print("handler error:", exc)

        # Всегда отвечаем 200, иначе Telegram будет повторять update
        self._reply(200, "ok")

    def _reply(self, code, body):
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))
