// Переключение обращений: список пользователя, «Новый чат» и панель админа.
// Подключается после app.js и использует его функции (supportState, renderChat, applySupport и т.д.).
(function () {
    const ICON = { open: "🟡", answered: "🟢", closed: "⚪" };
    let adminMode = false;
    let activeTicketId = null;

    function ticketLabel(t) {
        const d = new Date((t.last_ts || t.created || 0) * 1000);
        const when = d.toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit" });
        return { when, icon: ICON[t.status] || "🟡" };
    }

    function escapeHtml(s) {
        return String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
    }

    // Список обращений пользователя (плашки сверху)
    function renderUserTickets(tickets, currentId) {
        const box = $("support-tickets");
        box.innerHTML = "";
        if (!tickets || tickets.length === 0) {
            box.hidden = true;
            return;
        }
        box.hidden = false;
        tickets.forEach(t => {
            const b = document.createElement("button");
            b.type = "button";
            b.className = "sp-tab" + (t.id === currentId ? " active" : "");
            const lab = ticketLabel(t);
            b.innerHTML = `<span class="sp-tab-top">${lab.icon} #${t.id}</span><span class="sp-tab-sub"></span>`;
            b.querySelector(".sp-tab-sub").textContent = (t.preview || "").slice(0, 26) || lab.when;
            b.addEventListener("click", () => openUserTicket(t.id));
            box.appendChild(b);
        });
    }

    async function openUserTicket(id) {
        if (supportSending) return;
        try {
            await supportRequest({ action: "open", ticket_id: id });
            haptic();
        } catch (err) {
            toast(err.message);
        }
    }


    // ---- Админ ----
    function renderAdminList(items) {
        const list = $("admin-list");
        list.innerHTML = "";
        if (!items || items.length === 0) {
            const e = document.createElement("div");
            e.className = "chat-empty";
            e.textContent = "Обращений пока нет.";
            list.appendChild(e);
            return;
        }
        items.forEach(t => {
            const row = document.createElement("button");
            row.type = "button";
            row.className = "sp-admin-item" + (t.id === activeTicketId ? " active" : "");
            const lab = ticketLabel(t);
            row.innerHTML = `<span class="sp-admin-dot ${escapeHtml(t.status || "open")}"></span>` +
                `<span class="sp-admin-body"><span class="sp-admin-title">#${t.id} · ${escapeHtml(t.name || "без имени")}</span>` +
                `<span class="sp-admin-prev"></span></span><span class="sp-admin-when">${lab.when}</span>`;
            row.querySelector(".sp-admin-prev").textContent = t.preview || "—";
            row.addEventListener("click", () => adminOpen(t.id));
            list.appendChild(row);
        });
    }

    async function loadAdminList() {
        try {
            const r = await fetch(`${SUPPORT_API}?support=all&init=${encodeURIComponent(tg.initData)}`, { cache: "no-store" });
            if (!r.ok) throw new Error("bad status " + r.status);
            renderAdminList((await r.json()).tickets || []);
        } catch (e) {
            $("admin-list").textContent = "Нет связи с сервером";
        }
    }

    async function adminRequest(payload) {
        const r = await fetch(`${SUPPORT_API}?support=1`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(Object.assign({ init: tg.initData }, payload)),
        });
        const data = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(data.error || "Не удалось выполнить действие");
        return data;
    }

    function applyAdminTicket(data) {
        const t = data.ticket;
        if (!t) return;
        activeTicketId = t.id;
        supportState = { ticket: { id: t.id, status: t.status }, messages: data.messages || [], admin: true };
        const status = $("support-status");
        status.textContent = `Обращение #${t.id} · ${t.name || "без имени"} · ${STATUS_TEXT[t.status] || "Открыто"}`;
        status.className = "sp-status " + (t.status || "open");
        const closeBtn = $("support-close");
        closeBtn.hidden = t.status === "closed";
        closeBtn.onclick = () => adminClose(t.id);
        renderChat(supportState.messages, false);
        setAdminReplyMode(t.status !== "closed");
    }

    // Поле ввода для админа — это ответ пользователю
    function setAdminReplyMode(enabled) {
        const input = $("chat-text");
        input.disabled = !enabled;
        input.placeholder = enabled ? "Ответ пользователю..." : "Обращение закрыто";
        $("chat-send").disabled = !enabled;
        $("chat-form").dataset.mode = enabled ? "admin-reply" : "closed";
    }

    async function adminOpen(id) {
        try {
            applyAdminTicket(await adminRequest({ action: "admin_open", ticket_id: id }));
            loadAdminList();
        } catch (err) {
            toast(err.message);
        }
    }

    async function adminClose(id) {
        confirmBox("Закрыть обращение? Пользователь получит уведомление.", async () => {
            try {
                applyAdminTicket(await adminRequest({ action: "admin_close", ticket_id: id }));
                loadAdminList();
                haptic();
            } catch (err) {
                toast(err.message);
            }
        });
    }

    // Переключаем режим: админ видит свою панель, пользователь — свои обращения
    function applyModeFromState(state) {
        adminMode = !!state.admin;
        $("support-admin").hidden = !adminMode;
        $("support-new").hidden = adminMode;
        $("support-tabs").hidden = adminMode;
        if (!adminMode) renderUserTickets(state.tickets, state.ticket ? state.ticket.id : null);
    }

    // Перехватываем отрисовку из app.js: сначала переключаем режим, затем рисуем чат
    const baseApplySupport = applySupport;
    applySupport = function (data) {
        if (data.admin) {
            // Админ: обновляем только панель обращений, открытый чат не трогаем
            applyModeFromState(data);
            loadAdminList();
            return;
        }
        applyModeFromState(data);
        baseApplySupport(data);
        if (!adminMode) {
            activeTicketId = data.ticket ? data.ticket.id : null;
            $("chat-form").dataset.mode = "user";
            $("chat-text").disabled = false;
            $("chat-send").disabled = false;
            $("chat-text").placeholder = "Напишите сообщение...";
        }
        if (adminMode) loadAdminList();
    };

    // Отправка: для админа — ответ пользователю, для пользователя — штатная отправка из app.js
    $("chat-form").addEventListener("submit", async e => {
        const form = $("chat-form");
        if (form.dataset.mode !== "admin-reply") {
            if (form.dataset.mode === "closed") e.preventDefault();
            return;
        }
        e.preventDefault();
        e.stopImmediatePropagation();
        const input = $("chat-text");
        const text = input.value.trim();
        if (!text || !activeTicketId) return;
        $("chat-send").disabled = true;
        try {
            const data = await adminRequest({ action: "admin_reply", ticket_id: activeTicketId, text });
            applyAdminTicket(data);
            loadAdminList();
            input.value = "";
            input.style.height = "";
            haptic();
        } catch (err) {
            toast(err.message);
        } finally {
            $("chat-send").disabled = false;
        }
    }, true);

    $("support-new").addEventListener("click", startNewChat);
    $("admin-refresh").addEventListener("click", loadAdminList);
})();
