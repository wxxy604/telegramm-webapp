import hashlib
import json
import os
import time
from urllib import request

REDIS_URL = os.getenv("UPSTASH_REDIS_REST_URL", "")
REDIS_TOKEN = os.getenv("UPSTASH_REDIS_REST_TOKEN", "")


def _cmd(*args, retries=6):
    """Выполняет команду Redis через Upstash REST API и возвращает результат.
    При сетевом таймауте повторяет запрос до retries раз с нарастающей паузой (до ~30 с)."""
    last_exc = None
    for attempt in range(retries):
        req = request.Request(
            REDIS_URL,
            data=json.dumps(list(args)).encode("utf-8"),
            headers={"Authorization": f"Bearer {REDIS_TOKEN}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=45) as resp:
                return json.load(resp).get("result")
        except (TimeoutError, OSError) as exc:
            last_exc = exc
            time.sleep(min(2 ** attempt, 30))
    raise last_exc


def _pipeline(commands):
    """Выполняет несколько команд Redis одним запросом (Upstash /pipeline)."""
    req = request.Request(
        REDIS_URL.rstrip("/") + "/pipeline",
        data=json.dumps(commands).encode("utf-8"),
        headers={"Authorization": f"Bearer {REDIS_TOKEN}", "Content-Type": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


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
    user["keys_issued_at"] = now  # новый срок действия ключей (KEY_TTL в webhook.py)
    save_user(user_id, user)
    return user


def extend_paid(user_id, days):
    """Продлевает платную подписку на days дней. Возвращает обновлённого пользователя."""
    import time

    user = get_user(user_id) or {"id": user_id, "trial_until": 0, "referrer": None, "invited": 0}
    now = int(time.time())
    base = max(user.get("paid_until", 0), now)
    user["paid_until"] = base + days * 86400
    user["keys_issued_at"] = now  # оплата даёт новый срок действия ключей (KEY_TTL в webhook.py)
    save_user(user_id, user)
    return user


def is_banned(user_id):
    """Заблокирован ли пользователь администратором."""
    user = get_user(user_id) or {}
    return bool(user.get("banned"))


def set_banned(user_id, banned):
    """Блокирует или разблокирует пользователя."""
    user = get_user(user_id) or {"id": user_id, "trial_until": 0, "referrer": None, "invited": 0}
    user["banned"] = bool(banned)
    save_user(user_id, user)
    return user


def revoke_paid(user_id):
    """Снимает платную подписку пользователя."""
    user = get_user(user_id) or {"id": user_id, "trial_until": 0, "referrer": None, "invited": 0}
    user["paid_until"] = 0
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


def _config_id(uri):
    return hashlib.sha1(uri.encode("utf-8")).hexdigest()[:16]


def add_configs(uris):
    """Добавляет VPN-конфиги в свободный пул. Дубликаты пропускаются. Возвращает число новых.
    Записи идут пачками одним запросом, чтобы не перегружать Upstash."""
    items = []
    for uri in uris:
        uri = uri.strip()
        if uri:
            items.append((_config_id(uri), uri))
    added = 0
    chunk = 50
    for start in range(0, len(items), chunk):
        batch = items[start:start + chunk]
        commands = [["SET", f"config:{cid}", json.dumps({"uri": uri}, ensure_ascii=False), "NX"]
                    for cid, uri in batch]
        results = _pipeline(commands)
        new_ids = []
        for (cid, _), res in zip(batch, results):
            if res.get("result") == "OK":
                new_ids.append(cid)
        if new_ids:
            _pipeline([["SADD", "pool:free", cid] for cid in new_ids])
            added += len(new_ids)
    return added


def get_key(user_id):
    """Возвращает ссылку конфига пользователя. Если ключа ещё нет, берёт свободный из пула.
    Возвращает None, если свободных конфигов нет."""
    user = get_user(user_id) or {"id": user_id, "trial_until": 0, "referrer": None, "invited": 0}
    cid = user.get("config_id")
    if cid:
        raw = _cmd("GET", f"config:{cid}")
        if raw:
            return json.loads(raw)["uri"]
    cid = _cmd("SPOP", "pool:free")
    if not cid:
        return None
    raw = _cmd("GET", f"config:{cid}")
    if not raw:
        return None
    user["config_id"] = cid
    save_user(user_id, user)
    return json.loads(raw)["uri"]


def save_best_servers(servers):
    """Сохраняет список лучших серверов (уже отсортирован по пингу): [{"name", "uri", "ping"}]."""
    _cmd("SET", "servers:best", json.dumps(servers, ensure_ascii=False))


def save_servers_pool(servers):
    """Сохраняет полный пул серверов (активные и ожидающие удаления, dropped_at).
    servers:best — только активные лучшие 10 по пингу, их видят новые пользователи."""
    _cmd("SET", "servers:pool", json.dumps(servers, ensure_ascii=False))
    active = [s for s in servers if not s.get("dropped_at")]
    _cmd("SET", "servers:best", json.dumps(active[:100], ensure_ascii=False))


def get_sources_auto():
    """Источники, найденные парсером автоматически (хранятся в Redis)."""
    raw = _cmd("GET", "sources:auto")
    return json.loads(raw) if raw else []


def save_sources_auto(urls):
    _cmd("SET", "sources:auto", json.dumps(urls, ensure_ascii=False))


SUPPORT_WAIT_SECONDS = 600  # сколько ждём сообщение пользователя после нажатия «Написать в поддержку»


def set_support_wait(user_id):
    """Помечает, что следующее сообщение пользователя — обращение в поддержку."""
    _cmd("SET", f"support:wait:{user_id}", "1", "EX", str(SUPPORT_WAIT_SECONDS))


def pop_support_wait(user_id):
    """Возвращает True, если пользователь ждал ввода обращения, и сбрасывает ожидание."""
    return _cmd("DEL", f"support:wait:{user_id}") == 1


def set_admin_reply_wait(admin_id, ticket_id):
    """Админ нажал «Ответить»: следующее его сообщение — ответ на обращение ticket_id."""
    _cmd("SET", f"support:adminwait:{admin_id}", str(ticket_id), "EX", str(SUPPORT_WAIT_SECONDS))


def clear_admin_reply_wait(admin_id):
    _cmd("DEL", f"support:adminwait:{admin_id}")


def pop_admin_reply_wait(admin_id):
    """Возвращает номер обращения, на которое админ сейчас отвечает (или None), и сбрасывает ожидание."""
    raw = _cmd("GET", f"support:adminwait:{admin_id}")
    if raw:
        _cmd("DEL", f"support:adminwait:{admin_id}")
    return raw


def create_ticket(user_id, name, text):
    """Создаёт обращение в поддержку и возвращает его номер."""
    ticket_id = _cmd("INCR", "support:seq")
    now = int(time.time())
    ticket = {"id": ticket_id, "user_id": str(user_id), "name": name, "text": text,
              "created": now, "status": "open", "reply": None,
              "messages": [{"from": "user", "text": text, "ts": now}]}
    _cmd("SET", f"support:ticket:{ticket_id}", json.dumps(ticket, ensure_ascii=False))
    link_user_ticket(user_id, ticket_id)
    return ticket_id


def latest_user_ticket(user_id):
    """Последнее обращение пользователя (открытое или закрытое) или None."""
    tid = _cmd("GET", f"support:last:{user_id}")
    return get_ticket(int(tid)) if tid else None


def user_ticket_ids(user_id):
    """Все номера обращений пользователя, новые первыми."""
    raw = _cmd("LRANGE", f"support:list:{user_id}", "0", "99")
    return [int(x) for x in (raw or [])]


def user_tickets(user_id):
    """Список обращений пользователя с полями для переключения (без полной истории)."""
    out = []
    for tid in user_ticket_ids(user_id):
        t = get_ticket(tid)
        if t:
            msgs = ticket_messages(t)
            last = msgs[-1] if msgs else {}
            admin_ts = [m.get("ts", 0) for m in msgs if m.get("from") == "admin"]
            out.append({"id": t["id"], "status": t.get("status", "open"), "created": t.get("created", 0),
                        "preview": (last.get("text") or "")[:80], "last_ts": last.get("ts", t.get("created", 0)),
                        "last_admin_ts": max(admin_ts) if admin_ts else 0})
    return out


def link_user_ticket(user_id, ticket_id):
    """Добавляет номер обращения в список пользователя и делает его последним."""
    _cmd("LPUSH", f"support:list:{user_id}", str(ticket_id))
    _cmd("LTRIM", f"support:list:{user_id}", "0", "99")
    _cmd("SET", f"support:last:{user_id}", str(ticket_id))


def ticket_messages(ticket):
    """История переписки. Старые обращения без поля messages восстанавливаются из text и reply."""
    msgs = list(ticket.get("messages") or [])
    if not msgs:
        msgs.append({"from": "user", "text": ticket.get("text", ""), "ts": ticket.get("created", 0)})
        if ticket.get("reply"):
            msgs.append({"from": "admin", "text": ticket["reply"], "ts": ticket.get("created", 0)})
    return msgs


def append_ticket_message(ticket, sender, text):
    """Дописывает сообщение в историю и сохраняет обращение. Сообщение пользователя переоткрывает обращение."""
    msgs = ticket_messages(ticket)
    msgs.append({"from": sender, "text": text, "ts": int(time.time())})
    ticket["messages"] = msgs
    if sender == "user":
        ticket["status"] = "open"  # пользователь написал снова: обращение снова открыто
    save_ticket(ticket)


def close_user_ticket(ticket):
    """Пользователь закрыл своё обращение в мини приложении."""
    ticket["status"] = "closed"
    append_ticket_message(ticket, "system", "Обращение закрыто пользователем.")


def set_new_chat(user_id):
    """Пользователь нажал «Новый чат»: следующее сообщение без выбранного обращения создаст новое."""
    _cmd("SET", f"support:newchat:{user_id}", "1", "EX", "1800")


def pop_new_chat(user_id):
    """Возвращает True, если пользователь выбрал «Новый чат», и сбрасывает пометку."""
    return _cmd("DEL", f"support:newchat:{user_id}") == 1


def has_new_chat(user_id):
    """Проверяет пометку «Новый чат» без сброса: опрос состояния не должен её съедать."""
    return _cmd("GET", f"support:newchat:{user_id}") == "1"


def support_allowed(user_id):
    """Не чаще одного сообщения в 3 секунды с одного пользователя (защита от спама)."""
    return _cmd("SET", f"support:rate:{user_id}", "1", "NX", "EX", "3") == "OK"


def get_ticket(ticket_id):
    raw = _cmd("GET", f"support:ticket:{ticket_id}")
    return json.loads(raw) if raw else None


def open_ticket_for_user(user_id, ticket_id):
    """Переключает чат пользователя на обращение ticket_id. Возвращает обращение или None,
    если оно не принадлежит этому пользователю (нельзя открыть чужое)."""
    ticket = get_ticket(ticket_id)
    if not ticket or str(ticket.get("user_id")) != str(user_id):
        return None
    link_user_ticket(user_id, ticket_id)
    return ticket


def save_ticket(ticket):
    _cmd("SET", f"support:ticket:{ticket['id']}", json.dumps(ticket, ensure_ascii=False))


def list_tickets(limit=10):
    """Последние обращения, новые первыми."""
    last = _cmd("GET", "support:seq")
    last = int(last) if last else 0
    tickets = []
    for tid in range(last, max(0, last - limit), -1):
        t = get_ticket(tid)
        if t:
            tickets.append(t)
    return tickets


def iter_users():
    """Перебирает всех пользователей (user:<id>) через SCAN. Отдаёт пары (id, данные)."""
    cursor = "0"
    while True:
        res = _cmd("SCAN", cursor, "MATCH", "user:*", "COUNT", "500")
        cursor, keys = res[0], res[1]
        for key in keys:
            raw = _cmd("GET", key)
            if raw:
                data = json.loads(raw)
                yield data.get("id"), data
        if cursor == "0":
            break


def get_servers_pool():
    raw = _cmd("GET", "servers:pool")
    return json.loads(raw) if raw else []


def assign_servers(user_id, count_min=3, count_max=5):
    """Выдаёт пользователю серверы по пингу: от count_min до count_max штук.
    Сервер, выданный одному пользователю, помечается в servers:taken и другим не выдаётся.
    Уже выданные сервера сохраняются за пользователем и при пересборке пула не меняются.
    Возвращает список серверов пользователя (словари из пула)."""
    user = get_user(user_id) or {"id": user_id, "trial_until": 0, "referrer": None, "invited": 0}
    current = list(user.get("server_ids", []))
    pool = get_servers_pool()
    by_id = {_sid(s): s for s in pool}
    # Сервера, которые больше не в пуле (сломались), отбрасываем и освобождаем
    for sid in list(current):
        if sid not in by_id:
            current.remove(sid)
            _cmd("SREM", "servers:taken", sid)
    if len(current) < count_max:
        need = count_max - len(current)
        for s in pool:  # пул уже отсортирован по пингу
            if need <= 0:
                break
            if s.get("dropped_at"):  # новым пользователям — только актуальные сервера
                continue
            sid = _sid(s)
            if sid in current:
                continue
            if _cmd("SADD", "servers:taken", sid) == 1:
                current.append(sid)
                need -= 1
    user["server_ids"] = current
    save_user(user_id, user)
    return [by_id[sid] for sid in current]


def assign_random_pack(user_id, size=3):
    """Персональный пакет: size случайных серверов из полного пула (каждая запись — отдельный сервер).
    Пакет закрепляется за пользователем в user:<id>.server_ids и не меняется при повторных
    открытиях мини приложения. Сервера, уже занятые другими, берутся в последнюю очередь.
    Возвращает список записей серверов из пула."""
    import random

    user = get_user(user_id) or {"id": user_id, "trial_until": 0, "referrer": None, "invited": 0}
    pool = get_servers_pool()
    by_id = {_sid(s): s for s in pool}

    current = [sid for sid in user.get("server_ids", []) if sid in by_id]
    if len(current) == size:
        return [by_id[sid] for sid in current]

    # Освобождаем сервера, которых больше нет в пуле
    for sid in user.get("server_ids", []):
        if sid not in by_id:
            _cmd("SREM", "servers:taken", sid)

    candidates = [s for s in pool if not s.get("dropped_at") and _sid(s) not in current]
    random.shuffle(candidates)

    # Сначала свободные (не занятые другими пользователями), затем занятые — чтобы пакет был полным
    free, busy = [], []
    for s in candidates:
        if _cmd("SISMEMBER", "servers:taken", _sid(s)) == 1:
            busy.append(s)
        else:
            free.append(s)

    for s in free + busy:
        if len(current) >= size:
            break
        sid = _sid(s)
        if sid not in current:
            _cmd("SADD", "servers:taken", sid)
            current.append(sid)

    user["server_ids"] = current
    save_user(user_id, user)
    return [by_id[sid] for sid in current]


def release_servers(user_id):
    """Освобождает серверы пользователя (когда у него закончился доступ), чтобы их могли выдать другим."""
    user = get_user(user_id)
    if not user or not user.get("server_ids"):
        return
    for sid in user.pop("server_ids"):
        _cmd("SREM", "servers:taken", sid)
    save_user(user_id, user)


def _sid(server):
    """Уникальный идентификатор сервера: хэш ссылки."""
    return _config_id(server["uri"])


def get_best_servers():
    """Возвращает список лучших серверов или пустой список, если парсер ещё не запускался."""
    raw = _cmd("GET", "servers:best")
    return json.loads(raw) if raw else []


def release_key(user_id):
    """Возвращает конфиг пользователя в пул, когда доступ закончился."""
    user = get_user(user_id)
    if not user or not user.get("config_id"):
        return
    cid = user.pop("config_id")
    _cmd("SADD", "pool:free", cid)
    save_user(user_id, user)
