#!/usr/bin/env python3
"""VPN Telegram Bot with SQLite database and payment tracking."""
from __future__ import annotations

import json
import os
import sqlite3
import ssl
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

# Fix SSL certificate issues on macOS
import ssl
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
                    os.environ[key] = val

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


def init_db() -> None:
    """Initialize SQLite database."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
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
    conn.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            days INTEGER NOT NULL,
            status TEXT DEFAULT 'pending',
            payment_id TEXT,
            created_at INTEGER NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        )
    """)
    conn.commit()
    conn.close()


def now_ts() -> int:
    return int(time.time())


def format_ts(ts: int) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


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


def record_payment(user_id: int, days: int, amount: float) -> None:
    """Record payment."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO payments (user_id, amount, days, status, created_at) VALUES (?, ?, ?, ?, ?)",
        (user_id, amount, days, "completed", now_ts()),
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


def get_subscription_link(user_id: int) -> str:
    """Get subscription link for user."""
    return f"{BASE_URL}/sub/{user_id}.txt"


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
        send_message(
            chat_id,
            (
                "🌐 *VPN Subscription Bot*\n\n"
                "Команды:\n"
                "• `/subscribe [дней]` — активировать подписку\n"
                "• `/link` — получить ссылку VPN\n"
                "• `/status` — состояние подписки\n"
                "• `/price [дней]` — стоимость подписки\n"
                "• `/cancel` — отменить подписку\n"
                "• `/help` — справка\n\n"
                "Пример: `/subscribe 7` — подписка на 7 дней"
            ),
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

        # Check if user is admin
        is_admin = user_id in ADMIN_IDS
        if is_admin:
            # Admins get 365 free days
            days = 365
            amount = 0
            sub = create_subscription(user_id, days)
            record_payment(user_id, days, amount)
            send_message(
                chat_id,
                (
                    f"✅ *Администратор подписка активирована*\n\n"
                    f"📅 Дней: {days} (бесплатно)\n"
                    f"⏰ До: {format_ts(sub['expires_at'])}\n\n"
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
                    f"📅 Дней: {days}\n"
                    f"💰 Сумма: ${amount:.2f}\n"
                    f"⏰ До: {format_ts(sub['expires_at'])}\n\n"
                    f"🔗 `{get_subscription_link(user_id)}`"
                ),
            )
        return

    if cmd == "/link":
        if not is_subscription_active(user_id):
            send_message(chat_id, "❌ Подписка не активна. Используйте `/subscribe`")
            return
        send_message(chat_id, f"🔗 Ваша VPN ссылка:\n\n`{get_subscription_link(user_id)}`")
        return

    if cmd == "/status":
        status, days = get_subscription_status(user_id)
        if status == "inactive":
            send_message(chat_id, "❌ Нет активной подписки")
        else:
            sub = get_subscription(user_id)
            send_message(
                chat_id,
                (
                    f"✅ *Подписка активна*\n\n"
                    f"📅 Осталось дней: {days}\n"
                    f"⏰ До: {format_ts(sub['expires_at'])}\n"
                    f"🔗 {get_subscription_link(user_id)}"
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
        send_message(chat_id, f"💰 *Стоимость подписки*\n\n{days} дней = **${amount:.2f}**")
        return

    if cmd == "/cancel":
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            "UPDATE subscriptions SET status = 'cancelled' WHERE user_id = ? AND status = 'active'",
            (user_id,),
        )
        conn.commit()
        conn.close()
        send_message(chat_id, "❌ Подписка отменена")
        return

    send_message(chat_id, "❓ Неизвестная команда. Используйте `/help`")


def handle_update(update: dict[str, Any]) -> None:
    """Handle Telegram update."""
    if "message" in update and "text" in update["message"]:
        handle_command(update["message"])


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
                print("   Проверьте VPN_TELEGRAM_BOT_TOKEN в файле .env\n")
                first_try = False
            time.sleep(5)
            continue
        time.sleep(0.5)


class HTTPHandler(BaseHTTPRequestHandler):
    """HTTP handler for VPN subscriptions."""

    def do_GET(self) -> None:
        if self.path.startswith("/sub/") and self.path.endswith(".txt"):
            user_id_str = self.path[5:-4]
            try:
                user_id = int(user_id_str)
            except ValueError:
                self.send_error(400, "Invalid user ID")
                return

            if not is_subscription_active(user_id):
                content = "# Subscription expired or inactive\n# Renew at Telegram bot\n"
            else:
                try:
                    content = TOP_FILE.read_text(encoding="utf-8", errors="replace")
                    sub = get_subscription(user_id)
                    header = (
                        f"# VPN subscription for user {user_id}\n"
                        f"# Expires: {format_ts(sub['expires_at'])}\n"
                        f"# Remaining: {(sub['expires_at'] - now_ts()) // 86400} days\n\n"
                    )
                    content = header + content
                except FileNotFoundError:
                    content = "# VPN configs not ready yet\n"

            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(content.encode("utf-8"))))
            self.end_headers()
            self.wfile.write(content.encode("utf-8"))
            return

        if self.path in {"/", "/health"}:
            body = "VPN Bot OK\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body.encode())
            return

        self.send_error(404)

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[HTTP] {format % args}")


def run_http_server() -> None:
    """Run HTTP server."""
    server = HTTPServer((HTTP_HOST, HTTP_PORT), HTTPHandler)
    print(f"🌐 HTTP на {HTTP_HOST}:{HTTP_PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main() -> None:
    """Main entry point."""
    print("\n" + "=" * 60)
    print("🤖 VPN Telegram Bot")
    print("=" * 60)
    print(f"Token: {BOT_TOKEN[:20]}...")
    print(f"Base URL: {BASE_URL}")
    print(f"Price/day: ${PRICE_PER_DAY}")
    print(f"Default days: {DEFAULT_SUBSCRIBE_DAYS}")
    print("=" * 60 + "\n")

    init_db()
    http_thread = threading.Thread(target=run_http_server, daemon=True)
    http_thread.start()
    poll_telegram()


if __name__ == "__main__":
    main()
