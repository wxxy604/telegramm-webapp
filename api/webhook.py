import hashlib
import hmac
import json
import os
import re
import sys
import time
from http.server import BaseHTTPRequestHandler
from urllib import error, request
from urllib.parse import parse_qs, parse_qsl, urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db  # noqa: E402
import support  # noqa: E402
import support_bot  # noqa: E402
import platega  # noqa: E402
from docs_privacy import PRIVACY  # noqa: E402
from docs_terms import TERMS  # noqa: E402

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
WEBAPP_URL = os.getenv("WEBAPP_URL", "")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")
CRON_SECRET = os.getenv("CRON_SECRET", "")  # секрет для Vercel Cron (эндпоинт ?remind=1)
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID", "")  # куда приходят обращения в поддержку

BTN_PROFILE = "Профиль"
BTN_SUBSCRIPTION = "Подписка"
BTN_APP = "Мини приложение"

PLANS = {
    # key: (название, дни, цена в звёздах Telegram Stars)
    "1m": ("1 месяц", 30, 150),
    "3m": ("3 месяца", 90, 400),
    "12m": ("12 месяцев", 365, 1400),
}

CRYPTO_TOKEN = os.getenv("CRYPTO_PAY_TOKEN", "")
CRYPTO_PRICES = {"1m": 2, "3m": 5, "12m": 18}  # цены в USDT
SBP_PRICES = {"1m": 100, "3m": 250, "12m": 900}  # цены в рублях по СБП

KEY_TTL = 30 * 86400  # сек: ключи действуют 30 дней с оплаты или пробного периода
REFRESH_COOLDOWN = 3 * 3600  # сек: серверы можно обновить не чаще раза в 3 часа
DAY = 86400
SERVERS_PER_PAGE = 5
INIT_DATA_MAX_AGE = 24 * 3600  # секунд, после этого initData считается устаревшим

DOCS = {
    "terms": ("Пользовательское соглашение", TERMS),
    "privacy": ("Политика конфиденциальности", PRIVACY),
}

_bot_username = None


def _clean_payload(payload):
    """Telegram отвергает reply_markup: null / пустую клавиатуру и пустой текст (400).
    Убираем такие поля до отправки, чтобы ни один вызов не падал из-за них."""
    p = dict(payload)
    markup = p.get("reply_markup")
    if markup is None or (isinstance(markup, dict) and not markup.get("inline_keyboard", markup.get("keyboard", True))):
        p.pop("reply_markup", None)
    if "text" in p:
        p["text"] = (str(p["text"]) or "").strip() or "—"
    return p


def call(method, payload):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    payload = _clean_payload(payload)
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


def split_sections(text):
    """Режет документ по разделам: каждый пункт вида '1. Общие положения' — отдельная часть."""
    lines = text.split("\n")
    starts = [i for i, line in enumerate(lines) if re.match(r"^\d+\. ", line)]
    if not starts:
        return [text]
    parts = ["\n".join(lines[:starts[0]]).strip()]
    for idx, start in enumerate(starts):
        end = starts[idx + 1] if idx + 1 < len(starts) else len(lines)
        parts.append("\n".join(lines[start:end]).strip())
    return [p for p in parts if p]


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
        row.append({"text": "Назад", "callback_data": f"pg:{key}:{page - 1}"})
    row.append({"text": f"{page} / {total}", "callback_data": "noop"})
    if page < total:
        row.append({"text": "Вперёд", "callback_data": f"pg:{key}:{page + 1}"})
    return {"inline_keyboard": [row, [{"text": "К документам", "callback_data": "docs"}]]}


def show_doc_page(chat_id, message_id, key, page):
    """Показывает страницу документа. Если message_id задан, сообщение редактируется, иначе отправляется новое."""
    title, text = DOCS[key]
    pages = group_pages(text)
    page = max(1, min(page, len(pages)))
    body = f"{title}\n\n{pages[page - 1]}"
    edit_or_send(chat_id, message_id, body, page_markup(key, page, len(pages)))


def docs_markup():
    return {"inline_keyboard": [
        [{"text": "Пользовательское соглашение", "callback_data": "doc:terms"}],
        [{"text": "Политика конфиденциальности", "callback_data": "doc:privacy"}],
        [{"text": "Назад в меню", "callback_data": "menu"}],
    ]}


def back_markup():
    return {"inline_keyboard": [[{"text": "Назад в меню", "callback_data": "menu"}]]}


def html_escape(text):
    """Экранирует символы, которые Telegram HTML-разметка принимает как теги."""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def menu_markup():
    rows = [
        [{"text": "Купить подписку", "callback_data": "buy", "style": "success"}],
        [{"text": "Серверы", "callback_data": "keys"}, {"text": "Рефералы", "callback_data": "referral"}],
        [{"text": "Поддержка", "callback_data": "support"}, {"text": "Документы", "callback_data": "docs"}],
    ]
    if WEBAPP_URL:
        rows.append([{"text": "Открыть приложение", "web_app": {"url": WEBAPP_URL}}])
    return {"inline_keyboard": rows}


def support_markup():
    return {"inline_keyboard": [
        [{"text": "Написать обращение", "callback_data": "ticket"}],
        [{"text": "FAQ", "callback_data": "help"}, {"text": "О сервисе", "callback_data": "about"}],
        [{"text": "Возможности", "callback_data": "features"}, {"text": "Документы", "callback_data": "docs"}],
        [{"text": "Назад в меню", "callback_data": "menu"}],
    ]}


def welcome_text(user, record):
    """Приветствие главного экрана: статус подписки и пробного периода."""
    first = html_escape(user.get("first_name", ""))
    return (
        f"<b>Привет, {first}!</b>\n"
        "Добро пожаловать в <b>SupplineVPN</b>.\n\n"
        "<blockquote>Стабильное подключение и защита трафика в публичных сетях.\n"
        "Один доступ работает на 3 устройствах.</blockquote>\n\n"
        "<b>Ваш статус</b>\n"
        f"Подписка: {html_escape(paid_status(record))}\n"
        f"Пробный период: {html_escape(trial_status(record))}"
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


def keys_active(user_id):
    """Ключи действуют: есть доступ (подписка или пробный период) и не прошло KEY_TTL с даты выдачи.
    Дата выдачи ставится при оплате и выдаче пробного периода (db.py). Старым пользователям без даты
    она оценивается как конец подписки минус KEY_TTL."""
    user = db.get_user(user_id) or {}
    if not has_access(user):
        return False
    now = int(time.time())
    if "keys_issued_at" not in user:
        if user.get("paid_until"):
            user["keys_issued_at"] = max(int(user["paid_until"]) - KEY_TTL, 0)
        else:
            user["keys_issued_at"] = now
        db.save_user(user_id, user)
    return now - int(user["keys_issued_at"]) < KEY_TTL


def refresh_left(user_id):
    """Секунд до следующего обновления серверов (0 — можно обновить)."""
    u = db.get_user(user_id) or {}
    return max(0, REFRESH_COOLDOWN - (int(time.time()) - int(u.get("servers_refreshed_at", 0))))


def refresh_servers(user_id):
    """Обновляет персональный набор серверов. Общая логика для бота и мини приложения.
    Возвращает None при успехе или текст ошибки для пользователя."""
    if not keys_active(user_id):
        return "Серверы доступны с подпиской или пробным периодом."
    left = refresh_left(user_id)
    if left > 0:
        return f"Обновить серверы можно через {left // 3600} ч {(left % 3600) // 60} мин."
    user = db.get_user(user_id) or {"id": user_id, "trial_until": 0, "referrer": None, "invited": 0}
    user["servers_seed"] = int(user.get("servers_seed", 0)) + 1
    user["servers_refreshed_at"] = int(time.time())
    db.save_user(user_id, user)
    return None


def _tcp_ping_ms(uri_without_name):
    """TCP-задержка до host:port из vless:// ссылки в мс. При ошибке или таймауте — 0."""
    import socket
    from urllib.parse import urlsplit

    try:
        parts = urlsplit(uri_without_name)
        host, port = parts.hostname, parts.port
        if not host or not port:
            return 0
        start = time.perf_counter()
        with socket.create_connection((host, port), timeout=1.0):
            return round((time.perf_counter() - start) * 1000)
    except (OSError, ValueError):
        return 0


def get_user_vless_servers(user_id):
    """Персональный набор из 3 серверов. Набор закреплён за пользователем и номером обновления
    (servers_seed), поэтому между обновлениями не меняется."""
    import random
    from urllib.parse import quote

    if not keys_active(user_id):
        return []
    try:
        pool = db.get_servers_pool()
        all_links = [s["uri"] for s in pool if isinstance(s, dict) and str(s.get("uri", "")).startswith("vless://")]
        if not all_links:
            print("servers:pool is empty or has no vless uri")
            return []
        user = db.get_user(user_id) or {}
        rng = random.Random(f"{int(user_id)}:{int(user.get('servers_seed', 0))}")
        user_links = rng.sample(all_links, min(3, len(all_links)))
        servers = []
        for link in user_links:
            # Тело ссылки до первого '#' не меняем; меняем только имя после него
            before_hash = link.split("#", 1)[0]
            node_num = rng.randint(1, 999)
            name = f"MyVPN | Premium Node {node_num}"
            servers.append({
                "name": name,
                "ping": _tcp_ping_ms(before_hash),
                "uri": f"{before_hash}#{quote(name)}",
            })
        return servers
    except Exception as e:
        print(f"Error in get_user_vless_servers: {e!r}")
        return []


def user_servers(user_id):
    """Серверы для бота и мини приложения: одна и та же логика выдачи."""
    if not keys_active(user_id):
        db.release_servers(user_id)
        return []
    return get_user_vless_servers(user_id)


def _refresh_button(user_id):
    left = refresh_left(user_id)
    if left <= 0:
        return {"text": "Обновить серверы", "callback_data": "srvr"}
    return {"text": f"Обновить через {left // 3600} ч {(left % 3600) // 60} мин", "callback_data": "srvr"}


def servers_page(user_id, page):
    """Экран «Серверы» в боте. Список и обновление такие же, как в мини приложении."""
    if not keys_active(user_id):
        text = ("<b>Серверы недоступны</b>\n\n"
                "Оформите подписку или пробный период, чтобы получить доступ к серверам.")
        return text, {"inline_keyboard": [
            [{"text": "Купить подписку", "callback_data": "buy", "style": "success"}],
            [{"text": "Назад в меню", "callback_data": "menu"}],
        ]}
    servers = user_servers(user_id)
    if not servers:
        return ("<b>Серверов пока нет</b>\n\nПопробуйте обновить список немного позже.",
                {"inline_keyboard": [[_refresh_button(user_id)],
                                     [{"text": "Назад в меню", "callback_data": "menu"}]]})
    total_pages = max(1, -(-len(servers) // SERVERS_PER_PAGE))
    page = max(0, min(page, total_pages - 1))
    start = page * SERVERS_PER_PAGE
    rows = []
    for i in range(start, min(start + SERVERS_PER_PAGE, len(servers))):
        s = servers[i]
        rows.append([{"text": f"{s['name']} · {s['ping']} мс", "callback_data": f"srv:{i}"}])
    nav = []
    if page > 0:
        nav.append({"text": "Назад", "callback_data": f"srvp:{page - 1}"})
    nav.append({"text": f"{page + 1} / {total_pages}", "callback_data": "noop"})
    if page < total_pages - 1:
        nav.append({"text": "Вперёд", "callback_data": f"srvp:{page + 1}"})
    rows.append(nav)
    rows.append([_refresh_button(user_id)])
    rows.append([{"text": "Назад в меню", "callback_data": "menu"}])
    text = (f"<b>Ваши серверы: {len(servers)} шт.</b>\n\n"
            "<blockquote>Выберите сервер, чтобы получить ключ и инструкцию.\n"
            "Список можно обновить раз в 3 часа.</blockquote>")
    return text, {"inline_keyboard": rows}


def server_detail(user_id, index):
    """Инструкция и ключ для сервера index из персонального списка пользователя."""
    servers = user_servers(user_id)
    if index < 0 or index >= len(servers):
        return "Сервер не найден. Откройте список серверов заново.", back_markup()
    s = servers[index]
    page = index // SERVERS_PER_PAGE
    lines = [f"<b>{html_escape(s['name'])}</b> · {s['ping']} мс", "", "<b>Инструкция по приложениям</b>"]
    for title, app, how in APPS.values():
        lines.append(f"<b>{title}</b>: {html_escape(app)}.\n<i>{html_escape(how)}</i>")
    lines += ["", "<b>Ключ</b> (нажмите, чтобы скопировать):",
              f"<code>{html_escape(s['uri'])}</code>"]
    markup = {"inline_keyboard": [[{"text": "К серверам", "callback_data": f"srvp:{page}"}]]}
    return "\n".join(lines), markup


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
    if user.get("banned"):
        return False
    now = int(time.time())
    return user.get("paid_until", 0) > now or user.get("trial_until", 0) > now


def screen(name, user, arg=""):
    first = html_escape(user.get("first_name", ""))
    uid = user.get("id")
    record = db.get_user(uid) or {}
    if name == "profile":
        username = f"@{html_escape(user['username'])}" if user.get("username") else "не задан"
        text = (
            "<b>Профиль</b>\n\n"
            f"ID: <code>{uid}</code>\n"
            f"Имя: {first}\n"
            f"Username: {username}\n\n"
            "<blockquote>"
            f"Пробный период: {html_escape(trial_status(record))}\n"
            f"Приглашено друзей: {record.get('invited', 0)}"
            "</blockquote>"
        )
        return text, back_markup()
    if name == "subscription":
        text = (
            "<b>Подписка</b>\n\n"
            "<blockquote>"
            f"Статус: {html_escape(paid_status(record))}\n"
            f"Пробный период: {html_escape(trial_status(record))}"
            "</blockquote>"
        )
        markup = {"inline_keyboard": [
            [{"text": "Купить подписку", "callback_data": "buy", "style": "success"}],
            [{"text": "Назад в меню", "callback_data": "menu"}],
        ]}
        return text, markup
    if name == "buy":
        text = "<b>Оформление подписки</b>\n\nВыберите способ оплаты:"
        markup = {"inline_keyboard": [
            [{"text": "CryptoBot · USDT", "callback_data": "method:crypto"}],
            [{"text": "Telegram Stars", "callback_data": "method:stars"}],
            [{"text": "СБП · рубли", "callback_data": "method:sbp"}],
            [{"text": "Назад в меню", "callback_data": "menu"}],
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
            label = "Telegram Stars"
        elif arg == "sbp":
            rows = [[{"text": f"{title} · {SBP_PRICES[k]} ₽", "callback_data": f"pg:{k}"}]
                    for k, (title, _, _) in PLANS.items()]
            label = "СБП"
        else:
            return "Способ оплаты не найден.", back_markup()
        rows.append([{"text": "Назад", "callback_data": "buy"}])
        return f"<b>Оплата: {label}</b>\n\nВыберите тариф:", {"inline_keyboard": rows}
    if name == "sbp":
        lines = ["<b>Оплата: СБП</b>", "", "<blockquote>Тарифы (цены в рублях):"]
        for key, (title, _, _) in PLANS.items():
            lines.append(f"{title} — {SBP_PRICES[key]} ₽")
        lines.append("Нажмите тариф, откроется ссылка на оплату.</blockquote>")
        rows = [[{"text": f"{title} · {SBP_PRICES[k]} ₽", "callback_data": f"pg:{k}"}]
                for k, (title, _, _) in PLANS.items()]
        rows.append([{"text": "Назад", "callback_data": "buy"}])
        return "\n".join(lines), {"inline_keyboard": rows}
    if name == "plan":
        if arg not in PLANS:
            return "Тариф не найден.", back_markup()
        title, _, stars = PLANS[arg]
        markup = {"inline_keyboard": [
            [{"text": f"Оплатить {stars} звёзд", "callback_data": f"buy:{arg}"}],
            [{"text": f"Оплатить {CRYPTO_PRICES[arg]} USDT", "callback_data": f"cbuy:{arg}"}],
            [{"text": "К тарифам", "callback_data": "subscription"}],
        ]}
        text = (f"<b>Тариф «{title}»</b>\n\n"
                f"{stars} Telegram Stars или {CRYPTO_PRICES[arg]} USDT.\n"
                "Оплата проходит внутри бота.")
        return text, markup
    return screen_rest(name, user, arg, record)


def screen_rest(name, user, arg, record):
    uid = user.get("id")
    if name == "keys":
        return servers_page(uid, 0)
    if name == "devices":
        return ("<b>Устройства</b>\n\nПодключено: 0 из 3.\n"
                "<i>Учёт устройств появится позже.</i>"), back_markup()
    if name == "referral":
        link = f"https://t.me/{get_bot_username()}?start=ref{uid}"
        text = (
            "<b>Реферальная программа</b>\n\n"
            "Друг получает 3 дня пробного периода, вы получаете 3 дня за каждого друга.\n\n"
            f"Ваша ссылка:\n<code>{link}</code>\n\n"
            f"Приглашено: <b>{record.get('invited', 0)}</b>"
        )
        return text, back_markup()
    if name == "features":
        text = (
            "<b>Возможности SupplineVPN</b>\n\n"
            "Персональный набор серверов с ключами\n"
            "Подключение до 3 устройств\n"
            "Обновление серверов раз в 3 часа\n"
            "Оплата Telegram Stars, USDT или СБП"
        )
        return text, back_markup()
    if name == "about":
        text = (
            "<b>О сервисе SupplineVPN</b>\n\n"
            "<blockquote>Доступ к защищённому интернет-соединению.\n"
            "Оплата, подписка и ключи управляются прямо в боте.</blockquote>"
        )
        return text, back_markup()
    if name == "support":
        text = ("<b>Поддержка</b>\n\n"
                "Напишите вопрос в этот чат, мы ответим как можно скорее.")
        return text, support_markup()
    if name == "help":
        text = (
            "<b>Помощь</b>\n\n"
            "<code>/start</code> начать работу\n"
            "<code>/menu</code> главное меню\n"
            "<code>/help</code> эта справка"
        )
        return text, back_markup()
    return welcome_text(user, record), menu_markup()


def send(chat_id, text, markup, parse_mode=None):
    # Telegram отвечает 400 на reply_markup: null и на пустой текст — поэтому их не отправляем
    text = (text or "").strip() or "—"
    payload = {"chat_id": chat_id, "text": text}
    if markup:
        payload["reply_markup"] = markup
    if parse_mode:
        payload["parse_mode"] = parse_mode
    call("sendMessage", payload)


def edit_or_send(chat_id, message_id, text, markup, parse_mode=None):
    text = (text or "").strip() or "—"
    if message_id:
        payload = {"chat_id": chat_id, "message_id": message_id, "text": text}
        if markup:
            payload["reply_markup"] = markup
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
    send(message["chat"]["id"], f"Оплата прошла. Подписка продлена на {days} дн. Статус смотрите в разделе «Подписка».", reply_keyboard())


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


SUPPORT_HOOKS_USER = {
    "notify_new": lambda ticket: notify_admin_new_ticket(ticket),
    "notify_message": lambda ticket, text: notify_admin_ticket_message(ticket, text),
    "notify_closed": lambda ticket: notify_admin_ticket_closed_by_user(ticket),
}
SUPPORT_HOOKS_ADMIN = {
    "close": lambda ticket: close_ticket(ticket),
    "reply": lambda ticket, text: send_ticket_reply(ticket, text),
}


def handle_servers_refresh(cb):
    """Кнопка «Обновить серверы» в боте. Та же логика, что у мини приложения (refresh_servers)."""
    uid = cb["from"]["id"]
    err = refresh_servers(uid)
    call("answerCallbackQuery", {
        "callback_query_id": cb["id"],
        "text": err or "Серверы обновлены",
        "show_alert": bool(err),
    })
    msg = cb.get("message") or {}
    chat_id = msg.get("chat", {}).get("id")
    if err or not chat_id:
        return
    text, markup = servers_page(uid, 0)
    edit_or_send(chat_id, msg.get("message_id"), text, markup, parse_mode="HTML")


def handle_callback(cb):
    sender = cb.get("from") or {}
    if db.is_banned(sender.get("id")) and not is_admin(sender):
        call("answerCallbackQuery", {"callback_query_id": cb["id"], "text": "Доступ ограничен", "show_alert": True})
        return
    data = cb.get("data") or ""
    if data == "srvr":
        handle_servers_refresh(cb)
        return
    # Оплата: pg:<тариф>. Листание документов тоже начинается с pg:, но это pg:<документ>:<страница>
    pg_arg = data.split(":", 1)[1] if data.startswith("pg:") else None
    if pg_arg is not None and ":" not in pg_arg and pg_arg not in DOCS:
        ok, msg_text, url = platega.create_payment(cb["from"]["id"], pg_arg)
        chat_id = cb["message"]["chat"]["id"]
        if ok:
            send(chat_id, msg_text, {"inline_keyboard": [[{"text": "Оплатить", "url": url}]]})
        else:
            send(chat_id, msg_text, None)
        return
    if data == "ticket":
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
    message_id = msg.get("message_id")
    uid = cb["from"]["id"]
    name, _, arg = data.partition(":")
    if name == "buy" and arg in PLANS:
        send_invoice(chat_id, uid, arg)
        return
    if name == "cbuy" and arg in PLANS:
        crypto_invoice(chat_id, uid, arg)
        return
    if name == "check":
        invoice_id, _, key = arg.partition(":")
        crypto_check(chat_id, uid, invoice_id, key)
        return
    if name == "docs":
        edit_or_send(chat_id, message_id, "<b>Документы</b>\n\nВыберите документ:", docs_markup(), parse_mode="HTML")
        return
    if name == "srvp" and arg.isdigit():
        text, markup = servers_page(uid, int(arg))
        edit_or_send(chat_id, message_id, text, markup, parse_mode="HTML")
        return
    if name == "srv" and arg.isdigit():
        if not keys_active(uid):
            text, markup = servers_page(uid, 0)
            edit_or_send(chat_id, message_id, text, markup, parse_mode="HTML")
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
        if is_admin(cb["from"]):
            send(chat_id, "Вы администратор: обращения создают пользователи. Отвечайте кнопкой «Ответить» под обращением.", None)
            return
        db.set_support_wait(uid)
        # force_reply открывает строку ввода с подсказкой: пользователь сразу пишет обращение
        call("sendMessage", {
            "chat_id": chat_id,
            "text": "Опишите ваш вопрос одним сообщением. Ответ придёт в этот чат.",
            "reply_markup": {"force_reply": True, "input_field_placeholder": "Ваш вопрос..."},
        })
        return
    if name == "doc" and arg in DOCS:
        show_doc_page(chat_id, message_id, arg, 1)
        return
    if name == "pg":
        key, _, page = arg.partition(":")
        if key in DOCS and page.isdigit():
            show_doc_page(chat_id, message_id, key, int(page))
        return
    text, markup = screen(name, cb["from"], arg)
    edit_or_send(chat_id, message_id, text, markup, parse_mode="HTML")


def handle_start(message, user, payload):
    chat_id = message["chat"]["id"]
    if db.get_user(user["id"]) is None:
        referrer = payload[3:] if payload.startswith("ref") and payload[3:].isdigit() else None
        if referrer and db.register_referral(user["id"], referrer):
            call("sendMessage", {"chat_id": int(referrer), "text": "По вашей ссылке зарегистрировался новый пользователь. Вам начислено 3 дня пробного периода."})
        else:
            # Пробный период только по приглашению. Без реферальной ссылки — регистрация без триала.
            db.save_user(user["id"], {"id": user["id"], "trial_until": 0, "referrer": None, "invited": 0})

    record = db.get_user(user["id"]) or {}
    send(chat_id, welcome_text(user, record), menu_markup(), parse_mode="HTML")
    call("sendMessage", {"chat_id": chat_id, "text": "\u200b", "reply_markup": {"remove_keyboard": True}})


def is_admin(user):
    """Админ — только владелец, чей Telegram ID совпадает с ADMIN_CHAT_ID.
    Пустой ADMIN_CHAT_ID означает, что админа нет: все админские действия закрыты."""
    if not ADMIN_CHAT_ID or not isinstance(user, dict):
        return False
    uid = user.get("id")
    return uid is not None and str(uid) == str(ADMIN_CHAT_ID).strip()


def ticket_admin_markup(ticket_id):
    return {"inline_keyboard": [
        [{"text": "Ответить", "callback_data": f"tr:{ticket_id}"},
         {"text": "Закрыть", "callback_data": f"tc:{ticket_id}"}],
    ]}


def notify_admin_new_ticket(ticket):
    """Уведомление админу о новом обращении с кнопками."""
    if not ADMIN_CHAT_ID:
        return
    who = html_escape(ticket.get("name") or "без имени")
    call("sendMessage", {
        "chat_id": ADMIN_CHAT_ID,
        "text": (f"Новое обращение #{ticket['id']}\n"
                 f"От: {who} (ID {ticket['user_id']})\n\n"
                 f"{html_escape(ticket['text'])}\n\n"
                 f"Ответить: /reply {ticket['id']} текст"),
        "parse_mode": "HTML",
        "reply_markup": ticket_admin_markup(ticket["id"]),
    })


def handle_ticket_text(chat_id, user, text):
    """Пользователь прислал текст обращения: сохраняем, уведомляем админа."""
    if is_admin(user):
        send(chat_id, "Администратор не создаёт обращения в поддержку.", None)
        return
    ticket_id = db.create_ticket(user["id"], user.get("first_name", ""), text)
    notify_admin_new_ticket(db.get_ticket(ticket_id))
    send(chat_id, f"Обращение #{ticket_id} принято. Ответ придёт в этот чат.", back_markup())


def send_ticket_reply(ticket, answer):
    """Отправляет ответ пользователю в бот и в историю мини приложения. Закрытое обращение не отвечается."""
    if ticket.get("status") == "closed":
        return False
    ticket["reply"] = answer
    ticket["status"] = "answered"
    db.append_ticket_message(ticket, "admin", answer)
    call("sendMessage", {"chat_id": int(ticket["user_id"]),
                         "text": f"Ответ поддержки на обращение #{ticket['id']}:\n\n{answer}"})
    return True


def notify_admin_ticket_message(ticket, text):
    """Сообщение пользователя из мини приложения по уже открытому обращению."""
    if not ADMIN_CHAT_ID:
        return
    who = html_escape(ticket.get("name") or "без имени")
    call("sendMessage", {
        "chat_id": ADMIN_CHAT_ID,
        "text": (f"Новое сообщение в обращении #{ticket['id']}\n"
                 f"От: {who} (ID {ticket['user_id']})\n\n"
                 f"{html_escape(text)}"),
        "parse_mode": "HTML",
        "reply_markup": ticket_admin_markup(ticket["id"]),
    })


def notify_admin_ticket_closed_by_user(ticket):
    """Пользователь закрыл обращение в мини приложении: сообщаем админу."""
    if not ADMIN_CHAT_ID:
        return
    call("sendMessage", {"chat_id": ADMIN_CHAT_ID,
                         "text": f"Пользователь закрыл обращение #{ticket['id']}. Новое сообщение от него откроет его снова."})


def close_ticket(ticket):
    ticket["status"] = "closed"
    db.append_ticket_message(ticket, "system", "Обращение закрыто поддержкой.")
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
    markup, title = support_bot.list_markup(10)
    if markup is None:
        send(chat_id, title, None)
        return
    send(chat_id, title, markup)


def handle_admin_callback(cb, name, arg):
    """Кнопки админа: переключение обращений (tv/tl), «Ответить» (tr) и «Закрыть» (tc).
    Возвращает True, если обработано."""
    if name == "tl":
        if not is_admin(cb["from"]):
            return True
        chat_id = cb["message"]["chat"]["id"]
        markup, title = support_bot.list_markup(10)
        call("sendMessage", {"chat_id": chat_id, "text": title, "reply_markup": markup or {"inline_keyboard": []}})
        return True
    if name == "tv":
        if not is_admin(cb["from"]) or not arg.isdigit():
            return True
        chat_id = cb["message"]["chat"]["id"]
        ticket = db.get_ticket(int(arg))
        if not ticket:
            send(chat_id, f"Обращение #{arg} не найдено.", None)
            return True
        send(chat_id, support_bot.card_text(ticket), support_bot.card_markup(ticket))
        return True
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
        "text": (f"Ответ на обращение #{arg}\n"
                 f"От: {ticket.get('name') or 'без имени'} (ID {ticket['user_id']})\n\n"
                 f"Вопрос:\n{ticket['text']}\n\n"
                 f"Напишите ответ одним сообщением. Он сразу уйдёт пользователю."),
        "reply_markup": {"force_reply": True, "input_field_placeholder": f"Ответ на #{arg}..."},
    })
    return True


def fmt_date(ts):
    """Дата в формате ДД.ММ.ГГГГ или «нет», если ts пустой."""
    if not ts:
        return "нет"
    return time.strftime("%d.%m.%Y", time.localtime(ts))


def handle_admin_command(chat_id, user, text):
    """Команды администратора: /grant, /revoke, /ban, /unban, /user.
    Возвращает True, если сообщение было командой (и обработано)."""
    parts = text.split()
    if not parts:
        return False
    cmd = parts[0].lower()
    if cmd not in ("/grant", "/revoke", "/ban", "/unban", "/user"):
        return False
    if not is_admin(user):
        if not ADMIN_CHAT_ID:
            send(chat_id, "Админ-команды не настроены: в Vercel не задана переменная ADMIN_CHAT_ID. "
                          f"Ваш Telegram ID: {user.get('id')}. Добавьте его как ADMIN_CHAT_ID и сделайте Redeploy.", None)
        else:
            send(chat_id, "Нет доступа: эта команда только для администратора.", None)
        return True
    usage = ("Команды:\n"
             "/grant ID ДНИ — выдать подписку на N дней\n"
             "/revoke ID — снять подписку\n"
             "/ban ID — заблокировать\n"
             "/unban ID — разблокировать\n"
             "/user ID — информация")
    if len(parts) < 2 or not parts[1].isdigit():
        send(chat_id, usage, None)
        return True
    target = int(parts[1])

    if cmd == "/grant":
        if len(parts) < 3 or not parts[2].isdigit() or not (1 <= int(parts[2]) <= 3650):
            send(chat_id, "Укажите число дней от 1 до 3650: /grant ID ДНИ", None)
            return True
        days = int(parts[2])
        u = db.extend_paid(target, days)
        send(chat_id, f"Пользователю {target} выдана подписка на {days} дн. "
                      f"Доступ до {fmt_date(u.get('paid_until'))}.", None)
        call("sendMessage", {"chat_id": target, "text": f"Вам выдана подписка на {days} дн."})
    elif cmd == "/revoke":
        db.revoke_paid(target)
        send(chat_id, f"Подписка пользователя {target} снята.", None)
    elif cmd in ("/ban", "/unban"):
        banned = cmd == "/ban"
        db.set_banned(target, banned)
        send(chat_id, f"Пользователь {target} {'заблокирован' if banned else 'разблокирован'}.", None)
        if banned:
            call("sendMessage", {"chat_id": target, "text": "Доступ к сервису ограничен администратором."})
    else:  # /user
        u = db.get_user(target) or {}
        tickets = len(db.user_ticket_ids(target))
        send(chat_id,
             f"Пользователь {target}\n"
             f"Подписка до: {fmt_date(u.get('paid_until'))}\n"
             f"Пробный до: {fmt_date(u.get('trial_until'))}\n"
             f"Заблокирован: {'да' if u.get('banned') else 'нет'}\n"
             f"Обращений в поддержку: {tickets}", None)
    return True


def handle_message(message):
    chat_id = message["chat"]["id"]
    user = message.get("from", {})
    text = message.get("text", "").strip()

    if handle_admin_command(chat_id, user, text):
        return
    if db.is_banned(user.get("id")) and not is_admin(user):
        return  # заблокированные: сообщения не обрабатываем, ответа нет

    if text.startswith("/start pg_"):
        # Переход из мини приложения с выбранным тарифом
        key = text.split("pg_", 1)[1].strip()
        if key in PLANS:
            ok, msg, url = platega.create_payment(user.get("id"), key)
            send(chat_id, msg, {"inline_keyboard": [[{"text": "Оплатить", "url": url}]]} if ok else None)
        else:
            send(chat_id, "Тариф не найден. Выберите снова в мини приложении.", None)
        return
    if text == "/pay":
        send(chat_id, "Выберите тариф, оплата через СБП (Platega):", {"inline_keyboard": [
            [{"text": "1 месяц · 100 ₽", "callback_data": "pg:1m"}],
            [{"text": "3 месяца · 250 ₽", "callback_data": "pg:3m"}],
            [{"text": "12 месяцев · 900 ₽", "callback_data": "pg:12m"}],
        ]})
        return
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
        send(chat_id, body, markup, parse_mode="HTML")
    elif text == BTN_PROFILE:
        body, markup = screen("profile", user)
        send(chat_id, body, markup, parse_mode="HTML")
    elif text == BTN_SUBSCRIPTION:
        body, markup = screen("subscription", user)
        send(chat_id, body, markup, parse_mode="HTML")
    else:
        send(chat_id, "Выберите раздел в меню:", menu_markup())


REMIND_TEXT = {
    ("paid", "3d"): "Подписка SupplineVPN закончится через 3 дня.\n\nПродлите её, чтобы серверы продолжали работать.",
    ("paid", "1d"): "Подписка SupplineVPN закончится завтра.\n\nПродлите сейчас, чтобы не потерять доступ.",
    ("paid", "end"): "Подписка SupplineVPN закончилась, серверы больше не выдаются.\n\nОформите подписку, чтобы вернуть доступ.",
    ("trial", "3d"): "Пробный период SupplineVPN закончится через 3 дня.\n\nОформите подписку, чтобы не потерять доступ.",
    ("trial", "1d"): "Пробный период SupplineVPN закончится завтра.\n\nОформите подписку, чтобы не потерять доступ.",
    ("trial", "end"): "Пробный период SupplineVPN закончился, серверы больше не выдаются.\n\nОформите подписку, чтобы продолжить.",
}


def _remind_stage(until, now):
    """Этап: '3d', '1d', 'end' (срок истёк недавно), 'old' (истёк давно, молча пропускаем) или None."""
    left = until - now
    if left <= 0:
        return "end" if left > -2 * DAY else "old"
    if left <= DAY:
        return "1d"
    if left <= 3 * DAY:
        return "3d"
    return None


def _remind_user(uid, user, kind):
    """Отправляет напоминание этапа, если он ещё не отправлялся для текущего срока.
    Возвращает True, если сообщение ушло. Меняет user (сохраняет вызывающий код)."""
    field = "paid_until" if kind == "paid" else "trial_until"
    until = int(user.get(field, 0) or 0)
    if until <= 0 or user.get("banned"):
        return False
    stage = _remind_stage(until, int(time.time()))
    if stage is None:
        return False
    state_key = f"remind_{kind}"
    state = user.get(state_key) or {}
    if state.get("until") != until:  # новый срок (после продления) — напоминания начинаются заново
        state = {"until": until, "sent": []}
    sent = set(state.get("sent", []))
    sent_now = False
    if stage == "old":
        sent.add("end")
    elif stage not in sent:
        call("sendMessage", {
            "chat_id": int(uid),
            "text": REMIND_TEXT[(kind, stage)],
            "reply_markup": {"inline_keyboard": [[{"text": "Продлить", "callback_data": "buy", "style": "success"}]]},
        })
        sent.add(stage)
        sent_now = True
    if stage == "1d":
        sent.add("3d")  # этап 3d уже неактуален, не отправляем его задним числом
    state["until"] = until
    state["sent"] = sorted(sent)
    user[state_key] = state
    return sent_now


def run_reminders():
    """Проходит по всем пользователям и отправляет нужные напоминания. Возвращает число отправленных."""
    sent = 0
    for uid, user in db.iter_users():
        if not uid:
            continue
        before = json.dumps(user, sort_keys=True)
        for kind in ("paid", "trial"):
            if _remind_user(uid, user, kind):
                sent += 1
        if json.dumps(user, sort_keys=True) != before:
            db.save_user(uid, user)
    return sent


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        # Cron раз в сутки: Vercel передаёт CRON_SECRET в Authorization
        if "remind=" in self.path:
            self._remind()
            return
        # Данные для мини приложения: статус подписки и пробного периода (без секретов)
        if "support=" in self.path:
            self._support_get()
            return
        if "servers=" in self.path:
            self._servers()
            return
        if "init=" in self.path:
            self._me()
            return
        self._reply(200, "bot is alive")

    def _remind(self):
        if CRON_SECRET and self.headers.get("Authorization") != f"Bearer {CRON_SECRET}":
            self._reply(401, "unauthorized")
            return
        try:
            self._reply(200, f"reminders sent: {run_reminders()}")
        except Exception as exc:
            print("remind error:", exc)
            self._reply(500, "error")

    def _json(self, code, data):
        body = json.dumps(data, ensure_ascii=False)
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))

    def do_OPTIONS(self):
        self._json(200, {"ok": True})

    def _support_get(self):
        """Чат поддержки: список обращений пользователя и выбранный чат. Админ: все обращения."""
        uid = request_user_id(self.path)
        if not uid:
            self._json(403, {"error": "forbidden"})
            return
        if is_admin({"id": uid}):
            self._json(200, support.admin_list())
            return
        query = parse_qs(urlparse(self.path).query)
        ticket_id = int(query.get("ticket_id", ["0"])[0] or 0)
        self._support_state(uid, ticket_id=ticket_id or None)

    def _support_post(self, length):
        """Действия в чате поддержки из мини приложения."""
        data = json.loads(self.rfile.read(length) or b"{}")
        uid = verify_init_data(data.get("init", ""))
        if not uid:
            self._json(403, {"error": "forbidden"})
            return
        action = data.get("action", "send")
        if is_admin({"id": uid}):
            if action in ("admin_open", "admin_reply", "admin_close"):
                code, body = support.admin_action(dict(data, action=action), SUPPORT_HOOKS_ADMIN)
                self._json(code, body)
            else:
                self._json(403, {"error": "Администратор не пишет в поддержку. Отвечайте на обращения ниже."})
            return
        code, body = support.user_action(uid, dict(data, name=data.get("name", "")), SUPPORT_HOOKS_USER)
        self._json(code, body)

    def _support_state(self, uid, ticket_id=None, new_chat=False):
        ticket = db.get_ticket(ticket_id) if ticket_id else None
        # Чужое обращение не показываем: берём только обращения этого пользователя
        if ticket and str(ticket.get("user_id")) != str(uid):
            ticket = None
        self._json(200, support.state_for_user(uid, ticket=ticket, new_chat=new_chat))

    def _servers(self):
        """Персональный список серверов для мини приложения. Без доступа — пусто."""
        uid = request_user_id(self.path)
        servers = []
        error_text = None
        if uid and has_access(db.get_user(uid) or {}):
            if "refresh=" in self.path:
                error_text = refresh_servers(uid)
            servers = user_servers(uid)
        left = refresh_left(uid) if uid else 0
        body = json.dumps({"servers": servers, "access": bool(servers), "error": error_text,
                           "refresh_left": left}, ensure_ascii=False)
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
        body = json.dumps({
            "paid_until": record.get("paid_until", 0),
            "trial_until": record.get("trial_until", 0),
            "now": int(time.time()),
        })
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        # Callback Platega: адрес https://telegramm-webapp.vercel.app/api/webhook?platega=1
        if "platega=" in self.path:
            code, msg = platega.handle_callback(
                self.headers, self.rfile.read(length),
                lambda uid, text: call("sendMessage", {"chat_id": uid, "text": text}),
            )
            self._reply(code, msg)
            return
        # Сообщения из чата мини приложения (проверяются по подписи initData, без секрета вебхука)
        if self.path.startswith("/api/webhook?support") or "support=" in self.path:
            try:
                self._support_post(length)
            except Exception as exc:
                print("support error:", exc)
                self._json(500, {"error": "Не удалось отправить сообщение."})
            return
        if WEBHOOK_SECRET and self.headers.get("X-Telegram-Bot-Api-Secret-Token") != WEBHOOK_SECRET:
            self._reply(403, "forbidden")
            return
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
