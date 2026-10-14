const tg = window.Telegram ? window.Telegram.WebApp : null;
if (tg) { tg.ready(); tg.expand(); }

const $ = (id) => document.getElementById(id);

function toast(text) {
    const el = $("toast");
    el.textContent = text;
    el.classList.add("show");
    setTimeout(() => el.classList.remove("show"), 1800);
}

function showTab(tab) {
    document.querySelectorAll(".screen").forEach(s => s.classList.remove("active"));
    document.querySelectorAll("nav button").forEach(b => b.classList.remove("active"));
    $("screen-" + tab).classList.add("active");
    document.querySelector(`nav button[data-tab="${tab}"]`).classList.add("active");
    if (tg && tg.HapticFeedback) tg.HapticFeedback.impactOccurred("light");
}

document.querySelectorAll("nav button").forEach(btn => {
    btn.addEventListener("click", () => showTab(btn.dataset.tab));
});

document.querySelectorAll("[data-crypto]").forEach(btn => {
    btn.addEventListener("click", () => {
        if (!tg || !tg.initData) {
            toast("Откройте приложение из Telegram");
            return;
        }
        // Бот по payload cbuy_<план> создаст счёт Crypto Pay в USDT
        tg.openTelegramLink("https://t.me/SupplineVPNbot?start=cbuy_" + btn.dataset.crypto);
        tg.close();
    });
});

document.querySelectorAll("[data-plan]").forEach(btn => {
    btn.addEventListener("click", () => {
        const plan = btn.dataset.plan;
        if (!tg || !tg.initData) {
            toast("Откройте приложение из Telegram");
            return;
        }
        // Открываем чат с ботом по deep link: бот по payload выставит счёт
        tg.openTelegramLink("https://t.me/SupplineVPNbot?start=buy_" + plan);
        tg.close();
    });
});

const user = tg && tg.initDataUnsafe ? tg.initDataUnsafe.user : null;
if (user) {
    $("p-name").textContent = user.first_name;
    $("p-id").textContent = user.id;
    $("avatar").textContent = user.first_name.charAt(0).toUpperCase();
}
$("sub-status").textContent = "Выберите тариф ниже";
