"""Переключение обращений для админа прямо в чате бота.

/tickets — список обращений кнопками. Нажатие на обращение открывает карточку:
историю переписки и кнопки «Ответить», «Закрыть», «К списку».
Ответ админа уходит пользователю в бот и в чат мини приложения (через hooks из webhook.py).
"""
import db

STATUS_ICON = {"open": "🟡", "answered": "🟢", "closed": "⚪"}


def list_markup(limit=10):
    """Клавиатура со списком последних обращений."""
    last = int(db._cmd("GET", "support:seq") or 0)
    rows = []
    for tid in range(last, max(0, last - limit), -1):
        t = db.get_ticket(tid)
        if not t:
            continue
        name = (t.get("name") or "без имени")[:18]
        rows.append([{
            "text": f"{STATUS_ICON.get(t.get('status', 'open'), '🟡')} #{t['id']} · {name}",
            "callback_data": f"tv:{t['id']}",
        }])
    if not rows:
        return None, "Обращений пока нет."
    return {"inline_keyboard": rows}, f"Обращения (последние {len(rows)}). Нажмите, чтобы открыть:"


def card_text(ticket):
    """Текст карточки обращения: статус, пользователь и последние сообщения."""
    msgs = db.ticket_messages(ticket)[-6:]
    lines = [
        f"Обращение #{ticket['id']} · {STATUS_ICON.get(ticket.get('status', 'open'), '')} {ticket.get('status', 'open')}",
        f"От: {ticket.get('name') or 'без имени'} (ID {ticket['user_id']})",
        "",
    ]
    for m in msgs:
        who = {"user": "👤", "admin": "🛠", "system": "•"}.get(m.get("from"), "•")
        lines.append(f"{who} {m.get('text', '')}")
    lines.append("")
    lines.append("Ответить: кнопка «✉️ Ответить» или /reply " + str(ticket["id"]) + " текст")
    return "\n".join(lines)


def card_markup(ticket):
    tid = ticket["id"]
    closed = ticket.get("status") == "closed"
    rows = []
    if not closed:
        rows.append([{"text": "✉️ Ответить", "callback_data": f"tr:{tid}"},
                     {"text": "✅ Закрыть", "callback_data": f"tc:{tid}"}])
    rows.append([{"text": "🔄 Обновить", "callback_data": f"tv:{tid}"},
                 {"text": "« К списку", "callback_data": "tl"}])
    return {"inline_keyboard": rows}
