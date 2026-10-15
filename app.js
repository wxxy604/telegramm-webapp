const tg = window.Telegram ? window.Telegram.WebApp : null;
if (tg) {
    tg.ready();
    tg.expand();
    if (typeof tg.disableVerticalSwipes === "function") tg.disableVerticalSwipes();
}

const $ = (id) => document.getElementById(id);
const BOT = "https://t.me/SupplineVPNbot";

// Настройки и выбранный способ оплаты сохраняются в браузере
const settings = Object.assign({ notify: true, theme: false },
    JSON.parse(localStorage.getItem("settings") || "{}"));
let payMethod = localStorage.getItem("payMethod") || "crypto";
let selectedPlan = "1m";

const PRICES = {
    crypto: { "1m": "2 USDT", "3m": "5 USDT", "12m": "18 USDT" },
    stars:  { "1m": "150 ⭐", "3m": "400 ⭐", "12m": "1 400 ⭐" },
    sbp:    { "1m": "199 ₽", "3m": "499 ₽", "12m": "1 490 ₽" },
};
const METHOD_NAMES = { crypto: "CryptoBot (USDT)", stars: "Звёзды Telegram", sbp: "СБП" };

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

// Показываем только один экран и подсвечиваем вкладку
function showTab(tab) {
    document.querySelectorAll(".screen").forEach(s => {
        const on = s.id === "screen-" + tab;
        s.classList.toggle("active", on);
        s.style.display = on ? "block" : "none";
    });
    document.querySelectorAll(".tabbar button").forEach(b => {
        b.classList.toggle("active", b.dataset.tab === tab);
    });
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
    document.querySelectorAll(".plan-row").forEach(r => {
        r.classList.toggle("selected", r.dataset.plan === selectedPlan);
    });
    $("pay-btn").textContent = payMethod === "sbp"
        ? "СБП — скоро"
        : "Оплатить " + PRICES[payMethod][selectedPlan];
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

// Выбор тарифа
document.querySelectorAll(".plan-row").forEach(row => {
    row.addEventListener("click", () => {
        selectedPlan = row.dataset.plan;
        renderPayment();
        haptic();
    });
});

// Оплата: открываем бота по deep link, там создаётся счёт нужного способа
function openBot(link) {
    if (tg && typeof tg.openTelegramLink === "function") {
        tg.openTelegramLink(link);
        setTimeout(() => tg.close(), 300);
    } else {
        window.location.href = link;
    }
}

$("pay-btn").addEventListener("click", () => {
    if (payMethod === "sbp") {
        toast("СБП пока недоступен");
        return;
    }
    const prefix = payMethod === "crypto" ? "cbuy_" : "buy_";
    openBot(BOT + "?start=" + prefix + selectedPlan);
});

document.querySelectorAll(".tabbar button").forEach(btn => {
    btn.addEventListener("click", () => showTab(btn.dataset.tab));
});
document.querySelectorAll("[data-go]").forEach(el => {
    el.addEventListener("click", () => showTab(el.dataset.go));
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

// Профиль из Telegram: имя, ID, аватарка или первая буква
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
showTab("home");
