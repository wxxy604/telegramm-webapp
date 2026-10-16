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
    sbp:    { "1m": "100 ₽", "3m": "250 ₽", "12m": "900 ₽" },
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
        const dict = I18N_FULL[lang];
        const lbl = dict.pay_btn;
        payBtn.textContent = payMethod === "sbp"
            ? dict.sbp_soon
            : lbl + " · " + PRICES[payMethod][selectedPlan];
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

// Документы: полный текст на отдельном экране (текст документа на выбранном языке)
let currentDoc = null;
document.querySelectorAll("[data-doc]").forEach(el => {
    el.addEventListener("click", () => {
        currentDoc = el.dataset.doc === "terms" ? LEGAL_TERMS : LEGAL_PRIVACY;
        $("doc-title").textContent = currentDoc.title;
        $("doc-text").textContent = currentDoc.text;
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

// Язык интерфейса RU / EN: весь интерфейс берётся из словаря
const I18N_FULL = {
    ru: {
        home_subtitle: "Ваш доступ и баланс", home_sub: "Статус подписки", balance: "Баланс",
        renew: "Продлить подписку", renew_sub: "Выбрать способ оплаты",
        my_keys: "Мои ключи", my_keys_sub: "Подключение для устройств",
        keys_title: "Ключи", keys_subtitle: "Ключи появятся после активации подписки", keys_empty: "Ключей пока нет",
        devices_title: "Устройства", devices_count: "Подключено", devices_empty: "Подключённых устройств пока нет",
        pay_title: "Оплата", pay_subtitle: "Выберите способ оплаты и тариф", pay_method: "Способ оплаты",
        method_stars: "Звёзды Telegram", pay_plan: "Тариф",
        plan_1m: "1 месяц", plan_1m_sub: "30 дней полного доступа",
        plan_3m: "3 месяца", plan_3m_sub: "90 дней, выгоднее на 10%",
        plan_12m: "12 месяцев", plan_12m_sub: "365 дней, максимальная выгода",
        pay_note: "Оплата откроется в чате с ботом.", pay_btn: "Перейти к оплате",
        settings_title: "Настройки", settings_subtitle: "Параметры приложения",
        settings_functions: "Функции", set_notify: "Уведомления", set_notify_sub: "Напоминать об окончании подписки",
        set_theme: "Светлая тема", set_theme_sub: "Переключить оформление",
        settings_account: "Аккаунт", acc_name: "Имя",
        settings_docs: "Документы", doc_terms: "Пользовательское соглашение", doc_privacy: "Политика конфиденциальности",
        back: "Назад",
        tab_home: "Главная", tab_devices: "Устройства", tab_pay: "Оплата", tab_settings: "Настройки",
        active: "активна", inactive: "не активна",
        notif_sub_ends: "Подписка заканчивается через {d} дн.", notif_sub_ended: "Подписка закончилась",
        notif_trial_ends: "Пробный период заканчивается через {d} дн.", notif_none: "Новых уведомлений нет",
        lang_label: "RU", sbp_soon: "СБП — скоро", sbp_unavailable: "СБП пока недоступен",
        pay_opened: "Откройте чат с ботом",
    },
    en: {
        home_subtitle: "Your access and balance", home_sub: "Subscription status", balance: "Balance",
        renew: "Renew subscription", renew_sub: "Choose payment method",
        my_keys: "My keys", my_keys_sub: "Connection for devices",
        keys_title: "Keys", keys_subtitle: "Keys will appear after activation", keys_empty: "No keys yet",
        devices_title: "Devices", devices_count: "Connected", devices_empty: "No connected devices",
        pay_title: "Payment", pay_subtitle: "Choose a payment method and plan", pay_method: "Payment method",
        method_stars: "Telegram Stars", pay_plan: "Plan",
        plan_1m: "1 month", plan_1m_sub: "30 days of full access",
        plan_3m: "3 months", plan_3m_sub: "90 days, 10% off",
        plan_12m: "12 months", plan_12m_sub: "365 days, best value",
        pay_note: "Payment opens in the bot chat.", pay_btn: "Continue to payment",
        settings_title: "Settings", settings_subtitle: "App settings",
        settings_functions: "Features", set_notify: "Notifications", set_notify_sub: "Remind about subscription expiry",
        set_theme: "Light theme", set_theme_sub: "Switch appearance",
        settings_account: "Account", acc_name: "Name",
        settings_docs: "Documents", doc_terms: "Terms of Use", doc_privacy: "Privacy Policy",
        back: "Back",
        tab_home: "Home", tab_devices: "Devices", tab_pay: "Payment", tab_settings: "Settings",
        active: "active", inactive: "inactive",
        notif_sub_ends: "Subscription ends in {d} days", notif_sub_ended: "Subscription has ended",
        notif_trial_ends: "Trial ends in {d} days", notif_none: "No new notifications",
        lang_label: "EN", sbp_soon: "SBP — soon", sbp_unavailable: "SBP is not available yet",
        pay_opened: "Open the bot chat",
    },
};

// Старый словарь уведомлений/статусов оставлен для совместимости
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

// Переводим весь интерфейс: каждый элемент с data-i18n получает текст выбранного языка
function applyLang() {
    const dict = I18N_FULL[lang];
    document.documentElement.lang = lang;
    document.querySelectorAll("[data-i18n]").forEach(el => {
        const v = dict[el.dataset.i18n];
        if (v) el.textContent = v;
    });
    $("lang-label").textContent = dict.lang_label;
    document.querySelectorAll("[data-lang]").forEach(b => {
        b.classList.toggle("active", b.dataset.lang === lang);
    });
    renderPayment();
    renderNotifications();
    renderStatus();
    // Заголовок выбранного экрана документа
    if (currentDoc) $("doc-title").textContent = currentDoc.title;
}
document.querySelectorAll("[data-lang]").forEach(btn => {
    btn.addEventListener("click", e => {
        e.stopPropagation();
        lang = btn.dataset.lang;
        localStorage.setItem("lang", lang);
        applyLang();
        // Смена языка закрывает все выпадающие списки (язык, уведомления, способ оплаты)
        closeDrops(null);
        $("method-select").classList.remove("open");
        haptic();
    });
});

// Состояние подписки с сервера бота (даты окончания)
const BOT_API = "https://telegramm-webapp.vercel.app/api/webhook";
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

// Серверы: 10 лучших по пингу с сервера бота
const SERVERS_API = "https://telegramm-webapp.vercel.app/api/webhook?servers=1";
let serversAccess = false;
const APPS_GUIDE = [
    { os: "iPhone / iPad", app: "Streisand или V2Box (App Store)", how: "Откройте приложение, нажмите «+» → «Вставить из буфера». Выберите сервер и включите подключение." },
    { os: "Android", app: "v2rayNG или Hiddify (Google Play)", how: "Откройте приложение, нажмите «+» → «Импорт из буфера обмена». Выберите сервер и включите подключение." },
    { os: "Windows", app: "Hiddify или v2rayN", how: "Откройте приложение, нажмите «Вставить ключ» или «Импорт из буфера». Выберите сервер и подключитесь." },
    { os: "macOS", app: "Streisand или Hiddify", how: "Откройте приложение, выберите «Добавить из буфера». Выберите сервер и включите подключение." },
];
let servers = [];
let currentServer = null;

function renderServers() {
    const list = $("servers-list");
    list.innerHTML = "";
    if (!serversAccess) {
        const el = document.createElement("div");
        el.className = "empty";
        el.textContent = "Серверы доступны с подпиской или пробным периодом";
        list.appendChild(el);
        return;
    }
    if (servers.length === 0) {
        const el = document.createElement("div");
        el.className = "empty";
        el.textContent = "Серверы пока не готовы";
        list.appendChild(el);
        return;
    }
    servers.forEach((s, i) => {
        const row = document.createElement("div");
        row.className = "row server-row";
        row.innerHTML = `<div class="row-body"><div class="row-title"></div></div><div class="server-ping"></div>`;
        row.querySelector(".row-title").textContent = s.name;
        row.querySelector(".server-ping").textContent = s.ping + " мс";
        row.addEventListener("click", () => openSheet(i));
        list.appendChild(row);
    });
}

async function loadServers() {
    if (!user) {
        renderServers();
        return;
    }
    try {
        const r = await fetch(`${SERVERS_API}&uid=${user.id}`, { cache: "no-store" });
        if (r.ok) {
            const data = await r.json();
            servers = data.servers || [];
            serversAccess = !!data.access;
        }
    } catch (e) {
        // Нет связи: список остаётся пустым
    }
    renderServers();
}

$("servers-toggle").addEventListener("click", () => {
    $("servers-box").classList.toggle("open");
    haptic();
});

function openSheet(index) {
    currentServer = servers[index];
    if (!currentServer) return;
    $("sheet-title").textContent = currentServer.name;
    $("sheet-meta").textContent = "Пинг: " + currentServer.ping + " мс";
    const apps = $("sheet-apps");
    apps.innerHTML = "";
    APPS_GUIDE.forEach(g => {
        const row = document.createElement("div");
        row.className = "row";
        row.innerHTML = `<div class="row-body"><div class="row-title"></div><div class="row-sub"></div></div>`;
        row.querySelector(".row-title").textContent = g.os;
        row.querySelector(".row-sub").textContent = g.app;
        apps.appendChild(row);
    });
    $("sheet-howto").textContent = APPS_GUIDE.map(g => g.os + ": " + g.how).join("\n\n");
    $("sheet").classList.add("open");
    $("sheet-backdrop").classList.add("show");
    $("sheet").setAttribute("aria-hidden", "false");
    haptic();
}

function closeSheet() {
    $("sheet").classList.remove("open");
    $("sheet-backdrop").classList.remove("show");
    $("sheet").setAttribute("aria-hidden", "true");
}

$("sheet-backdrop").addEventListener("click", closeSheet);

async function copyText(text) {
    try {
        await navigator.clipboard.writeText(text);
        return true;
    } catch (e) {
        // Запасной способ, если Clipboard API недоступен в WebView Telegram
        const ta = document.createElement("textarea");
        ta.value = text;
        ta.setAttribute("readonly", "");
        ta.style.position = "fixed";
        ta.style.opacity = "0";
        document.body.appendChild(ta);
        ta.select();
        const ok = document.execCommand("copy");
        ta.remove();
        return ok;
    }
}

$("sheet-copy").addEventListener("click", async () => {
    if (!currentServer) return;
    const ok = await copyText(currentServer.uri);
    toast(ok ? "Ключ скопирован" : "Не удалось скопировать");
    haptic();
});

renderSettings();
renderPayment();
applyLang();
renderStatus();
renderNotifications();
loadState();
loadServers();
showTab("home");
