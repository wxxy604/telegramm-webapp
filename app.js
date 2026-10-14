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

document.querySelectorAll("[data-plan]").forEach(btn => {
    btn.addEventListener("click", () => {
        const plan = btn.dataset.plan;
        if (!tg || !tg.initData) {
            toast("Откройте приложение из Telegram");
            return;
        }
        // Приложение закроется, а бот получит выбор тарифа и выставит счёт
        tg.sendData(JSON.stringify({ action: "buy", plan: plan }));
    });
});

const user = tg && tg.initDataUnsafe ? tg.initDataUnsafe.user : null;
if (user) {
    $("p-name").textContent = user.first_name;
    $("p-id").textContent = user.id;
    $("avatar").textContent = user.first_name.charAt(0).toUpperCase();
}
$("sub-status").textContent = "Выберите тариф ниже";
