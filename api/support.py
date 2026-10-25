"""Чат поддержки в мини приложении и в боте.

Пользователь: список своих обращений, переключение между ними, сообщения, закрытие.
Админ: список всех обращений, переключение, ответ и закрытие из мини приложения.
Функции возвращают (код HTTP, словарь ответа).
"""
import db


def _user_view(ticket):
    if not ticket:
        return None
    return {"id": ticket["id"], "status": ticket.get("status", "open")}


def state_for_user(uid, ticket=None, new_chat=False):
    """Состояние чата пользователя: список обращений и выбранный чат.
    Выбранный чат — это ticket (его передаёт клиент). Без него показываем последнее обращение.
    new_chat — пустой чат: сервер ничего не выбирает, пока не придёт первое сообщение."""
    if new_chat:
        current = None
    elif ticket is not None:
        current = ticket
    else:
        current = db.latest_user_ticket(uid)
    return {
        "admin": False,
        "tickets": db.user_tickets(uid),
        "ticket": _user_view(current),
        "messages": db.ticket_messages(current) if current else [],
    }


def admin_list():
    """Все обращения для админа (последние 50, новые первыми)."""
    last = int(db._cmd("GET", "support:seq") or 0)
    items = []
    for tid in range(last, max(0, last - 50), -1):
        t = db.get_ticket(tid)
        if not t:
            continue
        msgs = db.ticket_messages(t)
        last_msg = msgs[-1] if msgs else {}
        items.append({
            "id": t["id"], "status": t.get("status", "open"), "name": t.get("name", ""),
            "user_id": t.get("user_id"), "preview": (last_msg.get("text") or "")[:80],
            "last_ts": last_msg.get("ts", t.get("created", 0)),
        })
    return {"admin": True, "tickets": items, "ticket": None, "messages": []}


def admin_view(ticket):
    return {
        "admin": True, "tickets": [],
        "ticket": {"id": ticket["id"], "status": ticket.get("status", "open"),
                   "user_id": ticket.get("user_id"), "name": ticket.get("name", "")},
        "messages": db.ticket_messages(ticket),
    }


def user_action(uid, data, hooks):
    """Действие пользователя. hooks: notify_new(ticket), notify_message(ticket, text), notify_closed(ticket)."""
    action = data.get("action", "send")
    ticket_id = int(data.get("ticket_id") or 0)

    if action == "open":
        ticket = db.open_ticket_for_user(uid, ticket_id)
        db.pop_new_chat(uid)  # выбрали существующее обращение — выходим из режима «Новый чат»
        if not ticket:
            return 404, {"error": "Обращение не найдено."}
        return 200, state_for_user(uid, ticket=ticket)

    if action == "new":
        db.set_new_chat(uid)
        return 200, state_for_user(uid, new_chat=True)

    if action == "close":
        ticket = (db.get_ticket(ticket_id) if ticket_id else None) or db.latest_user_ticket(uid)
        if not ticket or str(ticket.get("user_id")) != str(uid) or ticket.get("status") == "closed":
            return 400, {"error": "Открытых обращений нет."}
        db.close_user_ticket(ticket)
        hooks["notify_closed"](ticket)
        return 200, state_for_user(uid, ticket=ticket)

    text = str(data.get("text", "")).strip()
    if not text or len(text) > 2000:
        return 400, {"error": "Сообщение пустое или длиннее 2000 символов."}
    if not db.support_allowed(uid):
        return 429, {"error": "Подождите пару секунд перед следующим сообщением."}

    fresh_chat = db.pop_new_chat(uid)
    ticket = db.get_ticket(ticket_id) if ticket_id else (None if fresh_chat else db.latest_user_ticket(uid))
    if ticket and str(ticket.get("user_id")) == str(uid) and ticket.get("status") != "closed":
        db.append_ticket_message(ticket, "user", text)
        db.link_user_ticket(uid, ticket["id"])
        hooks["notify_message"](ticket, text)
        return 200, state_for_user(uid, ticket=ticket)

    # Чат закрыт или обращения нет: создаём новое обращение
    new_id = db.create_ticket(uid, str(data.get("name", ""))[:64], text)
    new_ticket = db.get_ticket(new_id)
    hooks["notify_new"](new_ticket)
    return 200, state_for_user(uid, ticket=new_ticket)


def admin_action(data, hooks):
    """Действие админа. hooks: close(ticket), reply(ticket, text) -> bool."""
    action = data.get("action")
    ticket = db.get_ticket(int(data.get("ticket_id") or 0))
    if not ticket:
        return 404, {"error": "Обращение не найдено."}

    if action == "admin_open":
        return 200, admin_view(ticket)

    if action == "admin_close":
        if ticket.get("status") == "closed":
            return 400, {"error": "Обращение уже закрыто."}
        hooks["close"](ticket)
        return 200, admin_view(db.get_ticket(ticket["id"]))

    # admin_reply
    text = str(data.get("text", "")).strip()
    if not text or len(text) > 2000:
        return 400, {"error": "Ответ пустой или длиннее 2000 символов."}
    if not hooks["reply"](ticket, text):
        return 400, {"error": "Обращение закрыто, ответить нельзя."}
    return 200, admin_view(db.get_ticket(ticket["id"]))
