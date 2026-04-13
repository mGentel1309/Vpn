#!/usr/bin/env python3
"""VPN Telegram Bot v2.0 - with SBP payments and secure access tokens."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import sqlite3
import ssl
import shutil
import subprocess
import threading
import time
import uuid
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

# Fix SSL certificate issues on macOS
ssl._create_default_https_context = ssl._create_unverified_context

# Load environment
def load_env():
    env_file = Path(__file__).parent.parent / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, val = line.split("=", 1)
                if key not in os.environ:
                    os.environ[key] = val.strip('"').strip("'")

load_env()

ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "tools" / "bot_data"
DB_PATH = Path(os.environ.get("VPN_BOT_DB_PATH", str(DATA_DIR / "vpn_bot.db")))
TOP_FILE = ROOT_DIR / "local-out" / "top.txt"

BOT_TOKEN = os.environ.get("VPN_TELEGRAM_BOT_TOKEN")
if not BOT_TOKEN:
    raise SystemExit("❌ VPN_TELEGRAM_BOT_TOKEN not set in .env")

BASE_URL = os.environ.get("VPN_SUBSCRIPTION_BASE_URL", "http://127.0.0.1:8080")
HTTP_HOST = os.environ.get("VPN_SUBSCRIPTION_HOST", "0.0.0.0")
HTTP_PORT = int(os.environ.get("VPN_SUBSCRIPTION_PORT", "8080"))
API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"
DEFAULT_SUBSCRIBE_DAYS = int(os.environ.get("VPN_DEFAULT_SUBSCRIBE_DAYS", "7"))
PRICE_PER_DAY = float(os.environ.get("VPN_PRICE_PER_DAY", "1.0"))
ADMIN_IDS = {int(x.strip()) for x in os.environ.get("VPN_BOT_ADMIN_IDS", "").split(",") if x.strip()}
HTTPS_ENABLED = os.environ.get("HTTPS_ENABLED", "false").lower() == "true"
ALLOW_SELF_SIGNED = os.environ.get("ALLOW_SELF_SIGNED", "false").lower() == "true"
SSL_CERT_FILE = Path(os.environ.get("SSL_CERT_FILE", str(DATA_DIR / "server.crt")))
SSL_KEY_FILE = Path(os.environ.get("SSL_KEY_FILE", str(DATA_DIR / "server.key")))
MAX_DEVICES_PER_USER = int(os.environ.get("MAX_DEVICES_PER_USER", "2"))
CLEANUP_INTERVAL_SECONDS = int(os.environ.get("CLEANUP_INTERVAL_SECONDS", "600"))
# Ensure BASE_URL uses https when HTTPS is enabled
if HTTPS_ENABLED and BASE_URL.startswith("http://"):
    BASE_URL = BASE_URL.replace("http://", "https://", 1)

# Payment gateway config
PAYMENT_ENABLED = os.environ.get("PAYMENT_ENABLED", "false").lower() == "true"
YOOKASSA_SHOP_ID = os.environ.get("YOOKASSA_SHOP_ID", "")
YOOKASSA_API_KEY = os.environ.get("YOOKASSA_API_KEY", "")


def init_db() -> None:
    """Initialize SQLite database."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))

    # Users table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            chat_id INTEGER NOT NULL,
            username TEXT,
            first_name TEXT,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        )
    """)

    # Subscriptions table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            status TEXT DEFAULT 'active',
            expires_at INTEGER NOT NULL,
            days_purchased INTEGER DEFAULT 0,
            created_at INTEGER NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        )
    """)

    # Payments table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            days INTEGER NOT NULL,
            status TEXT DEFAULT 'pending',
            payment_id TEXT UNIQUE,
            yookassa_id TEXT,
            created_at INTEGER NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        )
    """)

    # Access tokens table - for secure personalized links
    conn.execute("""
        CREATE TABLE IF NOT EXISTS access_tokens (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            created_at INTEGER NOT NULL,
            expires_at INTEGER NOT NULL,
            used_count INTEGER DEFAULT 0,
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        )
    """)

    conn.commit()
    conn.close()


def now_ts() -> int:
    return int(time.time())


def format_ts(ts: int) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def gen_token() -> str:
    """Generate secure access token."""
    return base64.urlsafe_b64encode(uuid.uuid4().bytes).decode().rstrip("=")


def prune_old_user_tokens(user_id: int) -> None:
    """Keep only the latest N active tokens per user."""
    conn = sqlite3.connect(DB_PATH)
    now = now_ts()
    cur = conn.execute(
        "SELECT token FROM access_tokens WHERE user_id = ? AND expires_at > ? ORDER BY created_at DESC",
        (user_id, now),
    )
    tokens = [row[0] for row in cur.fetchall()]
    if len(tokens) >= MAX_DEVICES_PER_USER:
        for token in tokens[MAX_DEVICES_PER_USER - 1 :]:
            conn.execute("DELETE FROM access_tokens WHERE token = ?", (token,))
        conn.commit()
    conn.close()


def create_access_token(user_id: int) -> str:
    """Create access token for user."""
    prune_old_user_tokens(user_id)
    token = gen_token()
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT OR REPLACE INTO access_tokens (token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
        (token, user_id, now_ts(), now_ts() + 365 * 24 * 60 * 60),
    )
    conn.commit()
    conn.close()
    return token


def verify_token(token: str) -> int | None:
    """Verify token and return user_id."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute(
        "SELECT user_id FROM access_tokens WHERE token = ? AND expires_at > ?",
        (token, now_ts()),
    )
    row = cur.fetchone()
    if row:
        conn.execute("UPDATE access_tokens SET used_count = used_count + 1 WHERE token = ?", (token,))
        conn.commit()
    conn.close()
    return row[0] if row else None


def cleanup_expired_subscriptions() -> None:
    """Expire subscriptions and delete access tokens for users without active subs."""
    conn = sqlite3.connect(DB_PATH)
    now = now_ts()
    conn.execute(
        "UPDATE subscriptions SET status = 'expired' WHERE status = 'active' AND expires_at <= ?",
        (now,),
    )
    conn.execute(
        "DELETE FROM access_tokens WHERE expires_at <= ?",
        (now,),
    )
    conn.execute(
        "DELETE FROM access_tokens WHERE user_id NOT IN (SELECT DISTINCT user_id FROM subscriptions WHERE status = 'active' AND expires_at > ?)",
        (now,),
    )
    conn.commit()
    conn.close()


def ensure_ssl_certificates() -> bool:
    """Generate self-signed certs if missing and HTTPS is enabled."""
    if SSL_CERT_FILE.exists() and SSL_KEY_FILE.exists():
        return True

    if not ALLOW_SELF_SIGNED:
        print("⚠️ HTTPS включен, но действительный сертификат не найден. Используется HTTP.")
        return False

    if shutil.which("openssl") is None:
        print("⚠️ HTTPS enabled and self-signed allowed but openssl not found; using HTTP instead.")
        return False

    SSL_CERT_FILE.parent.mkdir(parents=True, exist_ok=True)
    print("🔐 Генерируем self-signed SSL сертификат...")
    try:
        subprocess.run(
            [
                "openssl",
                "req",
                "-x509",
                "-nodes",
                "-days",
                "365",
                "-newkey",
                "rsa:2048",
                "-keyout",
                str(SSL_KEY_FILE),
                "-out",
                str(SSL_CERT_FILE),
                "-subj",
                "/CN=localhost",
            ],
            check=True,
        )
        return True
    except subprocess.CalledProcessError as exc:
        print(f"❌ Не удалось создать SSL сертификат: {exc}")
        return False


def get_user(user_id: int) -> dict[str, Any] | None:
    """Get user from database."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def update_user(user_id: int, chat_id: int, username: str | None, first_name: str | None) -> None:
    """Update or create user in database."""
    conn = sqlite3.connect(DB_PATH)
    existing = conn.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,)).fetchone()
    if existing:
        conn.execute(
            "UPDATE users SET chat_id = ?, username = ?, first_name = ?, updated_at = ? WHERE user_id = ?",
            (chat_id, username, first_name, now_ts(), user_id),
        )
    else:
        conn.execute(
            "INSERT INTO users (user_id, chat_id, username, first_name, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, chat_id, username, first_name, now_ts(), now_ts()),
        )
    conn.commit()
    conn.close()


def get_subscription(user_id: int) -> dict[str, Any] | None:
    """Get active subscription."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.execute(
        "SELECT * FROM subscriptions WHERE user_id = ? AND status = 'active' ORDER BY expires_at DESC LIMIT 1",
        (user_id,),
    )
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def create_subscription(user_id: int, days: int) -> dict[str, Any]:
    """Create or extend subscription."""
    conn = sqlite3.connect(DB_PATH)
    expires_at = now_ts() + max(1, days) * 24 * 60 * 60
    conn.execute(
        "INSERT INTO subscriptions (user_id, status, expires_at, days_purchased, created_at) VALUES (?, ?, ?, ?, ?)",
        (user_id, "active", expires_at, days, now_ts()),
    )
    conn.commit()
    sub_id = conn.lastrowid
    conn.row_factory = sqlite3.Row
    cur = conn.execute("SELECT * FROM subscriptions WHERE id = ?", (sub_id,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else {}


def record_payment(user_id: int, days: int, amount: float, payment_id: str = "", yookassa_id: str = "") -> None:
    """Record payment."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO payments (user_id, amount, days, status, payment_id, yookassa_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (user_id, amount, days, "completed", payment_id or gen_token(), yookassa_id, now_ts()),
    )
    conn.commit()
    conn.close()


def is_subscription_active(user_id: int) -> bool:
    """Check if subscription is active."""
    sub = get_subscription(user_id)
    return sub is not None and sub["expires_at"] > now_ts()


def get_subscription_status(user_id: int) -> tuple[str, int]:
    """Get subscription status and days remaining."""
    sub = get_subscription(user_id)
    if not sub:
        return "inactive", 0
    remaining = max(0, sub["expires_at"] - now_ts())
    days = remaining // 86400
    return "active" if sub["expires_at"] > now_ts() else "expired", days


def send_telegram(method: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    """Send request to Telegram API."""
    url = f"{API_URL}/{method}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        print(f"❌ Telegram HTTP {exc.code}: {exc.read().decode('utf-8', errors='ignore')}")
    except Exception as exc:
        print(f"⚠️  Telegram error: {exc}")
    return None


def send_message(chat_id: int, text: str, reply_markup: dict[str, Any] | None = None) -> None:
    """Send message to user."""
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    send_telegram("sendMessage", payload)


def send_message_buttons(chat_id: int, text: str, buttons: list[list[dict]]) -> None:
    """Send message with inline buttons."""
    reply_markup = {"inline_keyboard": buttons}
    send_message(chat_id, text, reply_markup)


def get_subscription_link(user_id: int) -> str:
    """Get secure subscription link for user."""
    token = create_access_token(user_id)
    return f"{BASE_URL}/sub/{user_id}/{token}/top.txt"


def create_payment_yookassa(user_id: int, days: int, amount: float) -> str | None:
    """Create payment in YooKassa SBP."""
    if not PAYMENT_ENABLED or not YOOKASSA_SHOP_ID or not YOOKASSA_API_KEY:
        return None

    payment_data = {
        "amount": {"value": f"{amount:.2f}", "currency": "RUB"},
        "payment_method_data": {"type": "sbp"},
        "confirmation": {"type": "redirect", "return_url": f"{BASE_URL}/payment-success"},
        "metadata": {"user_id": str(user_id), "days": str(days)},
        "description": f"VPN subscription for {days} days",
    }

    url = "https://payment.yookassa.ru/api/v3/payments"
    data = json.dumps(payment_data).encode("utf-8")
    auth_str = f"{YOOKASSA_SHOP_ID}:{YOOKASSA_API_KEY}"
    auth_b64 = base64.b64encode(auth_str.encode()).decode()

    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Basic {auth_b64}",
            "Idempotence-Key": str(uuid.uuid4()),
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            result = json.loads(response.read().decode("utf-8"))
            if result.get("status") == "pending":
                payment_id = result.get("id")
                record_payment(user_id, days, amount, payment_id=f"yk_{payment_id}", yookassa_id=payment_id)
                return result.get("confirmation", {}).get("confirmation_url")
    except Exception as exc:
        print(f"❌ YooKassa error: {exc}")
    return None


def handle_command(message: dict[str, Any]) -> None:
    """Handle Telegram command."""
    chat_id = message["chat"]["id"]
    user = message["from"]
    user_id = user["id"]
    username = user.get("username")
    first_name = user.get("first_name")

    update_user(user_id, chat_id, username, first_name)

    text = message.get("text", "").strip()
    if not text:
        return

    parts = text.split()
    cmd = parts[0].lower()
    args = parts[1:] if len(parts) > 1 else []

    if cmd in {"/start", "/help"}:
        buttons = [
            [
                {"text": "📅 Подписка 7 дн", "callback_data": "sub_7"},
                {"text": "📅 30 дней", "callback_data": "sub_30"},
            ],
            [
                {"text": "📅 90 дней", "callback_data": "sub_90"},
                {"text": "📅 365 дн", "callback_data": "sub_365"},
            ],
            [
                {"text": "🔗 Получить ссылку", "callback_data": "get_link"},
                {"text": "📊 Статус", "callback_data": "status"},
            ],
        ]
        send_message_buttons(
            chat_id,
            (
                "🌐 *VPN Subscription Bot v2.0*\n\n"
                "✨ Преимущества:\n"
                "• 🔐 Персональные защищенные ссылки\n"
                "• 💳 Оплата через СБП\n"
                "• 📊 Отслеживание подписки\n"
                "• ⚡ Мгновенный доступ\n\n"
                "📝 Команды:\n"
                "`/subscribe [дн]` — активировать подписку\n"
                "`/link` — получить ссылку\n"
                "`/status` — статус подписки\n"
                "`/price [дн]` — стоимость\n"
                "`/cancel` — отменить\n"
            ),
            buttons,
        )
        return

    if cmd == "/subscribe":
        days = DEFAULT_SUBSCRIBE_DAYS
        if args:
            try:
                days = max(1, int(args[0]))
            except ValueError:
                send_message(chat_id, "❌ Укажите целое число дней")
                return

        is_admin = user_id in ADMIN_IDS
        if is_admin:
            days = 365
            amount = 0
            sub = create_subscription(user_id, days)
            record_payment(user_id, days, amount)
            send_message(
                chat_id,
                (
                    f"✅ *Администратор подписка активирована*\n\n"
                    f"📅 Дней: {days} (бесплатно)\n"
                    f"⏰ До: {format_ts(sub['expires_at'])}\n"
                    f"🔗 Ссылка: `{get_subscription_link(user_id)}`\n\n"
                    f"💾 Сохраните ссылку для использования в VPN клиенте"
                ),
            )
        else:
            amount = days * PRICE_PER_DAY
            if PAYMENT_ENABLED:
                # Show payment options
                buttons = [
                    [
                        {
                            "text": f"💳 СБП {amount:.0f}₽ ({days} дн)",
                            "callback_data": f"pay_sbp_{days}",
                        }
                    ],
                    [{"text": "✅ Оплачено (свободный тест)", "callback_data": f"pay_free_{days}"}],
                ]
                send_message_buttons(
                    chat_id,
                    (
                        f"💰 *Выберите способ оплаты*\n\n"
                        f"📅 Период: {days} дней\n"
                        f"💵 Стоимость: *{amount:.2f} RUB*\n"
                        f"💱 Цена за день: ${PRICE_PER_DAY:.2f}\n\n"
                        f"✨ За оплату вы получите защищенную ссылку на VPN конфигурации"
                    ),
                    buttons,
                )
            else:
                sub = create_subscription(user_id, days)
                record_payment(user_id, days, amount)
                send_message(
                    chat_id,
                    (
                        f"✅ *Подписка активирована*\n\n"
                        f"📅 Дней: {days}\n"
                        f"💰 Сумма: ${amount:.2f}\n"
                        f"⏰ До: {format_ts(sub['expires_at'])}\n\n"
                        f"🔗 Ссылка: `{get_subscription_link(user_id)}`"
                    ),
                )
        return

    if cmd == "/link":
        if not is_subscription_active(user_id):
            send_message(
                chat_id,
                (
                    "❌ *Подписка не активна*\n\n"
                    "Используйте `/subscribe` для активации\n"
                    f"Цена: ${DEFAULT_SUBSCRIBE_DAYS * PRICE_PER_DAY:.2f} за {DEFAULT_SUBSCRIBE_DAYS} дней"
                ),
            )
            return
        link = get_subscription_link(user_id)
        sub = get_subscription(user_id)
        buttons = [
            [{"text": "📋 Скопировать ссылку", "callback_data": f"copy_link_{user_id}"}],
            [{"text": "📱 Инструкции", "callback_data": f"show_guide_{user_id}"}],
        ]
        send_message_buttons(
            chat_id,
            (
                f"🔗 *Ваша персональная VPN ссылка*\n\n"
                f"`{link}`\n\n"
                f"📱 *Как использовать:*\n"
                f"1. Скопируйте ссылку выше\n"
                f"2. Откройте ваш VPN клиент\n"
                f"3. Добавьте подписку (Add/Import)\n"
                f"4. Вставьте ссылку\n"
                f"5. Готово! 🎉\n\n"
                f"⏰ Действительна до: {format_ts(sub['expires_at'])}\n"
                f"📅 Осталось: {(sub['expires_at'] - now_ts()) // 86400} дней"
            ),
            buttons,
        )
        return

    if cmd == "/status":
        status, days = get_subscription_status(user_id)
        if status == "inactive":
            send_message(
                chat_id,
                (
                    "❌ *Нет активной подписки*\n\n"
                    "Активируйте подписку: `/subscribe`\n"
                    f"Цена: ${DEFAULT_SUBSCRIBE_DAYS * PRICE_PER_DAY:.2f}"
                ),
            )
        else:
            sub = get_subscription(user_id)
            send_message(
                chat_id,
                (
                    f"✅ *Подписка активна*\n\n"
                    f"📅 Осталось: {days} дн\n"
                    f"⏰ До: {format_ts(sub['expires_at'])}\n"
                    f"🔗 Ссылка: `{get_subscription_link(user_id)}`"
                ),
            )
        return

    if cmd == "/price":
        days = DEFAULT_SUBSCRIBE_DAYS
        if args:
            try:
                days = max(1, int(args[0]))
            except ValueError:
                send_message(chat_id, "❌ Укажите целое число дней")
                return
        amount = days * PRICE_PER_DAY
        send_message(
            chat_id,
            (
                f"💰 *Стоимость подписки*\n\n"
                f"{days} дней = *{amount:.2f} RUB*\n"
                f"за день: {PRICE_PER_DAY:.2f} RUB"
            ),
        )
        return

    if cmd == "/cancel":
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            "UPDATE subscriptions SET status = 'cancelled' WHERE user_id = ? AND status = 'active'",
            (user_id,),
        )
        conn.commit()
        conn.close()
        send_message(
            chat_id,
            (
                "❌ *Подписка отменена*\n\n"
                "Для восстановления доступа используйте `/subscribe`"
            ),
        )
        return

    send_message(chat_id, "❓ Неизвестная команда. Используйте `/help`")


def handle_callback(callback_query: dict[str, Any]) -> None:
    """Handle Telegram callback query."""
    callback_id = callback_query["id"]
    chat_id = callback_query["from"]["id"]
    user_id = callback_query["from"]["id"]
    data = callback_query["data"]

    # Mark callback as handled
    send_telegram("answerCallbackQuery", {"callback_query_id": callback_id})

    if data.startswith("sub_"):
        days = int(data.split("_")[1])
        is_admin = user_id in ADMIN_IDS
        if is_admin:
            days = 365
            amount = 0
            sub = create_subscription(user_id, days)
            record_payment(user_id, days, amount)
            send_message(
                chat_id,
                (
                    f"✅ *Администратор подписка активирована*\n\n"
                    f"📅 {days} дней (бесплатно)\n"
                    f"⏰ До: {format_ts(sub['expires_at'])}\n"
                    f"🔗 `{get_subscription_link(user_id)}`"
                ),
            )
        else:
            amount = days * PRICE_PER_DAY
            sub = create_subscription(user_id, days)
            record_payment(user_id, days, amount)
            send_message(
                chat_id,
                (
                    f"✅ *Подписка активирована*\n\n"
                    f"📅 {days} дней\n"
                    f"💰 {amount:.2f} RUB\n"
                    f"⏰ До: {format_ts(sub['expires_at'])}\n"
                    f"🔗 `{get_subscription_link(user_id)}`"
                ),
            )

    elif data == "get_link":
        if not is_subscription_active(user_id):
            send_message(chat_id, "❌ Подписка не активна. Используйте `/subscribe`")
            return
        send_message(chat_id, f"🔗 Ваша ссылка:\n\n`{get_subscription_link(user_id)}`")

    elif data == "status":
        status, days = get_subscription_status(user_id)
        if status == "inactive":
            send_message(chat_id, "❌ Нет активной подписки")
        else:
            sub = get_subscription(user_id)
            send_message(chat_id, f"✅ Осталось: {days} дн до {format_ts(sub['expires_at'])}")

    elif data.startswith("pay_sbp_"):
        days = int(data.split("_")[2])
        amount = days * PRICE_PER_DAY
        payment_url = create_payment_yookassa(user_id, days, amount)
        if payment_url:
            send_message(
                chat_id,
                (
                    f"💳 *Платеж через СБП*\n\n"
                    f"[Перейти к оплате]({payment_url})\n\n"
                    f"🔐 Платеж защищен"
                ),
            )
        else:
            send_message(chat_id, "❌ Ошибка инициализации платежа")

    elif data.startswith("pay_free_"):
        days = int(data.split("_")[2])
        sub = create_subscription(user_id, days)
        send_message(
            chat_id,
            (
                f"✅ *Тестовая подписка активирована*\n\n"
                f"📅 {days} дней\n"
                f"🔗 `{get_subscription_link(user_id)}`"
            ),
        )

    elif data.startswith("copy_link_"):
        if is_subscription_active(user_id):
            link = get_subscription_link(user_id)
            send_message(
                chat_id,
                (
                    f"✅ *Ссылка скопирована*\n\n"
                    f"`{link}`\n\n"
                    f"📋 Вставьте эту ссылку в ваш VPN клиент\n"
                    f"в разделе подписок (Subscriptions/Add profile)"
                ),
            )

    elif data.startswith("show_guide_"):
        send_message(
            chat_id,
            (
                "📚 *Как использовать VPN ссылку*\n\n"
                "*🖥️  Компьютер:*\n"
                "1. Скопируйте ссылку из сообщения выше\n"
                "2. Откройте приложение Clash/V2Ray/sing-box\n"
                "3. Нажмите \"Add Profile\" или \"Подписка\"\n"
                "4. Вставьте ссылку\n"
                "5. Нажмите OK - конфиги загрузятся\n\n"
                "*📱 iPhone (Shadowrocket):*\n"
                "1. Откройте Shadowrocket\n"
                "2. Нажмите + в левом верхнем углу\n"
                "3. Выберите \"Subscribe\"\n"
                "4. Вставьте ссылку\n"
                "5. Нажмите Download\n\n"
                "*🤖 Android (Clash):*\n"
                "1. Откройте Clash for Android\n"
                "2. Нажмите Profiles\n"
                "3. Нажмите + (Add)\n"
                "4. Вставьте ссылку\n"
                "5. Нажмите Save\n\n"
                "⏱️ *Совет:* Ссылка автоматически\n"
                "обновляется каждый час"
            ),
        )


def handle_update(update: dict[str, Any]) -> None:
    """Handle Telegram update."""
    if "message" in update and "text" in update["message"]:
        handle_command(update["message"])
    elif "callback_query" in update:
        handle_callback(update["callback_query"])


def poll_telegram() -> None:
    """Poll Telegram for updates."""
    offset = 0
    print("✅ Бот запущен. Ожидание команд...")
    first_try = True
    while True:
        try:
            url = f"{API_URL}/getUpdates?timeout=30&offset={offset + 1}"
            with urllib.request.urlopen(url, timeout=60) as response:
                data = json.loads(response.read().decode("utf-8"))
            if first_try and data.get("ok"):
                print("✅ Соединение с Telegram API установлено\n")
                first_try = False
            if data.get("ok"):
                for update in data.get("result", []):
                    offset = max(offset, update["update_id"])
                    handle_update(update)
            else:
                error = data.get("description", "Unknown error")
                print(f"⚠️  Telegram API error: {error}")
        except Exception as exc:
            if first_try:
                print(f"⚠️  Ошибка подключения к Telegram: {exc}")
                first_try = False
            time.sleep(5)
            continue
        time.sleep(0.5)


class HTTPHandler(BaseHTTPRequestHandler):
    """HTTP handler for VPN subscriptions."""

    def do_GET(self) -> None:
        # Secure personalized links: /sub/{user_id}/{token}/top.txt or legacy /sub/{user_id}/{token}.txt
        if self.path.startswith("/sub/") and self.path.endswith(".txt"):
            request_path = self.path[5:-4]
            if request_path.count("/") == 2 and request_path.endswith("/top"):
                user_id_str, token, _ = request_path.split("/")
            else:
                user_id_str, token = request_path.split("/") if request_path.count("/") == 1 else (None, None)

            if not user_id_str or not token:
                self.send_error(400, "Invalid request")
                return

            try:
                user_id = int(user_id_str)
                verified_user_id = verify_token(token)
                if verified_user_id != user_id:
                    self.send_error(403, "Invalid token")
                    return
            except (ValueError, IndexError):
                self.send_error(400, "Invalid format")
                return

            if not is_subscription_active(user_id):
                content = "# ❌ Subscription expired or inactive\n# 🔄 Renew at Telegram bot\n"
            else:
                try:
                    content = TOP_FILE.read_text(encoding="utf-8", errors="replace")
                    sub = get_subscription(user_id)
                    header = (
                        f"# 🔐 VPN subscription for user {user_id}\n"
                        f"# ⏰ Expires: {format_ts(sub['expires_at'])}\n"
                        f"# 📅 Remaining: {(sub['expires_at'] - now_ts()) // 86400} days\n\n"
                    )
                    content = header + content
                except FileNotFoundError:
                    content = "# ⚠️  VPN configs not ready yet\n"

            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(content.encode("utf-8"))))
            self.end_headers()
            self.wfile.write(content.encode("utf-8"))
            return

        if self.path in {"/", "/health"}:
            body = "VPN Bot v2.0 OK\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body.encode())
            return

        if self.path.startswith("/payment-success"):
            body = "✅ Payment processed. Check Telegram bot for status.\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body.encode())
            return

        self.send_error(404)

    def log_message(self, format: str, *args: Any) -> None:
        pass  # Silent logs


def run_http_server() -> None:
    """Run HTTP server."""
    server = HTTPServer((HTTP_HOST, HTTP_PORT), HTTPHandler)
    if HTTPS_ENABLED:
        if ensure_ssl_certificates():
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(str(SSL_CERT_FILE), str(SSL_KEY_FILE))
            server.socket = context.wrap_socket(server.socket, server_side=True)
            print(f"🔒 HTTPS Server: {HTTP_HOST}:{HTTP_PORT}")
        else:
            print(f"⚠️ HTTPS requested but not available, falling back to HTTP on {HTTP_HOST}:{HTTP_PORT}")
    else:
        print(f"🌐 HTTP Server: {HTTP_HOST}:{HTTP_PORT}")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def periodic_cleanup() -> None:
    """Run cleanup in a background loop."""
    while True:
        cleanup_expired_subscriptions()
        time.sleep(CLEANUP_INTERVAL_SECONDS)


def main() -> None:
    """Main entry point."""
    print("\n" + "=" * 60)
    print("🤖 VPN Telegram Bot v2.0")
    print("=" * 60)
    print(f"🔑 Token: {BOT_TOKEN[:20]}...")
    print(f"🌐 Base URL: {BASE_URL}")
    print(f"💵 Price/day: {PRICE_PER_DAY} RUB")
    print(f"📅 Default: {DEFAULT_SUBSCRIBE_DAYS} days")
    print(f"🔗 Secure tokens: Enabled")
    print(f"💳 SBP Payment: {'Enabled' if PAYMENT_ENABLED else 'Disabled'}")
    print("=" * 60 + "\n")

    init_db()

    cleanup_thread = threading.Thread(target=periodic_cleanup, daemon=True)
    cleanup_thread.start()

    http_thread = threading.Thread(target=run_http_server, daemon=True)
    http_thread.start()

    poll_telegram()


if __name__ == "__main__":
    main()
