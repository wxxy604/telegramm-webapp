import json
import os
from urllib import request

REDIS_URL = os.getenv("UPSTASH_REDIS_REST_URL", "")
REDIS_TOKEN = os.getenv("UPSTASH_REDIS_REST_TOKEN", "")


def _cmd(*args):
    """Выполняет команду Redis через Upstash REST API и возвращает результат."""
    req = request.Request(
        REDIS_URL,
        data=json.dumps(list(args)).encode("utf-8"),
        headers={"Authorization": f"Bearer {REDIS_TOKEN}", "Content-Type": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=10) as resp:
        return json.load(resp).get("result")


def get_user(user_id):
    raw = _cmd("GET", f"user:{user_id}")
    return json.loads(raw) if raw else None


def save_user(user_id, data):
    _cmd("SET", f"user:{user_id}", json.dumps(data, ensure_ascii=False))


def add_trial_days(user_id, days):
    """Продлевает пробный период на days дней. Возвращает обновлённого пользователя."""
    import time

    user = get_user(user_id) or {"id": user_id, "trial_until": 0, "referrer": None, "invited": 0}
    now = int(time.time())
    base = max(user.get("trial_until", 0), now)
    user["trial_until"] = base + days * 86400
    save_user(user_id, user)
    return user


def extend_paid(user_id, days):
    """Продлевает платную подписку на days дней. Возвращает обновлённого пользователя."""
    import time

    user = get_user(user_id) or {"id": user_id, "trial_until": 0, "referrer": None, "invited": 0}
    now = int(time.time())
    base = max(user.get("paid_until", 0), now)
    user["paid_until"] = base + days * 86400
    save_user(user_id, user)
    return user


def mark_invoice(invoice_id):
    """Помечает счёт Crypto Pay как учтённый. Возвращает False, если он уже учтён."""
    return _cmd("SET", f"invoice:{invoice_id}", "1", "NX") == "OK"


def register_referral(new_user_id, referrer_id):
    """Регистрирует нового пользователя по реферальной ссылке.

    Возвращает True, если бонусы начислены. Защита: один раз на пользователя,
    пригласить себя нельзя.
    """
    if str(new_user_id) == str(referrer_id):
        return False
    existing = get_user(new_user_id)
    if existing and existing.get("referrer"):
        return False
    if existing is None:
        existing = {"id": new_user_id, "trial_until": 0, "referrer": None, "invited": 0}
    if not get_user(referrer_id):
        return False

    existing["referrer"] = str(referrer_id)
    save_user(new_user_id, existing)
    add_trial_days(new_user_id, 3)
    referrer = get_user(referrer_id)
    referrer["invited"] = referrer.get("invited", 0) + 1
    save_user(referrer_id, referrer)
    add_trial_days(referrer_id, 3)
    return True
