# Telegram VPN Subscription Bot

## Что делает

Этот бот:
- регистрирует пользователей Telegram
- выдает ссылку на личную VPN-подписку
- хранит дату окончания подписки
- после истечения подписки возвращает пустой файл с комментарием

## Файлы

- `tools/vpn_telegram_bot.py` — основной бот + HTTP-сервер
- `tools/run_vpn_bot.sh` — скрипт для запуска
- `tools/bot_data/subscribers.db` — SQLite база подписчиков и транзакций (создается автоматически)
- `.env` — конфигурация окружения для запуска

## Переменные окружения

- `VPN_TELEGRAM_BOT_TOKEN` — токен бота Telegram
- `VPN_SUBSCRIPTION_BASE_URL` — ссылка, которую бот отправляет пользователям
- `VPN_SUBSCRIPTION_HOST` — адрес HTTP-сервера (по умолчанию `0.0.0.0`)
- `VPN_SUBSCRIPTION_PORT` — порт HTTP-сервера (по умолчанию `8080`)
- `VPN_DEFAULT_SUBSCRIBE_DAYS` — сколько дней дается по умолчанию (по умолчанию `7`)
- `VPN_BOT_ADMIN_IDS` — список admin id через запятую (опционально)
- `TELEGRAM_PAYMENT_PROVIDER_TOKEN` — токен провайдера платежей Telegram (если есть)
- `PAYMENT_CURRENCY` — валюта для платежа (по умолчанию `USD`)
- `PAYMENT_PRICE` — цена за день или фиксированный пакет в центов
- `PAYMENT_TITLE` — заголовок счета Telegram
- `PAYMENT_DESCRIPTION` — описание платежа
- `PAYMENT_LINK_TEMPLATE` — шаблон ссылки ручной оплаты для fallback

## Команды бота

- `/start` — начать работу с ботом
- `/help` — помощь
- `/subscribe [days]` — активировать или продлить подписку
- `/pay [days]` — оплатить подписку через Telegram или ссылку
- `/price [days]` — посмотреть стоимость
- `/link` — получить ссылку на VPN-подписку
- `/status` — проверить состояние подписки
- `/cancel` — отменить подписку
- `/renew [days]` — продлить подписку
- `/about` — информация о боте

## Админ-команды

- `/confirm <user_id> [days]` — вручную активировать подписку для пользователя
- `/subscribers` — показать последние подписчиков
- `/admin` — список доступных админ-команд

## Как запустить

```bash
export VPN_TELEGRAM_BOT_TOKEN="<your_bot_token>"
export VPN_SUBSCRIPTION_BASE_URL="https://example.com"
export VPN_SUBSCRIPTION_HOST="0.0.0.0"
export VPN_SUBSCRIPTION_PORT="8080"

bash tools/run_vpn_bot.sh
```

## Как работает ссылка

Пользователь получает URL вида:

```
https://example.com/sub/<user_id>.txt
```

Если подписка активна, файл содержит текущие сервера из `local-out/top.txt`.
Если подписка истекла, файл возвращает только комментарий и не содержит серверов.
