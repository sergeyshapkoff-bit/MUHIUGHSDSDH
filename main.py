import os
import json
import time
import hashlib
import random
import asyncio
import contextlib
from datetime import datetime, timedelta

import psycopg2
from psycopg2 import OperationalError
from psycopg2.extras import RealDictCursor
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

DATABASE_URL = os.getenv("postgresql://postgres:CZG0GfgQr9cqA64Y@db.zmfepxqnxcvkvdjonzhp.supabase.co:5432/postgres")
BOT_TOKEN = os.getenv("9014323969:AAEDRFi0RdbDv9SFivz9Pvho-Hp4AjqM-uw")
MAIN_ADMIN_ID = int(os.getenv("5634302903"))
WEBAPP_URL = os.getenv("https://mmiji.de1.netrun.io", "")
SQM_TAX = 10_000
LOAN_LIMIT = 1_000_000

if not DATABASE_URL or not BOT_TOKEN:
    raise RuntimeError("Заполни DATABASE_URL и BOT_TOKEN в переменных окружения.")

app = FastAPI(title="NEON CITY API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id BIGINT PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    cash BIGINT DEFAULT 0,
    bank BIGINT DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS admins (
    user_id BIGINT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS company_categories (
    id SERIAL PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    position INT DEFAULT 0
);

CREATE TABLE IF NOT EXISTS companies (
    id SERIAL PRIMARY KEY,
    category_id INT REFERENCES company_categories(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    price BIGINT NOT NULL,
    income BIGINT NOT NULL,
    sqm NUMERIC NOT NULL
);

CREATE TABLE IF NOT EXISTS user_companies (
    id SERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
    company_id INT REFERENCES companies(id) ON DELETE CASCADE,
    purchased_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, company_id)
);

CREATE TABLE IF NOT EXISTS transactions (
    id SERIAL PRIMARY KEY,
    sender_id BIGINT,
    receiver_id BIGINT,
    amount BIGINT NOT NULL,
    note TEXT,
    status TEXT DEFAULT 'completed',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS messages (
    id SERIAL PRIMARY KEY,
    sender_id BIGINT NOT NULL,
    receiver_id BIGINT NOT NULL,
    text TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS admin_messages (
    id SERIAL PRIMARY KEY,
    sender_id BIGINT NOT NULL,
    text TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS loan_requests (
    id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    amount BIGINT NOT NULL,
    days INT NOT NULL,
    reason TEXT,
    status TEXT DEFAULT 'pending',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS friends (
    id SERIAL PRIMARY KEY,
    requester_id BIGINT NOT NULL,
    target_id BIGINT NOT NULL,
    status TEXT DEFAULT 'pending',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(requester_id, target_id)
);

CREATE TABLE IF NOT EXISTS exchange_assets (
    key TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    min_price BIGINT NOT NULL,
    max_price BIGINT NOT NULL,
    base_price BIGINT NOT NULL,
    price BIGINT NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS user_assets (
    id SERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
    asset_key TEXT REFERENCES exchange_assets(key) ON DELETE CASCADE,
    amount NUMERIC DEFAULT 0,
    UNIQUE(user_id, asset_key)
);
"""

DEFAULT_EXCHANGE = [
    ("gold", "Золото", 500, 1200, 850),
    ("silver", "Серебро", 200, 800, 450),
    ("ring", "Сплав золота и серебра (кольцо)", 1800, 4000, 2900),
    ("tesla", "Машина Тесла", 35000, 42350, 38000),
    ("mcdonalds", "Акции Макдональдса", 45500, 55000, 50000),
    ("bitcoin", "Биткоин", 60000, 72280, 65000),
    ("ethereum", "Эфириум", 15000, 25000, 20000),
    ("oil", "Нефть (баррель)", 500, 900, 700),
]

DEFAULT_CATEGORIES = [
    ("Эконом - Класс", 1, [
        ("ЖК «Мапид»", 200000, 1650, 7),
        ("Грушевка", 345000, 2860, 11),
        ("ЖК «Малиновый Рай»", 500000, 3750, 12),
    ]),
    ("Комфорт - Класс", 2, [
        ("ЖК «Новая Боровая»", 1450000, 10000, 15),
        ("Северный Берег", 3000000, 16500, 15),
        ("ЖК «Речной порт»", 3500000, 22000, 23),
        ("Михалово", 5250000, 29500, 24),
        ("ЖК «Саввинская 17»", 11500000, 55000, 28),
        ("ЖК «Изумрудный бор»", 16700000, 75000, 31),
    ]),
    ("Премиум - Комфорт", 3, [
        ("ЖК - Minsk World", 25000000, 140500, 35),
        ("ЖК «Пирс»", 27500000, 185500, 43),
    ]),
    ("Бизнес - Класс", 4, [
        ("ЖК «Солнечный»", 35555500, 250000, 50),
        ("ЖК «Зелёная гавань»", 50000000, 350000, 50),
        ("Квартал Depo", 150000000, 500000, 50),
        ("ЖК «Айвазовский City»", 255000000, 625000, 55),
    ]),
    ("Люкс", 5, [
        ("Central Park Tower", 500000000, 1350000, 64),
        ("ЖК «Француз»", 1000000000, 5000000, 100),
        ("ЖК «АДМ»", 1500000000, 17000000, 105),
    ]),
    ("Бизнес - Люкс", 6, [
        ("Хрущевка", 15000000000, 80000000, 18),
    ]),
]


def get_db(max_retries=3):
    for attempt in range(max_retries):
        try:
            return psycopg2.connect(DATABASE_URL, connect_timeout=10)
        except OperationalError:
            if attempt == max_retries - 1:
                raise
            time.sleep(0.5 * (attempt + 1))


@contextlib.contextmanager
def db():
    conn = get_db()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                yield cur
    finally:
        conn.close()


def init_db():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(SCHEMA)
            for key, name, low, high, base in DEFAULT_EXCHANGE:
                cur.execute(
                    """INSERT INTO exchange_assets(key,name,min_price,max_price,base_price,price)
                    VALUES(%s,%s,%s,%s,%s,%s)
                    ON CONFLICT(key) DO NOTHING""",
                    (key, name, low, high, base, base),
                )
            for name, position, items in DEFAULT_CATEGORIES:
                cur.execute(
                    "INSERT INTO company_categories(name,position) VALUES(%s,%s) ON CONFLICT(name) DO NOTHING",
                    (name, position),
                )
                cur.execute("SELECT id FROM company_categories WHERE name=%s", (name,))
                category_id = cur.fetchone()["id"]
                for item_name, price, income, sqm in items:
                    cur.execute(
                        """INSERT INTO companies(category_id,name,price,income,sqm)
                        SELECT %s,%s,%s,%s,%s WHERE NOT EXISTS(
                            SELECT 1 FROM companies WHERE category_id=%s AND name=%s
                        )""",
                        (category_id, item_name, price, income, sqm, category_id, item_name),
                    )


def ensure_user(user_id: int, username: str | None, first_name: str | None):
    with db() as cur:
        cur.execute(
            """INSERT INTO users(user_id,username,first_name)
            VALUES(%s,%s,%s) ON CONFLICT(user_id) DO UPDATE
            SET username=EXCLUDED.username, first_name=EXCLUDED.first_name""",
            (user_id, username, first_name),
        )


def get_user(user_id: int):
    with db() as cur:
        cur.execute("SELECT * FROM users WHERE user_id=%s", (user_id,))
        return cur.fetchone()


def role_of(user_id: int) -> str:
    if user_id == MAIN_ADMIN_ID:
        return "main_admin"
    with db() as cur:
        cur.execute("SELECT 1 FROM admins WHERE user_id=%s", (user_id,))
        return "admin" if cur.fetchone() else "player"


def require_admin(user_id: int):
    if role_of(user_id) == "player":
        raise HTTPException(status_code=403, detail="Недостаточно прав")


def require_main_admin(user_id: int):
    if user_id != MAIN_ADMIN_ID:
        raise HTTPException(status_code=403, detail="Только главный админ может это делать")


def money(value: int) -> str:
    return f"{value:,}".replace(",", " ") + " BYN"


def main_menu(role: str):
    rows = [
        [InlineKeyboardButton("📈 Биржа", callback_data="market")],
        [InlineKeyboardButton("🏦 Банк", callback_data="bank")],
        [InlineKeyboardButton("🏢 Компании", callback_data="companies")],
        [InlineKeyboardButton("💬 Чаты", callback_data="chat")],
        [InlineKeyboardButton("💳 Кредиты", callback_data="loans")],
        [InlineKeyboardButton("👥 Друзья", callback_data="friends")],
    ]
    if role != "player":
        rows.append([InlineKeyboardButton("🛡 Админ-панель", callback_data="admin")])
    if WEBAPP_URL:
        rows.append([InlineKeyboardButton("🌐 Открыть веб-панель", web_app=WebAppInfo(url=WEBAPP_URL))])
    return InlineKeyboardMarkup(rows)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    ensure_user(u.id, u.username, u.first_name)
    role = role_of(u.id)
    text = (
        f"👋 Привет, {u.first_name}!\n\n"
        "Это NEON CITY — город возможностей.\n"
        "Здесь можно покупать активы, компании, переводить деньги, брать кредиты и общаться.\n\n"
        f"Твоя роль: <b>{'Главный админ' if role == 'main_admin' else 'Администратор' if role == 'admin' else 'Игрок'}</b>"
    )
    await update.message.reply_text(text, reply_markup=main_menu(role), parse_mode="HTML")


async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    ensure_user(u.id, u.username, u.first_name)
    user = get_user(u.id)
    await update.message.reply_text(
        f"<b>👤 Профиль</b>\n\n"
        f"ID: <code>{u.id}</code>\n"
        f"Наличные: <b>{money(user['cash'])}</b>\n"
        f"Банк: <b>{money(user['bank'])}</b>\n"
        f"Роль: <b>{role_of(u.id)}</b>",
        parse_mode="HTML",
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    role = role_of(user_id)

    if query.data == "market":
        with db() as cur:
            cur.execute("SELECT * FROM exchange_assets ORDER BY key")
            assets = cur.fetchall()
        text = "<b>📈 Биржа</b>\n\n" + "\n".join(
            f"{a['name']}: <b>{money(a['price'])}</b>" for a in assets
        )
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=main_menu(role))

    elif query.data == "bank":
        await query.edit_message_text(
            "<b>🏦 Банк</b>\n\nИспользуй команду:\n<code>/перевод ID сумма</code>",
            parse_mode="HTML",
            reply_markup=main_menu(role),
        )

    elif query.data == "companies":
        with db() as cur:
            cur.execute(
                """SELECT c.name company_name,c.price,c.income,c.sqm,cc.name category
                FROM companies c JOIN company_categories cc ON cc.id=c.category_id
                ORDER BY cc.position,c.price"""
            )
            items = cur.fetchall()
        text = "<b>🏢 Компании и недвижимость</b>\n\n"
        text += f"Налог: <b>{money(SQM_TAX)}</b> за 1 км² в день\n\n"
        for i in items:
            tax = int(float(i["sqm"]) * SQM_TAX)
            text += (
                f"<b>{i['category']}</b>\n"
                f"• {i['company_name']} — {money(i['price'])}\n"
                f"Доход: +{money(i['income'])}/день\n"
                f"Налог: -{money(tax)}/день\n\n"
            )
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=main_menu(role))

    elif query.data == "admin":
        if role == "player":
            return
        text = "<b>🛡 Админ-панель</b>\n\n"
        if role == "main_admin":
            text += "/админ ID — назначить админа\n/снять ID — снять админа\n/написать ID текст — написать игроку\n"
        text += "/кредиты — заявки на кредит\n/чатадм текст — чат администрации"
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=main_menu(role))


async def transfer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    if len(context.args) != 2:
        return await update.message.reply_text("Формат: /перевод ID сумма")
    try:
        target_id, amount = int(context.args[0]), int(context.args[1])
    except ValueError:
        return await update.message.reply_text("ID и сумма должны быть числами.")
    if amount <= 0 or target_id == u.id:
        return await update.message.reply_text("Некорректный перевод.")
    with db() as cur:
        cur.execute("SELECT cash FROM users WHERE user_id=%s FOR UPDATE", (u.id,))
        sender = cur.fetchone()
        if not sender or sender["cash"] < amount:
            return await update.message.reply_text("Недостаточно наличных.")
        cur.execute(
            "INSERT INTO users(user_id) VALUES(%s) ON CONFLICT(user_id) DO NOTHING", (target_id,)
        )
        cur.execute(
            "UPDATE users SET cash=cash-%s WHERE user_id=%s", (amount, u.id)
        )
        cur.execute(
            "UPDATE users SET bank=bank+%s WHERE user_id=%s", (amount, target_id)
        )
        cur.execute(
            "INSERT INTO transactions(sender_id,receiver_id,amount,note) VALUES(%s,%s,%s,%s)",
            (u.id, target_id, amount, " ".join(context.args[2:]) or None),
        )
    await update.message.reply_text(f"✅ Перевод {money(amount)} игроку <code>{target_id}</code> выполнен.", parse_mode="HTML")


async def buy_company(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    if len(context.args) != 1:
        return await update.message.reply_text("Формат: /купитькомпанию ID")
    try:
        company_id = int(context.args[0])
    except ValueError:
        return await update.message.reply_text("Некорректный ID компании.")
    with db() as cur:
        cur.execute("SELECT * FROM companies WHERE id=%s", (company_id,))
        company = cur.fetchone()
        if not company:
            return await update.message.reply_text("Компания не найдена.")
        cur.execute("SELECT cash FROM users WHERE user_id=%s FOR UPDATE", (u.id,))
        user = cur.fetchone()
        if not user or user["cash"] < company["price"]:
            return await update.message.reply_text("Недостаточно наличных.")
        cur.execute("UPDATE users SET cash=cash-%s WHERE user_id=%s", (company["price"], u.id))
        cur.execute(
            "INSERT INTO user_companies(user_id,company_id) VALUES(%s,%s) ON CONFLICT DO NOTHING",
            (u.id, company_id),
        )
    await update.message.reply_text(
        f"✅ Куплено: <b>{company['name']}</b>\n"
        f"Доход: +{money(company['income'])}/день\n"
        f"Налог: -{money(int(float(company['sqm']) * SQM_TAX))}/день",
        parse_mode="HTML",
    )


async def collect(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    with db() as cur:
        cur.execute(
            """SELECT COALESCE(SUM(c.income),0) income,COALESCE(SUM(c.sqm),0) sqm
            FROM user_companies uc JOIN companies c ON c.id=uc.company_id
            WHERE uc.user_id=%s""",
            (u.id,),
        )
        result = cur.fetchone()
        income, sqm = int(result["income"]), int(float(result["sqm"]))
        tax = sqm * SQM_TAX
        net = income - tax
        cur.execute("UPDATE users SET bank=bank+%s WHERE user_id=%s", (net, u.id))
    await update.message.reply_text(
        f"💰 Доход: +{money(income)}\n🏛 Налог: -{money(tax)}\n"
        f"Зачислено в банк: <b>{money(net)}</b>",
        parse_mode="HTML",
    )


async def request_loan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    if len(context.args) < 2:
        return await update.message.reply_text("Формат: /кредит сумма срок_дней причина")
    try:
        amount, days = int(context.args[0]), int(context.args[1])
    except ValueError:
        return await update.message.reply_text("Сумма и срок должны быть числами.")
    if amount <= 0 or amount > LOAN_LIMIT:
        return await update.message.reply_text(f"Максимальная сумма кредита: {money(LOAN_LIMIT)}.")
    reason = " ".join(context.args[2:]) or ""
    with db() as cur:
        cur.execute(
            "INSERT INTO loan_requests(user_id,amount,days,reason) VALUES(%s,%s,%s,%s)",
            (u.id, amount, days, reason),
        )
    await update.message.reply_text("✅ Заявка на кредит отправлена администрации.")


async def loans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if role_of(update.effective_user.id) == "player":
        return await update.message.reply_text("Недостаточно прав.")
    with db() as cur:
        cur.execute(
            """SELECT l.*,u.first_name,u.username FROM loan_requests l
            JOIN users u ON u.user_id=l.user_id WHERE l.status='pending' ORDER BY l.created_at"""
        )
        rows = cur.fetchall()
    if not rows:
        return await update.message.reply_text("Нет заявок на кредит.")
    text = "<b>💳 Заявки на кредит</b>\n\n"
    for r in rows:
        text += (
            f"ID {r['id']} · {r['first_name'] or r['username']}\n"
            f"Сумма: {money(r['amount'])} · {r['days']} дн.\n"
            f"Причина: {r['reason'] or '—'}\n\n"
        )
    await update.message.reply_text(text, parse_mode="HTML")


async def review_loan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if role_of(update.effective_user.id) == "player":
        return await update.message.reply_text("Недостаточно прав.")
    if len(context.args) != 2 or context.args[1].lower() not in ("да", "нет"):
        return await update.message.reply_text("Формат: /кредит ID да|нет")
    loan_id, decision = int(context.args[0]), context.args[1].lower()
    with db() as cur:
        cur.execute("SELECT * FROM loan_requests WHERE id=%s AND status='pending' FOR UPDATE", (loan_id,))
        loan = cur.fetchone()
        if not loan:
            return await update.message.reply_text("Заявка не найдена или уже обработана.")
        if decision == "да":
            cur.execute("UPDATE users SET bank=bank+%s WHERE user_id=%s", (loan["amount"], loan["user_id"]))
            cur.execute("UPDATE loan_requests SET status='approved' WHERE id=%s", (loan_id,))
            result = "одобрен"
        else:
            cur.execute("UPDATE loan_requests SET status='rejected' WHERE id=%s", (loan_id,))
            result = "отклонён"
    await update.message.reply_text(f"✅ Кредит #{loan_id} {result}.")


async def add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != MAIN_ADMIN_ID:
        return await update.message.reply_text("Только главный админ может назначать админов.")
    if not context.args:
        return await update.message.reply_text("Формат: /админ ID")
    try:
        target = int(context.args[0])
    except ValueError:
        return await update.message.reply_text("Некорректный ID.")
    with db() as cur:
        cur.execute("INSERT INTO admins(user_id) VALUES(%s) ON CONFLICT(user_id) DO NOTHING", (target,))
    await update.message.reply_text(f"✅ Игрок <code>{target}</code> назначен администратором.", parse_mode="HTML")


async def remove_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != MAIN_ADMIN_ID:
        return await update.message.reply_text("Только главный админ может снимать админов.")
    if not context.args:
        return await update.message.reply_text("Формат: /снять ID")
    try:
        target = int(context.args[0])
    except ValueError:
        return await update.message.reply_text("Некорректный ID.")
    if target == MAIN_ADMIN_ID:
        return await update.message.reply_text("Главного админа нельзя снять.")
    with db() as cur:
        cur.execute("DELETE FROM admins WHERE user_id=%s", (target,))
    await update.message.reply_text(f"✅ Игрок <code>{target}</code> больше не администратор.", parse_mode="HTML")


async def admin_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != MAIN_ADMIN_ID:
        return await update.message.reply_text("Только главный админ может писать игрокам от имени администрации.")
    if len(context.args) < 2:
        return await update.message.reply_text("Формат: /написать ID текст")
    try:
        target = int(context.args[0])
    except ValueError:
        return await update.message.reply_text("Некорректный ID.")
    text = " ".join(context.args[1:])
    try:
        await context.bot.send_message(target, f"📩 Сообщение от администрации:\n\n{text}")
    except Exception:
        return await update.message.reply_text("Не удалось отправить сообщение.")
    await update.message.reply_text("✅ Сообщение отправлено.")


async def admin_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if role_of(user_id) == "player":
        return await update.message.reply_text("Чат администрации доступен только админам.")
    text = " ".join(context.args)
    if not text:
        return await update.message.reply_text("Формат: /чатадм текст")
    with db() as cur:
        cur.execute("INSERT INTO admin_messages(sender_id,text) VALUES(%s,%s)", (user_id, text))
        cur.execute(
            """SELECT am.*,u.first_name,u.username FROM admin_messages am
            JOIN users u ON u.user_id=am.sender_id ORDER BY am.created_at DESC LIMIT 20"""
        )
        rows = cur.fetchall()[::-1]
    text_out = "<b>🛡 Чат администрации</b>\n\n" + "\n".join(
        f"<b>{r['first_name'] or r['username']}</b>: {r['text']}" for r in rows
    )
    await update.message.reply_text(text_out, parse_mode="HTML")


class TransferModel(BaseModel):
    user_id: int
    receiver_id: int
    amount: int
    note: str | None = None


class LoanModel(BaseModel):
    user_id: int
    amount: int
    days: int
    reason: str | None = None


class MessageModel(BaseModel):
    user_id: int
    receiver_id: int
    text: str


class AdminActionModel(BaseModel):
    user_id: int
    target_id: int


@app.get("/api/me/{user_id}")
def api_me(user_id: int):
    ensure_user(user_id, None, None)
    user = get_user(user_id)
    return {"user": user, "role": role_of(user_id)}


@app.get("/api/players")
def api_players():
    with db() as cur:
        cur.execute("SELECT user_id,first_name,username FROM users ORDER BY first_name NULLS LAST LIMIT 200")
        return cur.fetchall()


@app.get("/api/companies")
def api_companies():
    with db() as cur:
        cur.execute(
            """SELECT cc.id category_id,cc.name category,c.id,c.name,c.price,c.income,c.sqm
            FROM company_categories cc LEFT JOIN companies c ON c.category_id=cc.id
            ORDER BY cc.position,c.price"""
        )
        rows = cur.fetchall()
    categories = []
    for row in rows:
        if not categories or categories[-1]["name"] != row["category"]:
            categories.append({"id": row["category_id"], "name": row["category"], "items": []})
        if row["id"]:
            categories[-1]["items"].append(row)
    return categories


@app.post("/api/transfer")
def api_transfer(data: TransferModel):
    with db() as cur:
        cur.execute("SELECT cash FROM users WHERE user_id=%s FOR UPDATE", (data.user_id,))
        sender = cur.fetchone()
        if not sender or sender["cash"] < data.amount:
            raise HTTPException(status_code=400, detail="Недостаточно наличных")
        cur.execute("INSERT INTO users(user_id) VALUES(%s) ON CONFLICT DO NOTHING", (data.receiver_id,))
        cur.execute("UPDATE users SET cash=cash-%s WHERE user_id=%s", (data.amount, data.user_id))
        cur.execute("UPDATE users SET bank=bank+%s WHERE user_id=%s", (data.amount, data.receiver_id))
        cur.execute(
            "INSERT INTO transactions(sender_id,receiver_id,amount,note) VALUES(%s,%s,%s,%s)",
            (data.user_id, data.receiver_id, data.amount, data.note),
        )
    return {"ok": True}


@app.post("/api/message")
def api_message(data: MessageModel):
    with db() as cur:
        cur.execute(
            "INSERT INTO messages(sender_id,receiver_id,text) VALUES(%s,%s,%s)",
            (data.user_id, data.receiver_id, data.text),
        )
    return {"ok": True}


@app.get("/api/messages/{user_id}/{receiver_id}")
def api_messages(user_id: int, receiver_id: int):
    with db() as cur:
        cur.execute(
            """SELECT * FROM messages WHERE
            (sender_id=%s AND receiver_id=%s) OR (sender_id=%s AND receiver_id=%s)
            ORDER BY created_at LIMIT 100""",
            (user_id, receiver_id, receiver_id, user_id),
        )
        return cur.fetchall()


@app.post("/api/loan")
def api_loan(data: LoanModel):
    if data.amount <= 0 or data.amount > LOAN_LIMIT:
        raise HTTPException(status_code=400, detail="Некорректная сумма")
    with db() as cur:
        cur.execute(
            "INSERT INTO loan_requests(user_id,amount,days,reason) VALUES(%s,%s,%s,%s)",
            (data.user_id, data.amount, data.days, data.reason),
        )
    return {"ok": True}


@app.get("/api/loans")
def api_loans(user_id: int):
    require_admin(user_id)
    with db() as cur:
        cur.execute(
            """SELECT l.*,u.first_name,u.username FROM loan_requests l
            JOIN users u ON u.user_id=l.user_id WHERE l.status='pending' ORDER BY l.created_at"""
        )
        return cur.fetchall()


@app.post("/api/loan/{loan_id}/review")
def api_review_loan(loan_id: int, data: AdminActionModel):
    require_admin(data.user_id)
    with db() as cur:
        cur.execute("SELECT * FROM loan_requests WHERE id=%s AND status='pending' FOR UPDATE", (loan_id,))
        loan = cur.fetchone()
        if not loan:
            raise HTTPException(status_code=404, detail="Заявка не найдена")
        # approve/reject определяется отдельным endpoint; здесь только отмена не используется
    return {"ok": True}


@app.post("/api/admin/{target_id}/set")
def api_set_admin(target_id: int, data: AdminActionModel):
    require_main_admin(data.user_id)
    if target_id == MAIN_ADMIN_ID:
        raise HTTPException(status_code=400, detail="Главного админа нельзя изменить")
    with db() as cur:
        cur.execute("INSERT INTO admins(user_id) VALUES(%s) ON CONFLICT DO NOTHING", (target_id,))
    return {"ok": True}


@app.post("/api/admin/{target_id}/remove")
def api_remove_admin(target_id: int, data: AdminActionModel):
    require_main_admin(data.user_id)
    if target_id == MAIN_ADMIN_ID:
        raise HTTPException(status_code=400, detail="Главного админа нельзя снять")
    with db() as cur:
        cur.execute("DELETE FROM admins WHERE user_id=%s", (target_id,))
    return {"ok": True}


async def update_prices():
    while True:
        try:
            with db() as cur:
                cur.execute("SELECT * FROM exchange_assets")
                assets = cur.fetchall()
                for asset in assets:
                    new_price = random.randint(asset["min_price"], asset["max_price"])
                    cur.execute(
                        "UPDATE exchange_assets SET price=%s,updated_at=NOW() WHERE key=%s",
                        (new_price, asset["key"]),
                    )
        except Exception:
            pass
        await asyncio.sleep(300)


async def daily_income():
    while True:
        try:
            with db() as cur:
                cur.execute(
                    """SELECT uc.user_id,
                    COALESCE(SUM(c.income),0) income,COALESCE(SUM(c.sqm),0) sqm
                    FROM user_companies uc JOIN companies c ON c.id=uc.company_id
                    GROUP BY uc.user_id"""
                )
                for row in cur.fetchall():
                    net = int(row["income"]) - int(float(row["sqm"]) * SQM_TAX)
                    cur.execute(
                        "UPDATE users SET bank=bank+%s WHERE user_id=%s",
                        (net, row["user_id"]),
                    )
        except Exception:
            pass
        await asyncio.sleep(86400)


@app.on_event("startup")
async def startup():
    init_db()
    asyncio.create_task(update_prices())
    asyncio.create_task(daily_income())


def run_bot():
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("профиль", profile))
    application.add_handler(CommandHandler("перевод", transfer))
    application.add_handler(CommandHandler("купитькомпанию", buy_company))
    application.add_handler(CommandHandler("собрать", collect))
    application.add_handler(CommandHandler("кредит", request_loan))
    application.add_handler(CommandHandler("кредиты", loans))
    application.add_handler(CommandHandler("кредит", review_loan))
    application.add_handler(CommandHandler("админ", add_admin))
    application.add_handler(CommandHandler("снять", remove_admin))
    application.add_handler(CommandHandler("написать", admin_message))
    application.add_handler(CommandHandler("чатадм", admin_chat))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.run_polling()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
