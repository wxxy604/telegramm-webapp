const tg = window.Telegram ? window.Telegram.WebApp : null;
if (tg) {
    tg.ready();
    tg.expand();
    if (typeof tg.disableVerticalSwipes === "function") tg.disableVerticalSwipes();
}

const $ = (id) => document.getElementById(id);
const BOT = "https://t.me/SupplineVPNbot";

// Настройки сохраняются в браузере
const defaults = { notify: true, theme: false };
const settings = Object.assign({}, defaults, JSON.parse(localStorage.getItem("settings") || "{}"));
// Способ оплаты, выбранный в выпадающем списке
let payMethod = localStorage.getItem("payMethod") || "crypto";

// Цены по способу оплаты
const PRICES = {
    crypto: { "1m": "2 USDT", "3m": "5 USDT", "12m": "18 USDT" },
    stars:  { "1m": "150 ⭐", "3m": "400 ⭐", "12m": "1 400 ⭐" },
    sbp:    { "1m": "199 ₽", "3m": "499 ₽", "12m": "1 490 ₽" },
};
const METHOD_NAMES = { crypto: "Криптобот (USDT)", stars: "Звёзды Telegram", sbp: "СБП" };

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
    document.querySelectorAll(".tabbar button").forEach(b => b.classList.remove("active"));
    const screen = $("screen-" + tab);
    if (screen) screen.classList.add("active");
    const navBtn = document.querySelector(`.tabbar button[data-tab="${tab}"]`);
    if (navBtn) navBtn.classList.add("active");
    haptic();
}

function renderSettings() {
    document.querySelectorAll("[data-switch]").forEach(el => {
        el.classList.toggle("on", !!settings[el.dataset.switch]);
    });
    document.body.dataset.theme = settings.theme ? "light" : "dark";
}

function renderPayment() {
    $("method-label").textContent = METHOD_NAMES[payMethod];
    document.querySelectorAll(".select-opt").forEach(o => {
        o.classList.toggle("active", o.dataset.method === payMethod);
    });
    document.querySelectorAll("[data-price]").forEach(el => {
        el.textContent = PRICES[payMethod][el.dataset.price];
    });
}

// Выпадающий список способа оплаты
$("method-toggle").addEventListener("click", () => {
    $("method-select").classList.toggle("open");
});
document.querySelectorAll(".select-opt").forEach(opt => {
    opt.addEventListener("click", () => {
        payMethod = opt.dataset.method;
        localStorage.setItem("payMethod", payMethod);
        $("method-select").classList.remove("open");
        renderPayment();
        haptic();
    });
});

// Оплата: открываем бота по ссылке, в боте создаётся счёт нужного способа
function openBot(link) {
    if (tg && typeof tg.openTelegramLink === "function") {
        tg.openTelegramLink(link);
        setTimeout(() => tg.close(), 300);
    } else {
        window.location.href = link;
    }
}

let selectedPlan = "1m";
document.querySelectorAll("[data-price]").forEach(el => {
    el.closest(".tariff").addEventListener("click", () => {
        selectedPlan = el.dataset.price;
        document.querySelectorAll(".tariff").forEach(t => t.style.outline = "none");
        el.closest(".tariff").style.outline = "2px solid var(--accent)";
    });
});

$("pay-btn").addEventListener("click", () => {
    const link = payMethod === "crypto"
        ? BOT + "?start=cbuy_" + selectedPlan
        : BOT + "?start=buy_" + selectedPlan;
    if (payMethod === "sbp") {
        toast("СБП подключим позже");
        return;
    }
    openBot(link);
});

document.querySelectorAll(".tabbar button").forEach(btn => {
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

// Документы: полный текст на отдельном экране
document.querySelectorAll("[data-doc]").forEach(el => {
    el.addEventListener("click", () => {
        const doc = el.dataset.doc === "terms" ? LEGAL_TERMS : LEGAL_PRIVACY;
        $("doc-title").textContent = doc.title;
        $("doc-text").textContent = doc.text;
        showTab("doc");
    });
});

// Профиль из Telegram: имя, ID, аватарка (если есть) или первая буква
const user = tg && tg.initDataUnsafe ? tg.initDataUnsafe.user : null;
if (user) {
    $("p-name").textContent = user.first_name;
    $("p-id").textContent = user.id;
    $("home-greet").textContent = "Привет, " + user.first_name + "!";
    $("avatar-letter").textContent = user.first_name.charAt(0).toUpperCase();
    if (user.photo_url) {
        $("avatar-img").src = user.photo_url;
        $("avatar-img").hidden = false;
        $("avatar-letter").hidden = true;
    }
}

renderSettings();
renderPayment();
