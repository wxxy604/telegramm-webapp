import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler
from urllib import error, request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db  # noqa: E402

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
WEBAPP_URL = os.getenv("WEBAPP_URL", "")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")

BTN_PROFILE = "Профиль"
BTN_SUBSCRIPTION = "Подписка"
BTN_APP = "Мини приложение"

PLANS = {
    "1m": ("1 месяц", 199),
    "3m": ("3 месяца", 499),
    "12m": ("12 месяцев", 1490),
}

_bot_username = None


def call(method, payload):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with request.urlopen(req, timeout=10) as resp:
            return json.load(resp)
    except error.HTTPError as exc:
        print("telegram error:", method, exc.code, exc.read()[:300])
        return {"ok": False}


def get_bot_username():
    global _bot_username
    if _bot_username is None:
        _bot_username = call("getMe", {}).get("result", {}).get("username", "")
    return _bot_username


def reply_keyboard():
    rows = [[BTN_PROFILE, BTN_SUBSCRIPTION]]
    if WEBAPP_URL:
        rows.append([{"text": BTN_APP, "web_app": {"url": WEBAPP_URL}}])
    else:
        rows.append([BTN_APP])
    return {"keyboard": rows, "resize_keyboard": True, "is_persistent": True}


def back_markup():
    return {"inline_keyboard": [[{"text": "⬅ В меню", "callback_data": "menu"}]]}


def menu_markup():
    rows = [
        [{"text": "Профиль", "callback_data": "profile"}, {"text": "Подписка", "callback_data": "subscription"}],
        [{"text": "Ключи", "callback_data": "keys"}, {"text": "Устройства", "callback_data": "devices"}],
        [{"text": "Рефералы", "callback_data": "referral"}, {"text": "Помощь", "callback_data": "help"}],
    ]
    if WEBAPP_URL:
        rows.append([{"text": "Открыть приложение", "web_app": {"url": WEBAPP_URL}}])
    return {"inline_keyboard": rows}


def trial_status(user):
    left = user.get("trial_until", 0) - int(time.time())
    if left <= 0:
        return "нет"
    days = left // 86400 + (1 if left % 86400 else 0)
    return f"активен, осталось {days} дн."


def screen(name, user, arg=""):
    first = user.get("first_name", "")
    uid = user.get("id")
    record = db.get_user(uid) or {}
    if name == "profile":
        username = f"@{user['username']}" if user.get("username") else "не задан"
        text = (
            f"Профиль\n\nID: {uid}\nИмя: {first}\nUsername: {username}\n\n"
            f"Пробный период: {trial_status(record)}\n"
            f"Приглашено друзей: {record.get('invited', 0)}"
        )
        return text, back_markup()
    if name == "subscription":
        rows = [[{"text": f"{title} · {price} ₽", "callback_data": f"plan:{key}"}] for key, (title, price) in PLANS.items()]
        rows.append([{"text": "⬅ В меню", "callback_data": "menu"}])
        return f"Пробный период: {trial_status(record)}\n\nВыберите тариф:", {"inline_keyboard": rows}
    if name == "plan":
        if arg not in PLANS:
            return "Тариф не найден.", back_markup()
        title, price = PLANS[arg]
        text = (
            f"Тариф «{title}» — {price} ₽\n\n"
            "Оплата пока не подключена, подписка не активируется автоматически."
        )
        return text, back_markup()
    if name == "keys":
        return "Ключи\n\nКлючи выдаются после активации подписки или пробного периода. Сейчас ключей нет.", back_markup()
    if name == "devices":
        return "Устройства\n\nПодключено: 0 из 3.", back_markup()
    if name == "referral":
        link = f"https://t.me/{get_bot_username()}?start=ref{uid}"
        text = (
            f"Реферальная программа\n\n"
            f"Ваша ссылка:\n{link}\n\n"
            "Друг получает 3 дня пробного периода, вы тоже получаете 3 дня за каждого друга.\n"
            f"Приглашено: {record.get('invited', 0)}"
        )
        return text, back_markup()
    if name == "help":
        text = (
            "Помощь\n\n"
            "/start — начать работу\n"
            "/menu — главное меню\n"
            "/help — эта справка"
        )
        return text, back_markup()
    return f"Главное меню, {first}:", menu_markup()



def send(chat_id, text, markup):
    call("sendMessage", {"chat_id": chat_id, "text": text, "reply_markup": markup})


def edit_or_send(chat_id, message_id, text, markup):
    if message_id:
        result = call("editMessageText", {"chat_id": chat_id, "message_id": message_id, "text": text, "reply_markup": markup})
        if result.get("ok"):
            return
    send(chat_id, text, markup)


def handle_callback(cb):
    call("answerCallbackQuery", {"callback_query_id": cb["id"]})
    msg = cb.get("message") or {}
    chat_id = msg.get("chat", {}).get("id")
    if not chat_id:
        return
    name, _, arg = cb.get("data", "").partition(":")
    text, markup = screen(name, cb["from"], arg)
    edit_or_send(chat_id, msg.get("message_id"), text, markup)


def handle_start(message, user, payload):
    chat_id = message["chat"]["id"]
    if db.get_user(user["id"]) is None:
        referrer = payload[3:] if payload.startswith("ref") and payload[3:].isdigit() else None
        if referrer and db.register_referral(user["id"], referrer):
            call("sendMessage", {"chat_id": int(referrer), "text": "По вашей ссылке зарегистрировался новый пользователь. Вам начислено 3 дня пробного периода."})
            note = "Вы пришли по приглашению: вам начислено 3 дня пробного периода."
        else:
            db.save_user(user["id"], {"id": user["id"], "trial_until": 0, "referrer": None, "invited": 0})
            db.add_trial_days(user["id"], 3)
            note = "Вам начислено 3 дня бесплатного пробного периода."
    else:
        note = "С возвращением!"

    send(chat_id, f"Привет, {user.get('first_name', '')}! {note}", reply_keyboard())
    body, markup = screen("menu", user)
    send(chat_id, body, markup)


def handle_message(message):
    chat_id = message["chat"]["id"]
    user = message.get("from", {})
    text = message.get("text", "").strip()

    if text.startswith("/start"):
        handle_start(message, user, text[6:].strip())
    elif text in ("/menu", "/help"):
        name = "help" if text == "/help" else "menu"
        body, markup = screen(name, user)
        send(chat_id, body, markup)
    elif text == BTN_PROFILE:
        body, markup = screen("profile", user)
        send(chat_id, body, markup)
    elif text == BTN_SUBSCRIPTION:
        body, markup = screen("subscription", user)
        send(chat_id, body, markup)
    else:
        body, markup = screen("menu", user)
        send(chat_id, "Выберите раздел в меню:", markup)


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
            if "callback_query" in update:
                handle_callback(update["callback_query"])
            elif "message" in update and "text" in update["message"]:
                handle_message(update["message"])
        except Exception as exc:
            print("handler error:", exc)
        # Всегда 200, иначе Telegram будет повторять update
        self._reply(200, "ok")

    def _reply(self, code, body):
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))
