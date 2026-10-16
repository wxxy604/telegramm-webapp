# Telegram-бот и мини приложение (SupplineVPNbot)

## Где что лежит
- `vercel-bot/` — бот на Vercel (вебхук). Деплоится из GitHub: `wxxy604/telegramm-webapp`, папка `api/` в корне.
  - `api/webhook.py` — логика бота (меню, тарифы, оплата звёздами и USDT, рефералы, пробный период).
  - `api/db.py` — база Upstash Redis (пользователи, подписки, счета).
  - `set_webhook.py` — привязка вебхука: `python set_webhook.py https://telegramm-webapp.vercel.app`
- `webapp/` — мини приложение (`index.html`, `styles.css`, `app.js`). Лежит в корне GitHub-репозитория, открывается на `https://telegramm-webapp.vercel.app`.
- `.env` — локальные переменные (`BOT_TOKEN`, `WEBAPP_URL`, `WEBHOOK_SECRET`). Не публиковать.
- `bot.py`, `requirements.txt` — старая версия бота на polling. НЕ запускать: конфликтует с вебхуком.

## Переменные в Vercel (проект telegramm-webapp)
- `BOT_TOKEN` — токен бота из @BotFather
- `WEBAPP_URL` — `https://telegramm-webapp.vercel.app/index.html`
- `WEBHOOK_SECRET` — секрет вебхука (тот же, что в `.env`)
- `UPSTASH_REDIS_REST_URL`, `UPSTASH_REDIS_REST_TOKEN` — база
- `CRYPTO_PAY_TOKEN` — токен Crypto Pay (@CryptoBot)

После изменения переменных нужен Redeploy.

## Оплата и тарифы
- Тарифы: 1 мес (150 ⭐ / 2 USDT), 3 мес (400 ⭐ / 5 USDT), 12 мес (1400 ⭐ / 18 USDT).
- Звёзды Telegram — зачисляются на баланс бота (вывод через Fragment в @BotFather).
- USDT — Crypto Pay, проверка оплаты кнопкой «Я оплатил», защита от повторного начисления.

## Важно
- Перевыпустить токены, которые были в чате: Telegram (@BotFather `/revoke`), Crypto Pay (@CryptoBot), Upstash.
- Vercel Hobby — только некоммерческое использование.
- Ключи выдаются из пула публичных VPN-конфигов (Upstash, ключ `pool:free`). Конфиги добавляет `vercel-bot/import_configs.py`. После оплаты или пробного периода ключ показывается в боте и в разделе «Мои ключи».

## Следующий шаг
1. Парсер выгружает ссылки в файл и запускает `python import_configs.py configs.txt` из `vercel-bot/`.
2. Выдача ключа после оплаты и раздел «Ключи» в мини приложении.
