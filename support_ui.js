// Поддержка в мини приложении: чат, выпадающий список обращений, «Новый чат», панель админа.
// Подключается после app.js. Использует его функции: $, toast, haptic, renderChat, confirmBox,
// SUPPORT_API, STATUS_TEXT, tg, user, supportSending.
(function () {
    // Константы и общие функции поддержки (раньше были в app.js, перенесены сюда)
    const SUPPORT_API = "https://telegramm-webapp.vercel.app/api/webhook";
    const STATUS_TEXT = { open: "Открыто", answered: "Есть ответ", closed: "Закрыто" };
    let supportSending = false;
    const MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"];

    function fmtTime(ts) {
        if (!ts) return "";
        return new Date(ts * 1000).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
    }

    function dayLabel(ts) {
        const d = new Date(ts * 1000);
        const now = new Date();
        const y = new Date(now);
        y.setDate(now.getDate() - 1);
        if (d.toDateString() === now.toDateString()) return "Сегодня";
        if (d.toDateString() === y.toDateString()) return "Вчера";
        return d.getDate() + " " + MONTHS[d.getMonth()];
    }

    // Отрисовка переписки: пузыри, разделители дат, системные строки
    function renderChat(messages, keepScroll) {
        const list = $("chat-list");
        const nearBottom = list.scrollHeight - list.scrollTop - list.clientHeight < 80;
        list.innerHTML = "";
        if (!messages || messages.length === 0) {
            const el = document.createElement("div");
            el.className = "chat-empty";
            el.innerHTML = '<div class="chat-empty-icon">💬</div>Опишите вопрос ниже.<br>Ответ придёт сюда и в бота.';
            list.appendChild(el);
            return;
        }
        let lastDay = "";
        messages.forEach(m => {
            const day = m.ts ? dayLabel(m.ts) : "";
            if (day && day !== lastDay) {
                const sep = document.createElement("div");
                sep.className = "chat-date";
                sep.textContent = day;
                list.appendChild(sep);
                lastDay = day;
            }
            if (m.from === "system") {
                const s = document.createElement("div");
                s.className = "bubble system";
                s.textContent = m.text;
                list.appendChild(s);
                return;
            }
            const row = document.createElement("div");
            row.className = "msg-row " + (m.from === "user" ? "mine" : "theirs");
            const b = document.createElement("div");
            b.className = "bubble " + (m.from === "user" ? "user" : "admin");
            b.textContent = m.text;
            const t = document.createElement("span");
            t.className = "bubble-time";
            t.textContent = fmtTime(m.ts);
            b.appendChild(t);
            row.appendChild(b);
            list.appendChild(row);
        });
        if (!keepScroll || nearBottom) list.scrollTop = list.scrollHeight;
    }

    // Подтверждение действия (нативное окно Telegram, если доступно)
    function confirmBox(text, onYes) {
        if (tg && typeof tg.showConfirm === "function") {
            tg.showConfirm(text, ok => { if (ok) onYes(); });
        } else if (window.confirm(text)) {
            onYes();
        }
    }

    const ICON = { open: "🟡", answered: "🟢", closed: "⚪" };
    const STATE = {
        admin: false,
        activeId: null,      // обращение, открытое в чате (выбор клиента)
        newChat: false,      // режим «Новый чат»: следующее сообщение создаст обращение
        tickets: [],         // список обращений пользователя (для выпадающего списка)
        adminItems: [],      // список обращений админа
    };

    function esc(s) {
        return String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
    }

    function dateLabel(ts) {
        return new Date((ts || 0) * 1000).toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit" });
    }

    function initDataParam() {
        return encodeURIComponent(tg && tg.initData ? tg.initData : "");
    }

    // ---- Выпадающий список чатов (пользователь) ----
    function renderDropdown() {
        const menu = $("support-menu");
        const cur = STATE.tickets.find(t => t.id === STATE.activeId);
        const title = STATE.newChat ? "✏️ Новый чат" : cur ? `${ICON[cur.status] || "🟡"} Обращение #${cur.id}` : "Выберите чат";
        $("support-current").textContent = title + " ▾";
        menu.innerHTML = "";
        STATE.tickets.forEach(t => {
            const b = document.createElement("button");
            b.type = "button";
            b.className = "sp-drop-item" + (t.id === STATE.activeId && !STATE.newChat ? " active" : "");
            b.innerHTML = `<span class="sp-drop-top">${ICON[t.status] || "🟡"} #${t.id} · ${dateLabel(t.last_ts || t.created)}</span>` +
                `<span class="sp-drop-sub"></span>`;
            b.querySelector(".sp-drop-sub").textContent = (t.preview || "").slice(0, 40) || "—";
            b.addEventListener("click", () => selectUserTicket(t.id));
            menu.appendChild(b);
        });
        const nb = document.createElement("button");
        nb.type = "button";
        nb.className = "sp-drop-item sp-drop-new";
        nb.textContent = "+ Новый чат";
        nb.addEventListener("click", startNewChat);
        menu.appendChild(nb);
    }

    function toggleDropdown(force) {
        const menu = $("support-menu");
        const open = typeof force === "boolean" ? force : menu.hidden;
        menu.hidden = !open;
        $("support-current").setAttribute("aria-expanded", String(open));
    }

    // Выбор чата: сразу переключаем, данные подтягиваем с сервера
    function selectUserTicket(id) {
        toggleDropdown(false);
        STATE.activeId = id;
        STATE.newChat = false;
        haptic();
        loadUserState(true);
    }

    function startNewChat() {
        toggleDropdown(false);
        STATE.newChat = true;
        STATE.activeId = null;
        renderChat([], false);
        $("support-status").textContent = "Новый чат · опишите вопрос";
        $("support-status").className = "sp-status";
        $("support-close").hidden = true;
        setInputEnabled(true, "Опишите вопрос...");
        $("chat-text").focus();
        haptic();
        renderDropdown();
    }

    // ---- Опрос состояния пользователя ----
    async function loadUserState(immediate) {
        if (!tg || !tg.initData || !user) return;
        if (supportSending) return;
        const q = STATE.activeId && !STATE.newChat ? `&ticket_id=${STATE.activeId}` : "";
        try {
            const r = await fetch(`${SUPPORT_API}?support=1&init=${initDataParam()}${q}`, { cache: "no-store" });
            if (!r.ok) throw new Error("bad status " + r.status);
            const data = await r.json();
            if (data.admin) {
                enterAdminMode();
                return;
            }
            leaveAdminMode();
            STATE.tickets = data.tickets || [];
            if (!STATE.newChat) {
                STATE.activeId = data.ticket ? data.ticket.id : null;
                renderUserChat(data);
            }
            renderDropdown();
        } catch (e) {
            if (immediate) $("support-status").textContent = "Нет связи с сервером";
        }
    }


    function renderUserChat(data) {
        const t = data.ticket;
        $("support-status").textContent = t ? `Обращение #${t.id} · ${STATUS_TEXT[t.status] || "Открыто"}` : "Напишите, с чем нужна помощь";
        $("support-status").className = "sp-status " + (t ? (t.status || "open") : "");
        $("support-close").hidden = !t || t.status === "closed";
        $("support-close").onclick = closeUserTicket;
        renderChat(data.messages || [], true);
        setInputEnabled(true, "Напишите сообщение...");
    }

    function setInputEnabled(enabled, placeholder) {
        $("chat-text").disabled = !enabled;
        $("chat-send").disabled = !enabled;
        $("chat-text").placeholder = placeholder;
        $("chat-form").dataset.mode = enabled ? (STATE.admin ? "admin-reply" : "user") : "closed";
    }

    async function postSupport(payload) {
        const r = await fetch(`${SUPPORT_API}?support=1`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(Object.assign({ init: tg.initData }, payload)),
        });
        const data = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(data.error || "Не удалось выполнить действие");
        return data;
    }

    // Пользователь пишет: в открытое обращение или новое (если «Новый чат»)
    async function userSend(text) {
        const payload = { action: "send", text, name: user ? user.first_name : "" };
        if (!STATE.newChat && STATE.activeId) payload.ticket_id = STATE.activeId;
        const data = await postSupport(payload);
        STATE.newChat = false;
        STATE.tickets = data.tickets || STATE.tickets;
        STATE.activeId = data.ticket ? data.ticket.id : STATE.activeId;
        renderUserChat(data);
        renderDropdown();
    }

    async function closeUserTicket() {
        confirmBox("Закрыть обращение? Новое сообщение откроет его снова.", async () => {
            try {
                const data = await postSupport({ action: "close", ticket_id: STATE.activeId });
                STATE.tickets = data.tickets || STATE.tickets;
                renderUserChat(data);
                renderDropdown();
                toast("Обращение закрыто");
            } catch (err) {
                toast(err.message);
            }
        });
    }

    // ---- Админ ----
    // Режим админа: панель обращений с выпадающим списком, без «Новый чат» (админ не создаёт обращения)
    function enterAdminMode() {
        STATE.admin = true;
        $("support-admin").hidden = false;
        $("support-tabs").hidden = true;
        $("support-new").hidden = true;
        $("support-admin-toggle").hidden = false;
        loadAdminList();
    }

    function toggleAdminList(force) {
        const body = $("admin-list");
        const open = typeof force === "boolean" ? force : body.hidden;
        body.hidden = !open;
        $("support-admin-toggle").setAttribute("aria-expanded", String(open));
        $("support-admin-toggle").textContent = (open ? "Скрыть обращения ▴" : "Показать обращения ▾") +
            (STATE.adminItems.length ? ` (${STATE.adminItems.length})` : "");
    }

    function leaveAdminMode() {
        if (!STATE.admin) return;
        STATE.admin = false;
        $("support-admin").hidden = true;
        $("support-tabs").hidden = false;
        $("support-new").hidden = false;
    }

    async function loadAdminList() {
        try {
            const r = await fetch(`${SUPPORT_API}?support=all&init=${initDataParam()}`, { cache: "no-store" });
            if (!r.ok) throw new Error("bad status " + r.status);
            STATE.adminItems = (await r.json()).tickets || [];
            renderAdminList();
            toggleAdminList(!$("admin-list").hidden);
        } catch (e) {
            $("admin-list").textContent = "Нет связи с сервером";
        }
    }

    function renderAdminList() {
        const list = $("admin-list");
        list.innerHTML = "";
        if (STATE.adminItems.length === 0) {
            const e = document.createElement("div");
            e.className = "chat-empty";
            e.textContent = "Обращений пока нет.";
            list.appendChild(e);
            return;
        }
        STATE.adminItems.forEach(t => {
            const row = document.createElement("button");
            row.type = "button";
            row.className = "sp-admin-item" + (t.id === STATE.activeId ? " active" : "");
            row.innerHTML = `<span class="sp-admin-dot ${esc(t.status || "open")}"></span>` +
                `<span class="sp-admin-body"><span class="sp-admin-title">#${t.id} · ${esc(t.name || "без имени")}</span>` +
                `<span class="sp-admin-prev"></span></span><span class="sp-admin-when">${dateLabel(t.last_ts)}</span>`;
            row.querySelector(".sp-admin-prev").textContent = t.preview || "—";
            row.addEventListener("click", () => adminOpen(t.id));
            list.appendChild(row);
        });
    }

    function applyAdminTicket(data) {
        const t = data.ticket;
        if (!t) return;
        STATE.activeId = t.id;
        $("support-status").textContent = `Обращение #${t.id} · ${t.name || "без имени"} · ${STATUS_TEXT[t.status] || "Открыто"}`;
        $("support-status").className = "sp-status " + (t.status || "open");
        $("support-close").hidden = t.status === "closed";
        $("support-close").onclick = () => adminClose(t.id);
        renderChat(data.messages || [], false);
        setInputEnabled(t.status !== "closed", t.status === "closed" ? "Обращение закрыто" : "Ответ пользователю...");
        renderAdminList();
    }

    async function adminOpen(id) {
        try {
            applyAdminTicket(await postSupport({ action: "admin_open", ticket_id: id }));
        } catch (err) {
            toast(err.message);
        }
    }

    async function adminClose(id) {
        confirmBox("Закрыть обращение? Пользователь получит уведомление.", async () => {
            try {
                applyAdminTicket(await postSupport({ action: "admin_close", ticket_id: id }));
                loadAdminList();
                haptic();
            } catch (err) {
                toast(err.message);
            }
        });
    }

    // ---- Отправка формы: админ отвечает, пользователь пишет ----
    $("chat-form").addEventListener("submit", async e => {
        e.preventDefault();
        e.stopImmediatePropagation();
        const mode = $("chat-form").dataset.mode;
        if (mode === "closed") return;
        const input = $("chat-text");
        const text = input.value.trim();
        if (!text || supportSending) return;
        supportSending = true;
        $("chat-send").disabled = true;
        try {
            if (STATE.admin) {
                if (!STATE.activeId) return;
                applyAdminTicket(await postSupport({ action: "admin_reply", ticket_id: STATE.activeId, text }));
                loadAdminList();
            } else {
                await userSend(text);
            }
            input.value = "";
            input.style.height = "";
            haptic();
        } catch (err) {
            toast(err.message);
        } finally {
            supportSending = false;
            $("chat-send").disabled = $("chat-text").disabled;
        }
    }, true);

    // ---- Элементы управления и опрос ----
    $("support-current").addEventListener("click", () => toggleDropdown());
    $("support-new").addEventListener("click", startNewChat);
    $("admin-refresh").addEventListener("click", loadAdminList);
    $("support-admin-toggle").addEventListener("click", () => toggleAdminList());

    // Опрос: админ обновляет список, пользователь — свой открытый чат
    setInterval(() => {
        if (STATE.admin) {
            loadAdminList();
            if (STATE.activeId) refreshAdminChat();
        } else {
            loadUserState(false);
        }
    }, 6000);

    // Админ: обновляем открытый чат, чтобы новые сообщения пользователя появлялись сами
    async function refreshAdminChat() {
        if (supportSending || !STATE.activeId) return;
        try {
            const data = await postSupport({ action: "admin_open", ticket_id: STATE.activeId });
            applyAdminTicket(data);
        } catch (e) {
            /* тихо: следующий опрос повторит */
        }
    }

    const prevShowTab = showTab;
    showTab = function (tab) {
        prevShowTab(tab);
        if (tab === "support") loadUserState(true);
    };
})();
