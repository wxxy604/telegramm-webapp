"""Оплата через Platega: создание платежа СБП (paymentMethod 2) и приём callback.

Авторизация: X-MerchantId и X-Secret в заголовках (ключи из .env).
Callback: POST на /api/webhook?platega=1, статус CONFIRMED = оплата зачислена.
"""
import hmac
import json
import os
from urllib import error, request

import db

BASE_URL = "https://app.platega.io"
PAYMENT_METHOD_SBP = 2
PLANS = {  # ключ: (название, дни, цена в рублях)
    "1m": ("1 месяц", 30, 100),
    "3m": ("3 месяца", 90, 250),
    "12m": ("12 месяцев", 365, 900),
}
RETURN_URL = os.getenv("WEBAPP_URL", "https://telegramm-webapp.vercel.app/index.html")


def _creds():
    return os.getenv("PLATEGA_MERCHANT_ID", ""), os.getenv("PLATEGA_SECRET", "")


def _post(path, body):
    merchant, secret = _creds()
    req = request.Request(
        BASE_URL + path,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-MerchantId": merchant, "X-Secret": secret},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=20) as resp:
            return resp.status, json.load(resp)
    except error.HTTPError as exc:
        return exc.code, {"error": exc.read().decode("utf-8", "ignore")[:300]}
    except OSError as exc:
        return 0, {"error": str(exc)}


def create_payment(user_id, plan):
    """Создаёт платёж и возвращает (ok, текст для пользователя, ссылка на оплату)."""
    if plan not in PLANS:
        return False, "Неизвестный тариф.", None
    title, _days, rub = PLANS[plan]
    status, data = _post("/transaction/process", {
        "paymentMethod": PAYMENT_METHOD_SBP,
        "paymentDetails": {"amount": rub, "currency": "RUB"},
        "description": f"SupplineVPN: {title}",
        "payload": f"{user_id}:{plan}",
        "return": RETURN_URL,
        "failedUrl": RETURN_URL,
    })
    url = data.get("redirect") if status == 200 else None
    if not url:
        print("platega create error:", status, data)
        return False, "Не удалось создать платёж. Попробуйте позже.", None
    return True, f"Оплата тарифа «{title}» — {rub} ₽. После оплаты подписка включится автоматически.", url


def verify_headers(headers):
    merchant, secret = _creds()
    if not merchant or not secret:
        return False
    return (hmac.compare_digest(headers.get("X-MerchantId", "") or "", merchant)
            and hmac.compare_digest(headers.get("X-Secret", "") or "", secret))


def handle_callback(headers, raw_body, notify_user):
    """Обрабатывает callback. notify_user(user_id, text) отправляет сообщение в Telegram.
    Возвращает (код HTTP, текст)."""
    if not raw_body:
        return 200, "ok"  # проверочный пустой POST, который Platega шлёт при сохранении адреса
    if not verify_headers(headers):
        return 401, "unauthorized"
    try:
        data = json.loads(raw_body)
    except ValueError:
        return 400, "bad json"
    status = str(data.get("status", "")).upper()
    tid = str(data.get("id", ""))
    if status != "CONFIRMED" or not tid:
        return 200, "ignored"
    try:
        uid_s, plan = str(data.get("payload") or "").split(":", 1)
        uid = int(uid_s)
    except ValueError:
        return 200, "no payload"
    if plan not in PLANS:
        return 200, "unknown plan"
    _title, days, rub = PLANS[plan]
    try:
        paid = float(data.get("amount") or 0)
    except (TypeError, ValueError):
        paid = 0
    if paid < rub:
        return 200, "amount mismatch"
    if not db.mark_invoice(f"platega:{tid}"):  # повторный callback не выдаёт подписку дважды
        return 200, "duplicate"
    db.extend_paid(uid, days)
    notify_user(uid, f"✅ Оплата получена. Подписка на {days} дн. активирована.")
    return 200, "ok"
