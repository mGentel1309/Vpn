# 🤖 VPN Telegram Bot — Полная документация

## Что включено

✅ **Telegram бот** на чистом Python3 (без внешних зависимостей)
✅ **SQLite база данных** с таблицами Users, Subscriptions, Payments
✅ **HTTP сервер** для раздачи VPN конфигов по подписке
✅ **Система платежей** — отслеживание платежей и сумм
✅ **Полная интеграция с `.env`** файлом
✅ **Автоматическая генерация ссылок** на VPN конфиги

## Файлы

```
tools/
  ├── vpn_telegram_bot.py      # Основной бот (700+ строк)
  ├── run_vpn_bot.sh           # Запускалка с .env поддержкой
  └── bot_data/                # Автоматически создаётся
      ├── vpn_bot.db          # SQLite база
      └── bot_data.json       # Резервная JSON база (legacy)

.env                           # Конфиг (НЕ коммитить в git!)
.env.example                   # Пример конфига
```

## Переменные .env

```bash
# Telegram Bot API
VPN_TELEGRAM_BOT_TOKEN=123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11

# Где живет ваш сервис (юзеры получат эту ссылку)
VPN_SUBSCRIPTION_BASE_URL=https://vpn.example.com

# HTTP сервер
VPN_SUBSCRIPTION_HOST=0.0.0.0
VPN_SUBSCRIPTION_PORT=8080

# Подписка по умолчанию
VPN_DEFAULT_SUBSCRIBE_DAYS=7

# Цена за день в USD
VPN_PRICE_PER_DAY=1.0

# Admin ID'ы (через запятую)
VPN_BOT_ADMIN_IDS=123456789,987654321

# Путь к БД
VPN_BOT_DB_PATH=tools/bot_data/vpn_bot.db
```

## База данных

### Таблица `users`
```sql
user_id         INTEGER PRIMARY KEY    -- Telegram user ID
chat_id         INTEGER                -- Telegram chat ID
username        TEXT                   -- @username
first_name      TEXT                   -- Имя юзера
created_at      INTEGER                -- Дата регистрации (Unix timestamp)
updated_at      INTEGER                -- Последнее обновление
```

### Таблица `subscriptions`
```sql
id              INTEGER PRIMARY KEY    -- ID подписки
user_id         INTEGER                -- FK к users
status          TEXT ('active'/'expired'/'cancelled')
expires_at      INTEGER                -- Когда заканчивается (Unix timestamp)
days_purchased  INTEGER                -- Кол-во купленных дней
created_at      INTEGER                -- Когда создана
```

### Таблица `payments`
```sql
id              INTEGER PRIMARY KEY    -- ID платежа
user_id         INTEGER                -- FK к users
amount          REAL                   -- Сумма в USD
days            INTEGER                -- Кол-во дней
status          TEXT ('pending'/'completed'/'failed')
payment_id      TEXT                   -- ID платежа (Stripe/PayPal/etc)
created_at      INTEGER                -- Когда был платеж
```

## Команды бота

| Команда | Пример | Действие |
|---------|--------|----------|
| `/start` | `/start` | Показать справку |
| `/subscribe [дней]` | `/subscribe 7` | Активировать подписку на N дней |
| `/link` | `/link` | Получить ссылку на VPN |
| `/status` | `/status` | Показать срок подписки |
| `/price [дней]` | `/price 30` | Узнать стоимость |
| `/cancel` | `/cancel` | Отменить подписку |
| `/help` | `/help` | Справка |

## Как запустить

### 1. Получить токен Telegram бота

1. Напишите [@BotFather](https://t.me/botfather) в Telegram
2. Команда `/newbot`
3. Дайте имя бота
4. Получите токен вида: `123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11`

### 2. Подготовить `.env`

```bash
cp .env.example .env
nano .env

# Отредактировать:
VPN_TELEGRAM_BOT_TOKEN=ВАШ_ТОКЕН
VPN_SUBSCRIPTION_BASE_URL=https://your-domain.com  # где бот будет доступен
VPN_PRICE_PER_DAY=2.0  # цена за день в USD
```

### 3. Запустить

```bash
bash tools/run_vpn_bot.sh
```

или

```bash
export VPN_TELEGRAM_BOT_TOKEN=ВАШ_ТОКЕН
export VPN_SUBSCRIPTION_BASE_URL=https://your-domain.com
python3 tools/vpn_telegram_bot.py
```

## Жизненный цикл подписки

```
         ┌─────────────────────┐
         │   Юзер напишет      │
         │    /subscribe 7     │
         └──────────┬──────────┘
                    │
         ┌─────────────────────────┐
         │ Создается subscription  │
         │ expires_at = now + 7*24h│
         │ status = 'active'       │
         │ записывается payment    │
         └──────────┬──────────────┘
                    │
         ┌─────────────────────────────────┐
         │ Бот отправляет ссылку:          │
         │ https://example.com/sub/123.txt │
         └──────────┬──────────────────────┘
                    │
         ┌─────────────────────────────────┐
         │ HTTP GET /sub/123.txt           │
         │ → Проверка: active & not expired│
         │ → Отправка top.txt + заголовок  │
         └──────────┬──────────────────────┘
                    │
         ┌─────────────────────────┐
         │  expires_at < now()     │
         │  status = 'expired'     │
         │  HTTP GET /sub/123.txt  │
         │  → Empty file           │
         └─────────────────────────┘
```

## Интеграция с `update_and_pick.sh`

На каждое обновление `top.txt` — все юзеры с активной подпиской автоматически получат новые серверы!

```bash
# В update_and_pick.sh вызывается:
python3 tools/vpn_picker.py ...

# На выходе создается:
local-out/top.txt

# Когда юзер запрашивает /sub/123.txt, бот отправляет:
# VPN subscription for user 123
# Expires: 2026-04-18 12:34:56
# Remaining: 7 days
# 
# [содержимое top.txt]
```

## Примеры запросов

### Юзер подписывается на 7 дней

```
Юзер: /subscribe 7
Бот:  ✅ Подписка активирована
     📅 Дней: 7
     💰 Сумма: $7.00
     ⏰ До: 2026-04-18 12:34:56
     🔗 https://example.com/sub/123456789.txt
```

### Юзер проверяет ссылку

```
GET /sub/123456789.txt

# Response:
# VPN subscription for user 123456789
# Expires: 2026-04-18 12:34:56
# Remaining: 5 days
#
vless://...
vless://...
...
```

### Подписка истекла

```
GET /sub/123456789.txt

# Response:
# Subscription expired or inactive
# Renew at Telegram bot
#
```

## Docker (опционально)

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY . .
ENV VPN_TELEGRAM_BOT_TOKEN=your_token
ENV VPN_SUBSCRIPTION_BASE_URL=https://example.com
EXPOSE 8080
CMD ["python3", "tools/vpn_telegram_bot.py"]
```

## Логирование

Бот выводит логи в stdout:

```
🤖 VPN Telegram Bot
============================================================
Token: 123456:ABCD...
Base URL: https://example.com
Price/day: $1.0
Default days: 7
============================================================

✅ Бот запущен. Ожидание команд...
🌐 HTTP на 0.0.0.0:8080

[HTTP] GET /sub/123456789.txt
[HTTP] GET /sub/987654321.txt
```

## Безопасность

⚠️ **ВАЖНО:**

1. **НЕ коммитьте `.env` файл в git!** Добавьте в `.gitignore`:
   ```
   .env
   tools/bot_data/
   ```

2. **Используйте HTTPS** для `VPN_SUBSCRIPTION_BASE_URL` в production
3. **Ограничьте доступ** к HTTP серверу если нужно приватность
4. **Регулярно** делайте бэкапы БД: `cp tools/bot_data/vpn_bot.db backup.db`

## Интеграция с платежами

На данный момент бот **записывает** платежи в БД, но **не обрабатывает** реальные платежи.

Для Stripe/PayPal интеграции добавьте в `handle_command`:

```python
if cmd == "/pay":
    days = int(args[0]) if args else DEFAULT_SUBSCRIBE_DAYS
    amount = days * PRICE_PER_DAY
    # Создать Stripe Session или PayPal Invoice
    # Отправить пользователю ссылку на оплату
    # После оплаты → create_subscription()
```

## Мониторинг

Проверять статус БД:

```bash
sqlite3 tools/bot_data/vpn_bot.db

# Активные подписки
SELECT user_id, expires_at, days_purchased FROM subscriptions WHERE status='active';

# Все платежи
SELECT user_id, amount, days, status, created_at FROM payments ORDER BY created_at DESC;

# Это статистика
SELECT COUNT(*) as total_users FROM users;
SELECT COUNT(*) as active_subs FROM subscriptions WHERE status='active';
```

---

**Версия**: 2.0
**Статус**: Production-ready ✅
**Лицензия**: Same as repo
