import hashlib
import hmac
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler
from urllib import error, request
from urllib.parse import parse_qs, parse_qsl, urlparse

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
SBP_PRICES = {"1m": 100, "3m": 250, "12m": 900}  # цены в рублях по СБП


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
    return {"inline_keyboard": [[{"text": "Назад в меню", "callback_data": "menu"}]]}


def html_escape(text):
    """Экранирует символы, которые Telegram HTML-разметка принимает как теги."""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


WELCOME_TEXT = (
    "Добро пожаловать в SupplineVPN!\n\n"
    "Здесь вы оформляете доступ, получаете ключи и управляете подпиской. "
    "Выберите раздел ниже."
)


def menu_markup():
    rows = [
        [{"text": "Купить", "callback_data": "buy", "style": "success"}],
        [{"text": "Серверы", "callback_data": "keys"}, {"text": "Реф. система", "callback_data": "referral"}],
        [{"text": "Поддержка", "callback_data": "support"}],
        [{"text": "Документы", "callback_data": "docs"}],
    ]
    if WEBAPP_URL:
        rows.append([{"text": "Открыть приложение", "web_app": {"url": WEBAPP_URL}}])
    return {"inline_keyboard": rows}


def support_markup():
    return {"inline_keyboard": [
        [{"text": "✍️ Написать в поддержку", "callback_data": "ticket"}],
        [{"text": "FAQ", "callback_data": "help"}, {"text": "О сервисе", "callback_data": "about"}],
        [{"text": "Функции", "callback_data": "features"}, {"text": "Документы", "callback_data": "docs"}],
        [{"text": "Назад в меню", "callback_data": "menu"}],
    ]}


ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID", "")  # куда приходят обращения в поддержку (в .env)


def welcome_text(user, record):
    """Приветствие: преимущества VPN и статус подписки сразу, без лишних нажатий."""
    first = html_escape(user.get("first_name", ""))
    return (
        f"<b>Привет, {first}! Добро пожаловать в SupplineVPN</b>\n\n"
        "<blockquote>SupplineVPN обеспечивает стабильное подключение, защиту трафика в публичных сетях "
        "и работу на 3 устройствах одной подпиской.</blockquote>\n\n"
        "\u00a0\n\n"
        "<blockquote><b>Статус вашей подписки:</b></blockquote>\n"
        f"<blockquote>{html_escape(paid_status(record))}</blockquote>"
    )


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


APPS = {
    "ios": ("iPhone / iPad", "Streisand или V2Box (App Store)", "Откройте приложение, нажмите «+» → «Вставить из буфера». Ключ импортируется, выберите сервер и включите подключение."),
    "android": ("Android", "v2rayNG или Hiddify (Google Play)", "Откройте приложение, нажмите «+» → «Импорт из буфера обмена». Выберите сервер и включите подключение."),
    "windows": ("Windows", "Hiddify или v2rayN", "Откройте приложение, нажмите «Вставить ключ» или «Импорт из буфера». Выберите сервер и подключитесь."),
    "macos": ("macOS", "Streisand или Hiddify", "Откройте приложение, выберите «Добавить из буфера». Выберите сервер и включите подключение."),
}


SERVERS_PER_PAGE = 5


def user_servers(user_id):
    """Персональный список серверов пользователя: 3–5 лучших по пингу, без повторов у других."""
    return db.assign_servers(user_id, count_min=3, count_max=5)


def servers_page(user_id, page):
    """Страница персонального списка серверов по SERVERS_PER_PAGE штук.
    callback_data содержит индекс внутри списка пользователя."""
    servers = user_servers(user_id)
    if not servers:
        return "Серверы\n\nПодходящих серверов сейчас нет. Попробуйте позже.", back_markup()
    total_pages = max(1, -(-len(servers) // SERVERS_PER_PAGE))
    page = max(0, min(page, total_pages - 1))
    start = page * SERVERS_PER_PAGE
    rows = []
    for i in range(start, min(start + SERVERS_PER_PAGE, len(servers))):
        s = servers[i]
        rows.append([{"text": f"{s['name']} · {s['ping']} мс", "callback_data": f"srv:{i}"}])
    nav = []
    if page > 0:
        nav.append({"text": "◀️ Назад", "callback_data": f"srvp:{page - 1}"})
    nav.append({"text": f"{page + 1} / {total_pages}", "callback_data": "noop"})
    if page < total_pages - 1:
        nav.append({"text": "Вперёд ▶️", "callback_data": f"srvp:{page + 1}"})
    rows.append(nav)
    rows.append([{"text": "◀️ Назад в меню", "callback_data": "menu"}])
    text = f"Ваши серверы: {len(servers)} шт. Выберите сервер (от быстрого к медленному)."
    return text, {"inline_keyboard": rows}


def server_detail(user_id, index):
    """Текст инструкции и ключа для сервера index из персонального списка пользователя."""
    servers = user_servers(user_id)
    if index < 0 or index >= len(servers):
        return "Сервер не найден. Откройте список серверов заново.", back_markup()
    s = servers[index]
    page = index // SERVERS_PER_PAGE
    lines = [f"Сервер: {s['name']} · {s['ping']} мс", "", "Инструкция по приложениям:"]
    for title, app, how in APPS.values():
        lines.append(f"• {title}: {app}. {how}")
    lines += ["", "Ключ (нажмите на него, чтобы скопировать, и вставьте в приложение):"]
    # Ключ отдельным текстом в <code>: по нажатию Telegram копирует его целиком.
    # Кнопка copy_text здесь не используется: Telegram принимает в ней не больше 256 символов.
    markup = {"inline_keyboard": [
        [{"text": "◀️ К серверам", "callback_data": f"srvp:{page}"}],
    ]}
    return "\n".join(lines) + f"\n<code>{html_escape(s['uri'])}</code>", markup


INIT_DATA_MAX_AGE = 24 * 3600  # секунд, после этого initData считается устаревшим


def verify_init_data(init_data, max_age=INIT_DATA_MAX_AGE):
    """Проверяет подпись initData от Telegram Mini App (алгоритм из документации Telegram).
    Возвращает ID пользователя (строкой) или None, если подпись неверна, данные устарели или их нет."""
    if not init_data or not BOT_TOKEN:
        return None
    data = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = data.pop("hash", "")
    if not received_hash:
        return None
    check_string = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode("utf-8"), hashlib.sha256).digest()
    expected = hmac.new(secret_key, check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received_hash):
        return None
    try:
        auth_date = int(data.get("auth_date", "0"))
        user = json.loads(data.get("user", "{}"))
    except (ValueError, TypeError):
        return None
    if time.time() - auth_date > max_age:
        return None
    uid = user.get("id") if isinstance(user, dict) else None
    return str(uid) if uid else None


def request_user_id(path):
    """Достаёт проверенный ID пользователя из параметра init в адресе запроса."""
    init_data = parse_qs(urlparse(path).query).get("init", [""])[0]
    return verify_init_data(init_data)


def has_access(user):
    now = int(time.time())
    return user.get("paid_until", 0) > now or user.get("trial_until", 0) > now


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
        text = f"Подписка: {paid_status(record)}\nПробный период: {trial_status(record)}"
        markup = {"inline_keyboard": [
            [{"text": "💎 Купить", "callback_data": "buy"}],
            [{"text": "◀️ Назад в меню", "callback_data": "menu"}],
        ]}
        return text, markup
    if name == "buy":
        text = "Купить подписку\n\nВыберите способ оплаты:"
        markup = {"inline_keyboard": [
            [{"text": "💵 CryptoBot (USDT)", "callback_data": "method:crypto"}],
            [{"text": "⭐ TG Stars", "callback_data": "method:stars"}],
            [{"text": "💳 СБП", "callback_data": "method:sbp"}],
            [{"text": "Назад", "callback_data": "menu"}],
        ]}
        return text, markup
    if name == "method":
        if arg == "crypto":
            rows = [[{"text": f"{title} · {CRYPTO_PRICES[k]} USDT", "callback_data": f"cbuy:{k}"}]
                    for k, (title, _, _) in PLANS.items()]
            label = "CryptoBot (USDT)"
        elif arg == "stars":
            rows = [[{"text": f"{title} · {stars} звёзд", "callback_data": f"buy:{k}"}]
                    for k, (title, _, stars) in PLANS.items()]
            label = "TG Stars"
        elif arg == "sbp":
            rows = [[{"text": f"{title} · {SBP_PRICES[k]} ₽", "callback_data": "sbp"}]
                    for k, (title, _, _) in PLANS.items()]
            label = "СБП"
        else:
            return "Способ не найден.", back_markup()
        rows.append([{"text": "Назад", "callback_data": "buy"}])
        return f"Оплата: {label}\n\nВыберите тариф:", {"inline_keyboard": rows}
    if name == "sbp":
        lines = ["Оплата: СБП\n", "Тарифы (цены в рублях):"]
        for key, (title, _, _) in PLANS.items():
            lines.append(f"• {title} — {SBP_PRICES[key]} ₽")
        lines.append("\nОплата по СБП пока недоступна: подключение платёжного провайдера в работе.")
        return "\n".join(lines), {"inline_keyboard": [[{"text": "◀️ Назад", "callback_data": "buy"}]]}
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
        if not has_access(record):
            db.release_servers(uid)
            return "Ключи\n\nДоступа сейчас нет. Оформите подписку или пробный период в разделе «Купить».", back_markup()
        return servers_page(uid, 0)
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
            "SupplineVPN выдаёт персональный ключ доступа.\n"
            "SupplineVPN подключает несколько устройств.\n"
            "SupplineVPN принимает оплату звёздами Telegram, USDT или СБП."
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
        return text, support_markup()
    if name == "help":
        text = (
            "Помощь\n\n"
            "/start — начать работу\n"
            "/menu — главное меню\n"
            "/help — эта справка"
        )
        return text, back_markup()
    return welcome_text(user, record), menu_markup()



def send(chat_id, text, markup, parse_mode=None):
    payload = {"chat_id": chat_id, "text": text, "reply_markup": markup}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    call("sendMessage", payload)


def edit_or_send(chat_id, message_id, text, markup, parse_mode=None):
    if message_id:
        payload = {"chat_id": chat_id, "message_id": message_id, "text": text, "reply_markup": markup}
        if parse_mode:
            payload["parse_mode"] = parse_mode
        result = call("editMessageText", payload)
        if result.get("ok"):
            return
    send(chat_id, text, markup, parse_mode=parse_mode)


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
    if cb.get("data") == "ticket":
        # Всплывающее уведомление поверх чата: подсказка, что делать дальше
        call("answerCallbackQuery", {
            "callback_query_id": cb["id"],
            "text": "Напишите обращение в строке ввода ниже",
            "show_alert": True,
        })
    else:
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
    if name == "srvp" and arg.isdigit():
        uid = cb["from"]["id"]
        if not has_access(db.get_user(uid) or {}):
            edit_or_send(chat_id, msg.get("message_id"), "Серверы доступны с подпиской или пробным периодом.", back_markup())
            return
        text, markup = servers_page(uid, int(arg))
        edit_or_send(chat_id, msg.get("message_id"), text, markup)
        return
    if name == "srv" and arg.isdigit():
        uid = cb["from"]["id"]
        if not has_access(db.get_user(uid) or {}):
            edit_or_send(chat_id, msg.get("message_id"), "Серверы доступны с подпиской или пробным периодом.", back_markup())
            return
        # Инструкция отправляется новым сообщением: список остаётся на месте
        text, markup = server_detail(uid, int(arg))
        send(chat_id, text, markup, parse_mode="HTML")
        return
    if name == "noop":
        return
    if handle_admin_callback(cb, name, arg):
        return
    if name == "ticket":
        db.set_support_wait(cb["from"]["id"])
        # force_reply открывает строку ввода с подсказкой: пользователь сразу пишет обращение
        call("sendMessage", {
            "chat_id": chat_id,
            "text": "✍️ Опишите ваш вопрос одним сообщением. Ответ придёт в этот чат.",
            "reply_markup": {"force_reply": True, "input_field_placeholder": "Ваш вопрос..."},
        })
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
    # Главный экран использует HTML-цитаты, остальные экраны — обычный текст
    parse_mode = "HTML" if name == "menu" else None
    if name == "keys":
        parse_mode = None
    edit_or_send(chat_id, msg.get("message_id"), text, markup, parse_mode=parse_mode)


def handle_start(message, user, payload):
    chat_id = message["chat"]["id"]
    if db.get_user(user["id"]) is None:
        referrer = payload[3:] if payload.startswith("ref") and payload[3:].isdigit() else None
        if referrer and db.register_referral(user["id"], referrer):
            call("sendMessage", {"chat_id": int(referrer), "text": "По вашей ссылке зарегистрировался новый пользователь. Вам начислено 3 дня пробного периода."})
            note = "Вы пришли по приглашению: вам начислено 3 дня пробного периода."
        else:
            # Пробный период только по приглашению. Без реферальной ссылки — регистрация без триала.
            db.save_user(user["id"], {"id": user["id"], "trial_until": 0, "referrer": None, "invited": 0})
            note = "Пробный период доступен по приглашению от друга (3 дня по реферальной ссылке)."
    else:
        note = "С возвращением!"

    # Приветствие со статусом и преимуществами сразу, нижняя клавиатура снимается
    record = db.get_user(user["id"]) or {}
    send(chat_id, welcome_text(user, record), menu_markup(), parse_mode="HTML")
    call("sendMessage", {"chat_id": chat_id, "text": "\u200b", "reply_markup": {"remove_keyboard": True}})


def is_admin(user):
    return bool(ADMIN_CHAT_ID) and str(user.get("id")) == str(ADMIN_CHAT_ID)


STATUS_TITLE = {"open": "🟡 открыто", "answered": "🟢 отвечено", "closed": "⚪ закрыто"}


def ticket_admin_markup(ticket_id):
    return {"inline_keyboard": [
        [{"text": "✉️ Ответить", "callback_data": f"tr:{ticket_id}"},
         {"text": "✅ Закрыть", "callback_data": f"tc:{ticket_id}"}],
    ]}


def notify_admin_new_ticket(ticket):
    """Уведомление админу о новом обращении с кнопками."""
    if not ADMIN_CHAT_ID:
        return
    who = html_escape(ticket.get("name") or "без имени")
    call("sendMessage", {
        "chat_id": ADMIN_CHAT_ID,
        "text": (f"🆕 Новое обращение #{ticket['id']}\n"
                 f"От: {who} (ID {ticket['user_id']})\n\n"
                 f"{html_escape(ticket['text'])}\n\n"
                 f"Ответить: /reply {ticket['id']} текст"),
        "parse_mode": "HTML",
        "reply_markup": ticket_admin_markup(ticket["id"]),
    })


def handle_ticket_text(chat_id, user, text):
    """Пользователь прислал текст обращения: сохраняем, уведомляем админа."""
    ticket_id = db.create_ticket(user["id"], user.get("first_name", ""), text)
    notify_admin_new_ticket(db.get_ticket(ticket_id))
    send(chat_id, f"Обращение #{ticket_id} принято. Ответ придёт в этот чат.", back_markup())


def send_ticket_reply(ticket, answer):
    """Отправляет ответ пользователю, обновляет статус обращения. Закрытое обращение не отвечается."""
    if ticket.get("status") == "closed":
        return False
    ticket["status"] = "answered"
    ticket["reply"] = answer
    db.save_ticket(ticket)
    call("sendMessage", {"chat_id": int(ticket["user_id"]),
                         "text": f"Ответ поддержки на обращение #{ticket['id']}:\n\n{answer}"})
    return True


def close_ticket(ticket):
    ticket["status"] = "closed"
    db.save_ticket(ticket)
    call("sendMessage", {"chat_id": int(ticket["user_id"]),
                         "text": f"Обращение #{ticket['id']} закрыто. Если вопрос остался, напишите новое обращение."})


def handle_reply(chat_id, user, text):
    """Команда администратора: /reply <номер> <текст>."""
    if not is_admin(user):
        return
    parts = text.split(maxsplit=2)
    if len(parts) < 3 or not parts[1].isdigit():
        send(chat_id, "Формат: /reply <номер> <текст ответа>", None)
        return
    ticket = db.get_ticket(int(parts[1]))
    if not ticket:
        send(chat_id, f"Обращение #{parts[1]} не найдено.", None)
        return
    if not send_ticket_reply(ticket, parts[2]):
        send(chat_id, f"Обращение #{ticket['id']} закрыто, ответить нельзя.", None)
        return
    send(chat_id, f"Ответ отправлен по обращению #{ticket['id']}.", None)


def handle_tickets_list(chat_id, user):
    """Команда администратора /tickets: последние 10 обращений со статусами."""
    if not is_admin(user):
        return
    tickets = db.list_tickets(10)
    if not tickets:
        send(chat_id, "Обращений пока нет.", None)
        return
    lines = ["Последние обращения:"]
    for t in tickets:
        lines.append(f"#{t['id']} · {STATUS_TITLE.get(t.get('status', 'open'), '—')} · "
                     f"{t.get('name') or 'без имени'}: {t['text'][:60]}")
    send(chat_id, "\n".join(lines), None)


def handle_admin_callback(cb, name, arg):
    """Кнопки админа: «Ответить» (просит текст) и «Закрыть». Возвращает True, если обработано."""
    if name not in ("tr", "tc") or not arg.isdigit():
        return False
    if not is_admin(cb["from"]):
        return True
    chat_id = cb["message"]["chat"]["id"]
    ticket = db.get_ticket(int(arg))
    if not ticket:
        send(chat_id, f"Обращение #{arg} не найдено.", None)
        return True
    if name == "tc":
        if ticket.get("status") == "closed":
            send(chat_id, f"Обращение #{arg} уже закрыто.", None)
            return True
        close_ticket(ticket)
        db.clear_admin_reply_wait(cb["from"]["id"])
        send(chat_id, f"Обращение #{arg} закрыто, пользователь уведомлён.", None)
        return True
    # Ответить: закрытое обращение нельзя, иначе показываем текст обращения и подсказку
    if ticket.get("status") == "closed":
        send(chat_id, f"Обращение #{arg} закрыто, ответить нельзя.", None)
        return True
    db.set_admin_reply_wait(cb["from"]["id"], arg)
    call("sendMessage", {
        "chat_id": chat_id,
        "text": (f"✉️ Ответ на обращение #{arg}\n"
                 f"От: {ticket.get('name') or 'без имени'} (ID {ticket['user_id']})\n\n"
                 f"Вопрос:\n{ticket['text']}\n\n"
                 f"Напишите ответ одним сообщением. Он сразу уйдёт пользователю."),
        "reply_markup": {"force_reply": True, "input_field_placeholder": f"Ответ на #{arg}..."},
    })
    return True


def handle_message(message):
    chat_id = message["chat"]["id"]
    user = message.get("from", {})
    text = message.get("text", "").strip()

    if text.startswith("/reply"):
        handle_reply(chat_id, user, text)
        return
    if text == "/tickets":
        handle_tickets_list(chat_id, user)
        return
    if is_admin(user) and text and not text.startswith("/"):
        pending = db.pop_admin_reply_wait(user["id"])
        if pending:
            ticket = db.get_ticket(int(pending))
            if ticket and send_ticket_reply(ticket, text):
                send(chat_id, f"Ответ отправлен по обращению #{pending}.", None)
            elif ticket:
                send(chat_id, f"Обращение #{pending} закрыто, ответить нельзя.", None)
            return
    if text and not text.startswith("/") and db.pop_support_wait(user["id"]):
        handle_ticket_text(chat_id, user, text)
        return

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
        # Данные для мини приложения: статус подписки и пробного периода (без секретов)
        if "servers=" in self.path:
            self._servers()
            return
        if "init=" in self.path:
            self._me()
            return
        self._reply(200, "bot is alive")

    def _servers(self):
        """Персональный список серверов пользователя для мини приложения. Без доступа — пусто."""
        uid = request_user_id(self.path)
        servers = []
        if uid and has_access(db.get_user(uid) or {}):
            servers = [
                {"name": s["name"], "ping": s["ping"], "uri": s["uri"]}
                for s in user_servers(uid)
            ]
        body = json.dumps({"servers": servers, "access": bool(servers)}, ensure_ascii=False)
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))

    def _me(self):
        uid = request_user_id(self.path)
        if not uid:
            self._reply(403, "forbidden")
            return
        record = db.get_user(uid) or {}
        now = int(time.time())
        body = json.dumps({
            "paid_until": record.get("paid_until", 0),
            "trial_until": record.get("trial_until", 0),
            "now": now,
        })
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))

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
