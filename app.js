const tg = window.Telegram ? window.Telegram.WebApp : null;
if (tg) { tg.ready(); tg.expand(); }

// Демо-состояние. Позже сюда подключается API сервера.
const state = {
    keyActive: false,
    keyValue: "vless://demo-key-not-configured",
    devices: [
        { name: "iPhone", platform: "iOS", active: true },
        { name: "Windows PC", platform: "Windows", active: false }
    ],
    subscription: { active: false, plan: null, daysLeft: 0, totalDays: 30 },
    notify: true
};

const $ = (id) => document.getElementById(id);

function toast(text) {
    const el = $("toast");
    el.textContent = text;
    el.classList.add("show");
    setTimeout(() => el.classList.remove("show"), 1600);
}

function haptic() {
    if (tg && tg.HapticFeedback) tg.HapticFeedback.impactOccurred("light");
}

function renderKeys() {
    $("key-status").textContent = state.keyActive ? "Активен" : "Не активен";
    $("key-status").className = "badge " + (state.keyActive ? "on" : "off");
    $("key-toggle").textContent = state.keyActive ? "Выключить" : "Включить";
    $("key-value").textContent = state.keyValue;
}

function renderDevices() {
    const list = $("device-list");
    list.innerHTML = "";
    state.devices.forEach((d, i) => {
        const card = document.createElement("div");
        card.className = "card row";
        card.innerHTML = `
            <div>
                <div>${d.name}</div>
                <div class="muted">${d.platform}</div>
            </div>
            <div class="row" style="gap:10px">
                <span class="badge ${d.active ? "on" : "off"}">${d.active ? "Онлайн" : "Офлайн"}</span>
                <button class="btn small ghost" data-device="${i}">Удалить</button>
            </div>`;
        list.appendChild(card);
    });
    $("device-count").textContent = state.devices.length;
    if (state.devices.length === 0) {
        list.innerHTML = '<div class="empty">Устройств пока нет</div>';
    }
}

function renderSubscription() {
    const s = state.subscription;
    $("plan-name").textContent = s.active ? "Тариф: " + s.plan : "Тариф не выбран";
    $("plan-expire").textContent = s.active ? "Осталось дней: " + s.daysLeft : "Срок действия: нет";
    $("plan-badge").textContent = s.active ? "Активна" : "Нет подписки";
    $("plan-badge").className = "badge " + (s.active ? "on" : "warn");
    const percent = s.active ? Math.round((s.daysLeft / s.totalDays) * 100) : 0;
    $("plan-progress").style.width = percent + "%";
}

function renderProfile() {
    const user = tg && tg.initDataUnsafe ? tg.initDataUnsafe.user : null;
    if (user) {
        $("p-name").textContent = user.first_name;
        $("p-id").textContent = user.id;
        $("avatar").textContent = user.first_name.charAt(0).toUpperCase();
    }
    $("notify-switch").classList.toggle("on", state.notify);
}

function showTab(tab) {
    document.querySelectorAll(".screen").forEach(s => s.classList.remove("active"));
    document.querySelectorAll("nav button").forEach(b => b.classList.remove("active"));
    $("screen-" + tab).classList.add("active");
    document.querySelector(`nav button[data-tab="${tab}"]`).classList.add("active");
    haptic();
}

document.querySelectorAll("nav button").forEach(btn => {
    btn.addEventListener("click", () => showTab(btn.dataset.tab));
});

document.addEventListener("click", (e) => {
    const device = e.target.closest("[data-device]");
    if (device) {
        state.devices.splice(Number(device.dataset.device), 1);
        renderDevices();
        toast("Устройство удалено");
        return;
    }

    const el = e.target.closest("[data-action]");
    if (!el) return;
    const action = el.dataset.action;

    if (action === "copy-key") {
        navigator.clipboard.writeText(state.keyValue).then(
            () => toast("Ключ скопирован"),
            () => toast("Не удалось скопировать")
        );
    } else if (action === "toggle-key") {
        state.keyActive = !state.keyActive;
        renderKeys();
        toast(state.keyActive ? "Ключ включён" : "Ключ выключен");
    } else if (action === "rotate-key") {
        state.keyValue = "vless://rotated-" + Date.now().toString(36);
        renderKeys();
        toast("Ключ обновлён");
    } else if (action === "add-device") {
        if (state.devices.length >= 3) {
            toast("Достигнут лимит устройств");
        } else {
            state.devices.push({ name: "Новое устройство", platform: "Не определено", active: false });
            renderDevices();
            toast("Устройство добавлено");
        }
    } else if (action === "buy") {
        state.subscription = { active: true, plan: "1 месяц", daysLeft: 30, totalDays: 30 };
        renderSubscription();
        toast("Демо: подписка активирована");
    } else if (action === "toggle-notify") {
        state.notify = !state.notify;
        renderProfile();
    }
    haptic();
});

renderKeys();
renderDevices();
renderSubscription();
renderProfile();
