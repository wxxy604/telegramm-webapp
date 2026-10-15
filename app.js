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
    const payBtn = $("pay-btn");
    if (payBtn) {
        const lbl = (T && T().pay_btn) || "Перейти к оплате";
        payBtn.textContent = payMethod === "sbp" ? "СБП — скоро" : lbl + " · " + PRICES[payMethod][selectedPlan];
    }
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

}

// Выпадающие списки верхней плашки: открываются по клику, закрываются при клике мимо
function closeDrops(except) {
    document.querySelectorAll(".drop").forEach(d => {
        if (d !== except) d.classList.remove("open");
    });
}
$("notif-toggle").addEventListener("click", e => {
    e.stopPropagation();
    const drop = $("notif-drop");
    closeDrops(drop);
    drop.classList.toggle("open");
});
$("lang-toggle").addEventListener("click", e => {
    e.stopPropagation();
    const drop = $("lang-drop");
    closeDrops(drop);
    drop.classList.toggle("open");
});
document.addEventListener("click", () => closeDrops(null));

// Язык интерфейса RU / EN
const I18N = {
    ru: {
        notif_sub_ends: "Подписка заканчивается через {d} дн.",
        notif_sub_ended: "Подписка закончилась",
        notif_trial_ends: "Пробный период заканчивается через {d} дн.",
        notif_none: "Новых уведомлений нет",
        lang_label: "RU",
        home_sub: "Статус подписки",
        home_trial: "Пробный период",
        active: "активна",
        inactive: "не активна",
        pay_btn: "Перейти к оплате",
        pay_note: "Оплата откроется в чате с ботом.",
        keys_empty: "Ключей пока нет",
        devices_empty: "Подключённых устройств пока нет",
    },
    en: {
        notif_sub_ends: "Subscription ends in {d} days",
        notif_sub_ended: "Subscription has ended",
        notif_trial_ends: "Trial ends in {d} days",
        notif_none: "No new notifications",
        lang_label: "EN",
        home_sub: "Subscription status",
        home_trial: "Trial period",
        active: "active",
        inactive: "inactive",
        pay_btn: "Continue to payment",
        pay_note: "Payment opens in the bot chat.",
        keys_empty: "No keys yet",
        devices_empty: "No devices connected",
    },
};
let lang = localStorage.getItem("lang") || "ru";
const T = () => I18N[lang];

// Статические тексты с data-i18n
function applyLang() {
    document.documentElement.lang = lang;
    document.querySelectorAll("[data-i18n]").forEach(el => {
        const v = T()[el.dataset.i18n];
        if (v) el.textContent = v;
    });
    $("lang-label").textContent = T().lang_label;
    const note = $("pay-note");
    if (note) note.textContent = T().pay_note;
    document.querySelectorAll("[data-lang]").forEach(b => {
        b.classList.toggle("active", b.dataset.lang === lang);
    });
    renderPayment();
    renderNotifications();
}
document.querySelectorAll("[data-lang]").forEach(btn => {
    btn.addEventListener("click", e => {
        e.stopPropagation();
        lang = btn.dataset.lang;
        localStorage.setItem("lang", lang);
        applyLang();
        closeDrops(null);
        haptic();
    });
});

// Состояние подписки с сервера бота (даты окончания)
const BOT_API = "https://telegramm-webapp.vercel.app/api/me";
let state = { paid_until: 0, trial_until: 0, now: Math.floor(Date.now() / 1000) };

function daysLeft(until) {
    const sec = until - state.now;
    return sec > 0 ? Math.ceil(sec / 86400) : 0;
}

// Уведомления появляются только когда что-то происходит
function buildNotifications() {
    const items = [];
    const paidDays = daysLeft(state.paid_until);
    const trialDays = daysLeft(state.trial_until);
    if (state.paid_until > 0 && paidDays > 0 && paidDays <= 3) {
        items.push(T().notif_sub_ends.replace("{d}", paidDays));
    } else if (state.paid_until > 0 && paidDays === 0) {
        items.push(T().notif_sub_ended);
    }
    if (state.trial_until > 0 && trialDays > 0 && trialDays <= 3) {
        items.push(T().notif_trial_ends.replace("{d}", trialDays));
    }
    return items;
}

function renderNotifications() {
    const list = $("notif-list");
    const items = buildNotifications();
    $("notif-dot").hidden = items.length === 0;
    list.innerHTML = "";
    if (items.length === 0) {
        const el = document.createElement("div");
        el.className = "drop-item muted";
        el.textContent = T().notif_none;
        list.appendChild(el);
        return;
    }
    items.forEach(text => {
        const el = document.createElement("div");
        el.className = "drop-item";
        el.textContent = text;
        list.appendChild(el);
    });
}

function renderStatus() {
    const paid = state.paid_until > state.now;
    const trial = state.trial_until > state.now;
    const days = daysLeft(state.paid_until);
    $("home-sub").textContent = paid
        ? `${T().active}, ${days} дн.`
        : T().inactive;
    $("home-trial").textContent = trial
        ? `${T().active}, ${daysLeft(state.trial_until)} дн.`
        : T().inactive;
}

async function loadState() {
    if (!user) return;
    try {
        const r = await fetch(`${BOT_API}?uid=${user.id}`, { cache: "no-store" });
        if (r.ok) state = await r.json();
    } catch (e) {
        // Нет связи с сервером: оставляем пустое состояние
    }
    renderStatus();
    renderNotifications();
}

renderSettings();
renderPayment();
applyLang();
renderStatus();
renderNotifications();
loadState();
showTab("home");
