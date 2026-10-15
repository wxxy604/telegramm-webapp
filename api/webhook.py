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
    # key: (название, дни, цена в звёздах Telegram Stars)
    "1m": ("1 месяц", 30, 150),
    "3m": ("3 месяца", 90, 400),
    "12m": ("12 месяцев", 365, 1400),
}

_bot_username = None

CRYPTO_TOKEN = os.getenv("CRYPTO_PAY_TOKEN", "")
CRYPTO_PRICES = {"1m": 2, "3m": 5, "12m": 18}  # цены в USDT


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


from docs_privacy import PRIVACY  # noqa: E402
from docs_terms import TERMS  # noqa: E402

DOCS = {"terms": ("Пользовательское соглашение", TERMS), "privacy": ("Политика конфиденциальности", PRIVACY)}


def split_sections(text):
    """Режет документ по разделам: каждый пункт вида '1. Общие положения' — отдельная часть.
    Текст не меняется, только делится по границам разделов."""
    import re
    lines = text.split("\n")
    starts = [i for i, line in enumerate(lines) if re.match(r"^\d+\. ", line)]
    if not starts:
        return [text]
    parts = ["\n".join(lines[:starts[0]]).strip()]
    for idx, start in enumerate(starts):
        end = starts[idx + 1] if idx + 1 < len(starts) else len(lines)
        parts.append("\n".join(lines[start:end]).strip())
    return [p for p in parts if p]


def send_long(chat_id, text, markup=None):
    """Отправляет документ по разделам, с номером части. Каждый раздел — отдельным сообщением.
    Если раздел длиннее лимита Telegram (4096 символов), режется по абзацам."""
    limit = 3900
    chunks = []
    for section in split_sections(text):
        while len(section) > limit:
            cut = section.rfind("\n", 0, limit)
            if cut <= 0:
                cut = limit
            chunks.append(section[:cut].strip())
            section = section[cut:].strip()
        chunks.append(section)
    total = len(chunks)
    for i, chunk in enumerate(chunks, 1):
        label = f"({i}/{total})\n\n" if total > 1 else ""
        send(chat_id, label + chunk, markup if i == total else None)


def group_pages(text, limit=3500):
    """Собирает разделы документа в страницы, не длиннее limit символов."""
    pages = []
    current = ""
    for section in split_sections(text):
        if current and len(current) + len(section) + 2 > limit:
            pages.append(current)
            current = section
        else:
            current = f"{current}\n\n{section}" if current else section
    if current:
        pages.append(current)
    return pages


def page_markup(key, page, total):
    row = []
    if page > 1:
        row.append({"text": "◀️ Назад", "callback_data": f"pg:{key}:{page - 1}"})
    row.append({"text": f"{page} / {total}", "callback_data": "noop"})
    if page < total:
        row.append({"text": "Вперёд ▶️", "callback_data": f"pg:{key}:{page + 1}"})
    return {"inline_keyboard": [row, [{"text": "📄 К документам", "callback_data": "docs"}]]}


def show_doc_page(chat_id, message_id, key, page):
    """Показывает страницу документа. Если message_id задан, сообщение редактируется, иначе отправляется новое."""
    title, text = DOCS[key]
    pages = group_pages(text)
    page = max(1, min(page, len(pages)))
    body = f"{title}\n\n{pages[page - 1]}"
    edit_or_send(chat_id, message_id, body, page_markup(key, page, len(pages)))


def docs_markup():
    return {"inline_keyboard": [
        [{"text": "📜 Пользовательское соглашение", "callback_data": "doc:terms"}],
        [{"text": "🔒 Политика конфиденциальности", "callback_data": "doc:privacy"}],
        [{"text": "◀️ Назад в меню", "callback_data": "menu"}],
    ]}


def back_markup():
    return {"inline_keyboard": [[{"text": "◀️ Назад в меню", "callback_data": "menu"}]]}


WELCOME_TEXT = (
    "Добро пожаловать в SupplineVPN!\n\n"
    "Здесь вы оформляете доступ, получаете ключи и управляете подпиской. "
    "Выберите раздел ниже."
)


def menu_markup():
    rows = [
        [{"text": "Моя подписка", "callback_data": "subscription", "style": "primary"}],
        [{"text": "Купить", "callback_data": "subscription", "style": "success"}],
        [{"text": "Функции", "callback_data": "features"}, {"text": "Реф. система", "callback_data": "referral"}],
        [{"text": "О сервисе", "callback_data": "about"}],
    ]
    if WEBAPP_URL:
        rows[-1].append({"text": "Mini app", "web_app": {"url": WEBAPP_URL}})
    else:
        rows[-1].append({"text": "Mini app", "callback_data": "about"})
    rows.append([{"text": "FAQ", "callback_data": "help"}, {"text": "Поддержка", "callback_data": "support"}])
    return {"inline_keyboard": rows}


def paid_status(user):
    left = user.get("paid_until", 0) - int(time.time())
    if left <= 0:
        return "не активна"
    days = left // 86400 + (1 if left % 86400 else 0)
    return f"активна, осталось {days} дн."


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
        rows = []
        for key, (title, _, stars) in PLANS.items():
            rows.append([{"text": f"⭐ {title} · {stars} звёзд", "callback_data": f"buy:{key}"}])
            rows.append([{"text": f"💵 {title} · {CRYPTO_PRICES[key]} USDT", "callback_data": f"cbuy:{key}"}])
        rows.append([{"text": "◀️ Назад в меню", "callback_data": "menu"}])
        paid = paid_status(record)
        return f"Подписка: {paid}\nПробный период: {trial_status(record)}\n\nВыберите тариф:", {"inline_keyboard": rows}
    if name == "plan":
        if arg not in PLANS:
            return "Тариф не найден.", back_markup()
        title, _, stars = PLANS[arg]
        markup = {"inline_keyboard": [
            [{"text": f"Оплатить {stars} ⭐", "callback_data": f"buy:{arg}"}],
            [{"text": f"Оплатить {CRYPTO_PRICES[arg]} USDT", "callback_data": f"cbuy:{arg}"}],
            [{"text": "⬅ К тарифам", "callback_data": "subscription"}],
        ]}
        return f"Тариф «{title}» — {stars} ⭐\n\nОплата звёздами Telegram внутри бота.", markup
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
    if name == "features":
        text = (
            "Функции SupplineVPN\n\n"
            "• Персональный ключ доступа\n"
            "• Подключение нескольких устройств\n"
            "• Пробный период 3 дня\n"
            "• Оплата звёздами Telegram или USDT"
        )
        return text, back_markup()
    if name == "about":
        text = (
            "О сервисе SupplineVPN\n\n"
            "Сервис предоставляет доступ к защищённому интернет-соединению. "
            "Оплата, подписка и ключи управляются прямо в боте."
        )
        return text, back_markup()
    if name == "support":
        text = "Поддержка\n\nПо всем вопросам напишите сюда, в этот чат. Мы ответим как можно скорее."
        return text, back_markup()
    if name == "help":
        text = (
            "Помощь\n\n"
            "/start — начать работу\n"
            "/menu — главное меню\n"
            "/help — эта справка"
        )
        return text, back_markup()
    return WELCOME_TEXT, menu_markup()



def send(chat_id, text, markup):
    call("sendMessage", {"chat_id": chat_id, "text": text, "reply_markup": markup})


def edit_or_send(chat_id, message_id, text, markup):
    if message_id:
        result = call("editMessageText", {"chat_id": chat_id, "message_id": message_id, "text": text, "reply_markup": markup})
        if result.get("ok"):
            return
    send(chat_id, text, markup)


def send_invoice(chat_id, user_id, key):
    title, days, stars = PLANS[key]
    call("sendInvoice", {
        "chat_id": chat_id,
        "title": f"VPN: {title}",
        "description": f"Доступ к VPN на {days} дн.",
        "payload": f"plan:{key}:{user_id}",
        "provider_token": "",
        "currency": "XTR",
        "prices": [{"label": title, "amount": stars}],
    })


def handle_pre_checkout(pcq):
    # Подтверждаем оплату, если тариф известен
    payload = pcq.get("invoice_payload", "")
    ok = payload.startswith("plan:") and payload.split(":")[1] in PLANS
    call("answerPreCheckoutQuery", {
        "pre_checkout_query_id": pcq["id"],
        "ok": ok,
        "error_message": "" if ok else "Тариф недоступен, попробуйте позже.",
    })


def handle_successful_payment(message):
    payment = message["successful_payment"]
    key = payment["invoice_payload"].split(":")[1]
    user_id = message["from"]["id"]
    _, days, _ = PLANS[key]
    db.extend_paid(user_id, days)
    send(message["chat"]["id"], f"Оплата прошла. Подписка продлена на {days} дн. Проверьте статус в разделе «Подписка».", reply_keyboard())


def handle_web_app_data(message):
    chat_id = message["chat"]["id"]
    user_id = message["from"]["id"]
    try:
        data = json.loads(message["web_app_data"]["data"])
    except (ValueError, KeyError):
        send(chat_id, "Не удалось прочитать выбор тарифа.", reply_keyboard())
        return
    if data.get("action") == "buy" and data.get("plan") in PLANS:
        send_invoice(chat_id, user_id, data["plan"])
    else:
        send(chat_id, "Тариф не найден.", reply_keyboard())


def crypto_call(method, payload):
    req = request.Request(
        f"https://pay.crypt.bot/api/{method}",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Crypto-Pay-API-Token": CRYPTO_TOKEN,
            "Content-Type": "application/json",
            # Crypto Pay блокирует стандартный User-Agent Python (ошибка 1010)
            "User-Agent": "Mozilla/5.0 (compatible; SupplineVPNbot/1.0)",
        },
    )
    try:
        with request.urlopen(req, timeout=10) as resp:
            body = json.load(resp)
    except error.HTTPError as exc:
        print("crypto error:", method, exc.code, exc.read()[:300])
        return None
    return body.get("result") if body.get("ok") else None


def crypto_invoice(chat_id, user_id, key):
    title, _, _ = PLANS[key]
    inv = crypto_call("createInvoice", {
        "asset": "USDT",
        "amount": str(CRYPTO_PRICES[key]),
        "description": f"VPN: {title}",
        "payload": f"{user_id}:{key}",
        "expires_in": 3600,
    })
    if not inv:
        send(chat_id, "Не удалось создать счёт в Crypto Pay. Попробуйте позже.", back_markup())
        return
    markup = {"inline_keyboard": [
        [{"text": f"Оплатить {CRYPTO_PRICES[key]} USDT", "url": inv["bot_invoice_url"]}],
        [{"text": "Я оплатил, проверить", "callback_data": f"check:{inv['invoice_id']}:{key}"}],
    ]}
    send(chat_id, f"Счёт на «{title}»: {CRYPTO_PRICES[key]} USDT. Оплатите по кнопке и нажмите «Я оплатил».", markup)


def crypto_check(chat_id, user_id, invoice_id, key):
    result = crypto_call("getInvoices", {"invoice_ids": str(invoice_id)})
    items = (result or {}).get("items", [])
    if not items or items[0].get("status") != "paid":
        send(chat_id, "Оплата пока не найдена. Подождите минуту и нажмите «Я оплатил» ещё раз.", back_markup())
        return
    # Защита: счёт должен принадлежать этому пользователю и этому тарифу
    if items[0].get("payload") != f"{user_id}:{key}":
        send(chat_id, "Этот счёт не относится к вашему аккаунту.", back_markup())
        return
    if not db.mark_invoice(invoice_id):
        send(chat_id, "Эта оплата уже учтена.", back_markup())
        return
    _, days, _ = PLANS[key]
    db.extend_paid(user_id, days)
    send(chat_id, f"Оплата USDT получена. Подписка продлена на {days} дн.", reply_keyboard())


def handle_callback(cb):
    call("answerCallbackQuery", {"callback_query_id": cb["id"]})
    msg = cb.get("message") or {}
    chat_id = msg.get("chat", {}).get("id")
    if not chat_id:
        return
    name, _, arg = cb.get("data", "").partition(":")
    if name == "buy" and arg in PLANS:
        send_invoice(chat_id, cb["from"]["id"], arg)
        return
    if name == "cbuy" and arg in PLANS:
        crypto_invoice(chat_id, cb["from"]["id"], arg)
        return
    if name == "check":
        invoice_id, _, key = arg.partition(":")
        crypto_check(chat_id, cb["from"]["id"], invoice_id, key)
        return
    if name == "docs":
        edit_or_send(chat_id, msg.get("message_id"), "📄 Документы\n\nВыберите документ:", docs_markup())
        return
    if name == "noop":
        return
    if name == "doc" and arg in DOCS:
        show_doc_page(chat_id, msg.get("message_id"), arg, 1)
        return
    if name == "pg":
        key, _, page = arg.partition(":")
        if key in DOCS and page.isdigit():
            show_doc_page(chat_id, msg.get("message_id"), key, int(page))
        return
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

    # Убираем нижнюю клавиатуру у пользователя, остаётся только инлайн-меню
    send(chat_id, f"Привет, {user.get('first_name', '')}! {note}", {"remove_keyboard": True})
    send(chat_id, WELCOME_TEXT, menu_markup())


def handle_message(message):
    chat_id = message["chat"]["id"]
    user = message.get("from", {})
    text = message.get("text", "").strip()

    if text.startswith("/start"):
        payload = text[6:].strip()
        if payload.startswith("buy_") and payload[4:] in PLANS:
            send_invoice(chat_id, user["id"], payload[4:])
        elif payload.startswith("cbuy_") and payload[5:] in PLANS:
            crypto_invoice(chat_id, user["id"], payload[5:])
        else:
            handle_start(message, user, payload)
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
            if "pre_checkout_query" in update:
                handle_pre_checkout(update["pre_checkout_query"])
            elif "callback_query" in update:
                handle_callback(update["callback_query"])
            elif "message" in update and "successful_payment" in update["message"]:
                handle_successful_payment(update["message"])
            elif "message" in update and "web_app_data" in update["message"]:
                handle_web_app_data(update["message"])
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
