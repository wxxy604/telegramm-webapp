const tg = window.Telegram ? window.Telegram.WebApp : null;
if (tg) { tg.ready(); tg.expand(); }

const $ = (id) => document.getElementById(id);
const BOT = "https://t.me/SupplineVPNbot";

// Настройки сохраняются в браузере (localStorage)
const defaults = { notify: true, autorenew: false, theme: false };
const settings = Object.assign({}, defaults, JSON.parse(localStorage.getItem("settings") || "{}"));

function saveSettings() {
    localStorage.setItem("settings", JSON.stringify(settings));
}

function toast(text) {
    const el = $("toast");
    el.textContent = text;
    el.classList.add("show");
    setTimeout(() => el.classList.remove("show"), 1800);
}

function haptic() {
    if (tg && tg.HapticFeedback) tg.HapticFeedback.impactOccurred("light");
}

function showTab(tab) {
    document.querySelectorAll(".screen").forEach(s => s.classList.remove("active"));
    document.querySelectorAll("nav button").forEach(b => b.classList.remove("active"));
    const screen = $("screen-" + tab);
    if (screen) screen.classList.add("active");
    const navBtn = document.querySelector(`nav button[data-tab="${tab}"]`);
    if (navBtn) navBtn.classList.add("active");
    haptic();
}

function requireTelegram() {
    if (!tg || !tg.initData) {
        toast("Откройте приложение из Telegram");
        return false;
    }
    return true;
}

function renderSettings() {
    document.querySelectorAll("[data-toggle]").forEach(el => {
        el.classList.toggle("on", !!settings[el.dataset.toggle]);
    });
    document.body.dataset.theme = settings.theme ? "light" : "dark";
}

document.querySelectorAll("nav button").forEach(btn => {
    btn.addEventListener("click", () => showTab(btn.dataset.tab));
});

document.querySelectorAll("[data-go]").forEach(btn => {
    btn.addEventListener("click", () => showTab(btn.dataset.go));
});

document.querySelectorAll("[data-toggle]").forEach(el => {
    el.addEventListener("click", () => {
        const key = el.dataset.toggle;
        settings[key] = !settings[key];
        saveSettings();
        renderSettings();
        haptic();
    });
});

// Оплата: открываем бота по deep link, там создаётся счёт
document.querySelectorAll("[data-plan]").forEach(btn => {
    btn.addEventListener("click", () => {
        if (!requireTelegram()) return;
        tg.openTelegramLink(BOT + "?start=buy_" + btn.dataset.plan);
        tg.close();
    });
});

document.querySelectorAll("[data-crypto]").forEach(btn => {
    btn.addEventListener("click", () => {
        if (!requireTelegram()) return;
        tg.openTelegramLink(BOT + "?start=cbuy_" + btn.dataset.crypto);
        tg.close();
    });
});

const user = tg && tg.initDataUnsafe ? tg.initDataUnsafe.user : null;
if (user) {
    $("p-name").textContent = user.first_name;
    $("p-id").textContent = user.id;
    $("avatar").textContent = user.first_name.charAt(0).toUpperCase();
    $("home-greet").textContent = "Привет, " + user.first_name + "!";
}

renderSettings();
