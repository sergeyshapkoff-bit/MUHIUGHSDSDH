import os
from contextlib import asynccontextmanager

import psycopg2
from psycopg2.extras import RealDictCursor
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

DATABASE_URL = os.getenv("DATABASE_URL")
BOT_TOKEN = os.getenv("BOT_TOKEN")
MAIN_ADMIN_ID = int(os.getenv("MAIN_ADMIN_ID", "5634302903"))
WEBAPP_URL = os.getenv("WEBAPP_URL", "")

SQM_TAX = 100
LOAN_LIMIT = 1_000_000
LOAN_RATE = 0.10

if not DATABASE_URL or not BOT_TOKEN:
    raise RuntimeError("Заполни DATABASE_URL и BOT_TOKEN в переменных окружения.")

app = FastAPI(title="NEON CITY")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    telegram_id BIGINT PRIMARY KEY,
    nickname TEXT UNIQUE NOT NULL,
    first_name TEXT,
    balance NUMERIC(18,2) NOT NULL DEFAULT 0,
    bank NUMERIC(18,2) NOT NULL DEFAULT 0,
    credit NUMERIC(18,2) NOT NULL DEFAULT 0,
    sqm INTEGER NOT NULL DEFAULT 0,
    card_color TEXT NOT NULL DEFAULT '#7c3aed',
    card_background TEXT NOT NULL DEFAULT '#111827',
    card_image TEXT,
    is_admin BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS friends (
    id BIGSERIAL PRIMARY KEY,
    owner_id BIGINT NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
    friend_id BIGINT NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(owner_id, friend_id)
);

CREATE TABLE IF NOT EXISTS transfers (
    id BIGSERIAL PRIMARY KEY,
    sender_id BIGINT NOT NULL REFERENCES users(telegram_id),
    receiver_id BIGINT NOT NULL REFERENCES users(telegram_id),
    amount NUMERIC(18,2) NOT NULL CHECK (amount > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS loans (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(telegram_id),
    amount NUMERIC(18,2) NOT NULL CHECK (amount > 0),
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS companies (
    id BIGSERIAL PRIMARY KEY,
    category TEXT NOT NULL,
    name TEXT NOT NULL,
    price NUMERIC(18,2) NOT NULL CHECK (price >= 0),
    daily_income NUMERIC(18,2) NOT NULL CHECK (daily_income >= 0),
    sqm INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS user_companies (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
    company_id BIGINT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    purchased_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(user_id, company_id)
);

CREATE TABLE IF NOT EXISTS exchange_items (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    base_price NUMERIC(18,2) NOT NULL,
    min_price NUMERIC(18,2) NOT NULL,
    max_price NUMERIC(18,2) NOT NULL,
    current_price NUMERIC(18,2) NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS exchange_holdings (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
    item_id BIGINT NOT NULL REFERENCES exchange_items(id) ON DELETE CASCADE,
    quantity INTEGER NOT NULL DEFAULT 0 CHECK (quantity >= 0),
    UNIQUE(user_id, item_id)
);

CREATE TABLE IF NOT EXISTS messages (
    id BIGSERIAL PRIMARY KEY,
    sender_id BIGINT NOT NULL REFERENCES users(telegram_id),
    receiver_id BIGINT NOT NULL REFERENCES users(telegram_id),
    text TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_users_balance
ON users(balance DESC);

CREATE INDEX IF NOT EXISTS idx_messages_receiver
ON messages(receiver_id, created_at DESC);
"""

DEFAULT_COMPANIES = [
    ("Магазин", "Киоск", 10_000, 300, 1),
    ("Магазин", "Мини-маркет", 50_000, 1_200, 3),
    ("Магазин", "Супермаркет", 250_000, 5_000, 10),
    ("Кафе", "Кофейня", 100_000, 2_000, 5),
    ("Кафе", "Ресторан", 500_000, 9_000, 15),
    ("Авто", "Автомойка", 150_000, 3_000, 6),
    ("Авто", "Автосалон", 1_000_000, 18_000, 25),
    ("Недвижимость", "Квартира", 300_000, 4_000, 20),
    ("Недвижимость", "Офис", 800_000, 12_000, 40),
    ("Недвижимость", "Торговый центр", 5_000_000, 70_000, 150),
]

DEFAULT_EXCHANGE = [
    ("Gold", 5_000, 3_000, 8_000),
    ("Silver", 2_500, 1_500, 4_000),
    ("Ring", 8_000, 5_000, 12_000),
    ("Tesla", 100_000, 70_000, 150_000),
    ("McDonald's", 250_000, 180_000, 350_000),
    ("Bitcoin", 500_000, 300_000, 900_000),
    ("Ethereum", 300_000, 180_000, 550_000),
    ("Oil", 150_000, 100_000, 250_000),
]


def get_db():
    return psycopg2.connect(DATABASE_URL, connect_timeout=10)


def db_execute(query, params=(), fetch=False):
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, params)
            rows = cur.fetchall() if fetch else None
        conn.commit()
    return rows


def get_user(telegram_id):
    rows = db_execute(
        "SELECT * FROM users WHERE telegram_id = %s",
        (telegram_id,),
        fetch=True,
    )
    return rows[0] if rows else None


def get_user_by_nickname(nickname):
    rows = db_execute(
        "SELECT * FROM users WHERE LOWER(nickname) = LOWER(%s)",
        (nickname,),
        fetch=True,
    )
    return rows[0] if rows else None


def ensure_user(telegram_id, nickname, first_name="Игрок"):
    nickname = (nickname or "").strip()

    if not nickname:
        nickname = f"player{telegram_id}"

    existing = get_user_by_nickname(nickname)

    if existing and existing["telegram_id"] != telegram_id:
        nickname = f"player{telegram_id}"

    db_execute(
        """
        INSERT INTO users (telegram_id, nickname, first_name)
        VALUES (%s, %s, %s)
        ON CONFLICT (telegram_id) DO UPDATE
        SET nickname = EXCLUDED.nickname,
            first_name = EXCLUDED.first_name
        """,
        (telegram_id, nickname, first_name),
    )

    if telegram_id == MAIN_ADMIN_ID:
        db_execute(
            "UPDATE users SET is_admin = TRUE WHERE telegram_id = %s",
            (telegram_id,),
        )

    return get_user(telegram_id)


def is_admin(telegram_id):
    user = get_user(telegram_id)
    return bool(user and user["is_admin"])


def money(value):
    return f"{float(value):,.2f}".replace(",", " ")


def main_keyboard(telegram_id):
    if WEBAPP_URL:
        site_button = [
            InlineKeyboardButton(
                "🌐 Открыть NEON CITY",
                web_app=WebAppInfo(url=WEBAPP_URL),
            )
        ]
    else:
        site_button = [
            InlineKeyboardButton(
                "🌐 Сайт недоступен",
                callback_data="no_site",
            )
        ]

    buttons = [
        site_button,
        [InlineKeyboardButton("👤 Профиль", callback_data="profile")],
        [InlineKeyboardButton("🏆 Лидеры", callback_data="leaderboard")],
        [InlineKeyboardButton("🏦 Банк", callback_data="bank")],
        [InlineKeyboardButton("📈 Биржа", callback_data="exchange")],
        [InlineKeyboardButton("🏢 Бизнес", callback_data="companies")],
        [InlineKeyboardButton("💸 Перевод", callback_data="transfer")],
        [InlineKeyboardButton("👥 Игроки", callback_data="players")],
        [InlineKeyboardButton("💬 Сообщения", callback_data="messages")],
        [InlineKeyboardButton("💳 Кредит", callback_data="loans")],
        [InlineKeyboardButton("🤝 Друзья", callback_data="friends")],
    ]

    if is_admin(telegram_id):
        buttons.append(
            [InlineKeyboardButton("🛡 Админ-панель", callback_data="admin")]
        )

    return InlineKeyboardMarkup(buttons)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    nickname = update.effective_user.username or f"player{telegram_id}"
    first_name = update.effective_user.first_name or "Игрок"

    user = ensure_user(telegram_id, nickname, first_name)

    text = (
        f"🌆 <b>NEON CITY</b>\n\n"
        f"Привет, <b>{user['nickname']}</b>!\n\n"
        f"💰 Баланс: <b>{money(user['balance'])} BYN</b>\n"
        f"🏦 Банк: <b>{money(user['bank'])} BYN</b>\n"
        f"🌍 Земля: <b>{user['sqm']} км²</b>"
    )

    await update.message.reply_text(
        text,
        reply_markup=main_keyboard(telegram_id),
        parse_mode="HTML",
    )


async def profile_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = get_user(query.from_user.id)

    if not user:
        await query.edit_message_text("Сначала нажми /start.")
        return

    text = (
        f"👤 <b>Профиль</b>\n\n"
        f"Ник: <b>{user['nickname']}</b>\n"
        f"Telegram ID: <code>{user['telegram_id']}</code>\n\n"
        f"💰 Наличные: <b>{money(user['balance'])} BYN</b>\n"
        f"🏦 Банк: <b>{money(user['bank'])} BYN</b>\n"
        f"💳 Кредит: <b>{money(user['credit'])} BYN</b>\n"
        f"🌍 Земля: <b>{user['sqm']} км²</b>"
    )

    await query.edit_message_text(
        text,
        reply_markup=main_keyboard(user["telegram_id"]),
        parse_mode="HTML",
    )


async def leaderboard_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    players = db_execute(
        """
        SELECT nickname, balance, sqm
        FROM users
        ORDER BY balance DESC, sqm DESC
        LIMIT 10
        """,
        fetch=True,
    )

    text = "🏆 <b>Таблица лидеров</b>\n\n"

    if not players:
        text += "Игроков пока нет."
    else:
        for index, player in enumerate(players, start=1):
            text += (
                f"{index}. <b>{player['nickname']}</b>\n"
                f"💰 {money(player['balance'])} BYN\n"
                f"🌍 {player['sqm']} км²\n\n"
            )

    await query.edit_message_text(
        text,
        reply_markup=main_keyboard(query.from_user.id),
        parse_mode="HTML",
    )


async def bank_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = get_user(query.from_user.id)

    if not user:
        await query.edit_message_text("Сначала нажми /start.")
        return

    text = (
        f"🏦 <b>NEON BANK</b>\n\n"
        f"💰 Наличные: <b>{money(user['balance'])} BYN</b>\n"
        f"💳 На карте: <b>{money(user['bank'])} BYN</b>\n\n"
        f"Команды:\n"
        f"<code>/deposit СУММА</code>\n"
        f"<code>/withdraw СУММА</code>"
    )

    await query.edit_message_text(
        text,
        reply_markup=main_keyboard(user["telegram_id"]),
        parse_mode="HTML",
    )


async def deposit_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Формат: <code>/deposit СУММА</code>",
            parse_mode="HTML",
        )
        return

    try:
        amount = float(context.args[0].replace(",", "."))
    except ValueError:
        await update.message.reply_text("Сумма должна быть числом.")
        return

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT balance, bank FROM users WHERE telegram_id = %s FOR UPDATE",
                (update.effective_user.id,),
            )
            user = cur.fetchone()

            if not user or float(user["balance"]) < amount:
                await update.message.reply_text("Недостаточно наличных.")
                return

            cur.execute(
                """
                UPDATE users
                SET balance = balance - %s, bank = bank + %s
                WHERE telegram_id = %s
                """,
                (amount, amount, update.effective_user.id),
            )

        conn.commit()

    await update.message.reply_text(f"✅ Положено в банк: {money(amount)} BYN")


async def withdraw_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Формат: <code>/withdraw СУММА</code>",
            parse_mode="HTML",
        )
        return

    try:
        amount = float(context.args[0].replace(",", "."))
    except ValueError:
        await update.message.reply_text("Сумма должна быть числом.")
        return

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT balance, bank FROM users WHERE telegram_id = %s FOR UPDATE",
                (update.effective_user.id,),
            )
            user = cur.fetchone()

            if not user or float(user["bank"]) < amount:
                await update.message.reply_text("Недостаточно денег на карте.")
                return

            cur.execute(
                """
                UPDATE users
                SET bank = bank - %s, balance = balance + %s
                WHERE telegram_id = %s
                """,
                (amount, amount, update.effective_user.id),
            )

        conn.commit()

    await update.message.reply_text(f"✅ Снято с карты: {money(amount)} BYN")


async def exchange_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    items = db_execute(
        "SELECT * FROM exchange_items ORDER BY base_price ASC",
        fetch=True,
    )

    text = "📈 <b>NEON EXCHANGE</b>\n\n"

    for item in items:
        text += (
            f"<b>{item['name']}</b>\n"
            f"Цена: {money(item['current_price'])} BYN\n\n"
        )

    await query.edit_message_text(
        text,
        reply_markup=main_keyboard(query.from_user.id),
        parse_mode="HTML",
    )


async def companies_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    companies = db_execute(
        """
        SELECT c.*,
               EXISTS (
                   SELECT 1 FROM user_companies uc
                   WHERE uc.user_id = %s AND uc.company_id = c.id
               ) AS owned
        FROM companies c
        ORDER BY c.price ASC
        """,
        (query.from_user.id,),
        fetch=True,
    )

    text = "🏢 <b>Бизнес и недвижимость</b>\n\n"

    for company in companies:
        status = "✅ Куплено" if company["owned"] else "🛒 Доступно"
        text += (
            f"{status} <b>{company['name']}</b>\n"
            f"ID: {company['id']}\n"
            f"Цена: {money(company['price'])} BYN\n"
            f"Доход: {money(company['daily_income'])} BYN/день\n\n"
        )

    await query.edit_message_text(
        text,
        reply_markup=main_keyboard(query.from_user.id),
        parse_mode="HTML",
    )


async def transfer_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    await query.edit_message_text(
        "💸 <b>Перевод игроку</b>\n\n"
        "Команда:\n"
        "<code>/transfer НИК СУММА</code>\n\n"
        "Пример:\n"
        "<code>/transfer Owner 1000</code>",
        reply_markup=main_keyboard(query.from_user.id),
        parse_mode="HTML",
    )


async def transfer_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 2:
        await update.message.reply_text(
            "Формат: <code>/transfer НИК СУММА</code>",
            parse_mode="HTML",
        )
        return

    receiver = get_user_by_nickname(context.args[0])

    if not receiver:
        await update.message.reply_text("Игрок с таким ником не найден.")
        return

    try:
        amount = float(context.args[1].replace(",", "."))
    except ValueError:
        await update.message.reply_text("Сумма должна быть числом.")
        return

    sender_id = update.effective_user.id

    if sender_id == receiver["telegram_id"]:
        await update.message.reply_text("Нельзя перевести самому себе.")
        return

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT balance FROM users WHERE telegram_id = %s FOR UPDATE",
                (sender_id,),
            )
            sender = cur.fetchone()

            if not sender or float(sender["balance"]) < amount:
                await update.message.reply_text("Недостаточно денег.")
                return

            cur.execute(
                "UPDATE users SET balance = balance - %s WHERE telegram_id = %s",
                (amount, sender_id),
            )
            cur.execute(
                "UPDATE users SET balance = balance + %s WHERE telegram_id = %s",
                (amount, receiver["telegram_id"]),
            )
            cur.execute(
                """
                INSERT INTO transfers (sender_id, receiver_id, amount)
                VALUES (%s, %s, %s)
                """,
                (sender_id, receiver["telegram_id"], amount),
            )

        conn.commit()

    await update.message.reply_text(
        f"✅ Переведено {money(amount)} BYN игроку {receiver['nickname']}."
    )


async def players_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    players = db_execute(
        """
        SELECT nickname, balance, is_admin
        FROM users
        ORDER BY balance DESC
        LIMIT 20
        """,
        fetch=True,
    )

    text = "👥 <b>Игроки NEON CITY</b>\n\n"

    for player in players:
        status = "🛡 Админ" if player["is_admin"] else "Игрок"
        text += (
            f"<b>{player['nickname']}</b> — "
            f"{money(player['balance'])} BYN — {status}\n"
        )

    await query.edit_message_text(
        text,
        reply_markup=main_keyboard(query.from_user.id),
        parse_mode="HTML",
    )


async def messages_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    messages = db_execute(
        """
        SELECT m.*, u.nickname AS sender_name
        FROM messages m
        JOIN users u ON u.telegram_id = m.sender_id
        WHERE m.receiver_id = %s
        ORDER BY m.created_at DESC
        LIMIT 10
        """,
        (query.from_user.id,),
        fetch=True,
    )

    text = "💬 <b>Сообщения</b>\n\n"

    if not messages:
        text += "Сообщений нет."
    else:
        for message in messages:
            text += f"<b>{message['sender_name']}</b>: {message['text']}\n\n"

    await query.edit_message_text(
        text,
        reply_markup=main_keyboard(query.from_user.id),
        parse_mode="HTML",
    )


async def message_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text(
            "Формат: <code>/message НИК ТЕКСТ</code>",
            parse_mode="HTML",
        )
        return

    receiver = get_user_by_nickname(context.args[0])

    if not receiver:
        await update.message.reply_text("Игрок с таким ником не найден.")
        return

    text = " ".join(context.args[1:])

    db_execute(
        """
        INSERT INTO messages (sender_id, receiver_id, text)
        VALUES (%s, %s, %s)
        """,
        (update.effective_user.id, receiver["telegram_id"], text),
    )

    await update.message.reply_text(
        f"✅ Сообщение отправлено игроку {receiver['nickname']}."
    )


async def loans_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = get_user(query.from_user.id)

    if not user:
        await query.edit_message_text("Сначала нажми /start.")
        return

    await query.edit_message_text(
        f"💳 <b>Кредит</b>\n\n"
        f"Лимит: {money(LOAN_LIMIT)} BYN\n"
        f"Ставка: {int(LOAN_RATE * 100)}%\n"
        f"Долг: {money(user['credit'])} BYN\n\n"
        f"Команда:\n<code>/loan СУММА</code>",
        reply_markup=main_keyboard(user["telegram_id"]),
        parse_mode="HTML",
    )


async def loan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Формат: <code>/loan СУММА</code>",
            parse_mode="HTML",
        )
        return

    try:
        amount = float(context.args[0].replace(",", "."))
    except ValueError:
        await update.message.reply_text("Сумма должна быть числом.")
        return

    if amount <= 0 or amount > LOAN_LIMIT:
        await update.message.reply_text(
            f"Кредит должен быть от 1 до {money(LOAN_LIMIT)} BYN."
        )
        return

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT credit FROM users WHERE telegram_id = %s FOR UPDATE",
                (update.effective_user.id,),
            )
            user = cur.fetchone()

            if not user:
                await update.message.reply_text("Сначала нажми /start.")
                return

            if float(user["credit"]) + amount > LOAN_LIMIT:
                await update.message.reply_text("Превышен кредитный лимит.")
                return

            total = amount * (1 + LOAN_RATE)

            cur.execute(
                """
                UPDATE users
                SET balance = balance + %s, credit = credit + %s
                WHERE telegram_id = %s
                """,
                (amount, total, update.effective_user.id),
            )
            cur.execute(
                """
                INSERT INTO loans (user_id, amount, status)
                VALUES (%s, %s, 'approved')
                """,
                (update.effective_user.id, amount),
            )

        conn.commit()

    await update.message.reply_text(
        f"✅ Кредит выдан: {money(amount)} BYN.\nК возврату: {money(total)} BYN."
    )


async def friends_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    friends = db_execute(
        """
        SELECT u.nickname
        FROM friends f
        JOIN users u ON u.telegram_id = f.friend_id
        WHERE f.owner_id = %s
        ORDER BY u.nickname
        """,
        (query.from_user.id,),
        fetch=True,
    )

    text = "🤝 <b>Друзья</b>\n\n"

    if not friends:
        text += "Друзей нет.\n\nДобавить: <code>/friend НИК</code>"
    else:
        for friend in friends:
            text += f"<b>{friend['nickname']}</b>\n"

    await query.edit_message_text(
        text,
        reply_markup=main_keyboard(query.from_user.id),
        parse_mode="HTML",
    )


async def friend_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Формат: <code>/friend НИК</code>",
            parse_mode="HTML",
        )
        return

    friend = get_user_by_nickname(context.args[0])

    if not friend:
        await update.message.reply_text("Игрок с таким ником не найден.")
        return

    if update.effective_user.id == friend["telegram_id"]:
        await update.message.reply_text("Нельзя добавить себя.")
        return

    db_execute(
        """
        INSERT INTO friends (owner_id, friend_id)
        VALUES (%s, %s)
        ON CONFLICT DO NOTHING
        """,
        (update.effective_user.id, friend["telegram_id"]),
    )

    await update.message.reply_text(
        f"✅ {friend['nickname']} добавлен в друзья."
    )


async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not is_admin(query.from_user.id):
        await query.edit_message_text("Доступ только у администраторов.")
        return

    await query.edit_message_text(
        "🛡 <b>Админ-панель</b>\n\n"
        "<code>/admin НИК</code> — назначить админа\n"
        "<code>/unadmin НИК</code> — снять админа\n"
        "<code>/give НИК СУММА</code> — выдать деньги\n"
        "<code>/addcompany Категория|Название|Цена|Доход|Площадь</code>",
        reply_markup=main_keyboard(query.from_user.id),
        parse_mode="HTML",
    )


async def add_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    if not context.args:
        await update.message.reply_text(
            "Формат: <code>/admin НИК</code>",
            parse_mode="HTML",
        )
        return

    target = get_user_by_nickname(context.args[0])

    if not target:
        await update.message.reply_text("Игрок не найден.")
        return

    db_execute(
        "UPDATE users SET is_admin = TRUE WHERE telegram_id = %s",
        (target["telegram_id"],),
    )

    await update.message.reply_text(
        f"✅ {target['nickname']} назначен администратором."
    )


async def remove_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    if not context.args:
        await update.message.reply_text(
            "Формат: <code>/unadmin НИК</code>",
            parse_mode="HTML",
        )
        return

    target = get_user_by_nickname(context.args[0])

    if not target:
        await update.message.reply_text("Игрок не найден.")
        return

    if target["telegram_id"] == MAIN_ADMIN_ID:
        await update.message.reply_text("Главного администратора нельзя снять.")
        return

    db_execute(
        "UPDATE users SET is_admin = FALSE WHERE telegram_id = %s",
        (target["telegram_id"],),
    )

    await update.message.reply_text(
        f"✅ {target['nickname']} снят с должности."
    )


async def give_money_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    if len(context.args) != 2:
        await update.message.reply_text(
            "Формат: <code>/give НИК СУММА</code>",
            parse_mode="HTML",
        )
        return

    target = get_user_by_nickname(context.args[0])

    if not target:
        await update.message.reply_text("Игрок не найден.")
        return

    try:
        amount = float(context.args[1].replace(",", "."))
    except ValueError:
        await update.message.reply_text("Сумма должна быть числом.")
        return

    db_execute(
        "UPDATE users SET balance = balance + %s WHERE telegram_id = %s",
        (amount, target["telegram_id"]),
    )

    await update.message.reply_text(
        f"✅ Выдано {money(amount)} BYN игроку {target['nickname']}."
    )


async def add_company_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    if len(context.args) != 1:
        await update.message.reply_text(
            "Формат:\n"
            "<code>/addcompany Категория|Название|Цена|Доход|Площадь</code>",
            parse_mode="HTML",
        )
        return

    try:
        category, name, price, income, sqm = context.args[0].split("|")

        db_execute(
            """
            INSERT INTO companies (category, name, price, daily_income, sqm)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                category.strip(),
                name.strip(),
                float(price.replace(",", ".")),
                float(income.replace(",", ".")),
                int(sqm),
            ),
        )
    except Exception:
        await update.message.reply_text("Проверь формат команды.")
        return

    await update.message.reply_text("✅ Объект добавлен.")


async def no_site_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer(
        "Добавь WEBAPP_URL в секреты Netrun.",
        show_alert=True,
    )


class LoginRequest(BaseModel):
    telegram_id: int
    nickname: str
    first_name: str = "Игрок"


class BankRequest(BaseModel):
    telegram_id: int
    amount: float
    action: str


class TransferRequest(BaseModel):
    sender_id: int
    receiver_nickname: str
    amount: float


class LoanRequest(BaseModel):
    telegram_id: int
    amount: float


class FriendRequest(BaseModel):
    telegram_id: int
    friend_nickname: str


class CardSettingsRequest(BaseModel):
    telegram_id: int
    card_color: str = "#7c3aed"
    card_background: str = "#111827"
    card_image: str = ""


class CompanyBuyRequest(BaseModel):
    telegram_id: int
    company_id: int


class ExchangeTradeRequest(BaseModel):
    telegram_id: int
    item_id: int
    quantity: int = 1
    action: str


class MessageRequest(BaseModel):
    sender_id: int
    receiver_nickname: str
    text: str


class AdminActionRequest(BaseModel):
    admin_id: int
    target_nickname: str


class GiveMoneyRequest(BaseModel):
    admin_id: int
    target_nickname: str
    amount: float


class AddCompanyRequest(BaseModel):
    admin_id: int
    category: str
    name: str
    price: float
    daily_income: float
    sqm: int


@app.get("/")
def home():
    return FileResponse("index.html")


@app.get("/health")
def health():
    try:
        db_execute("SELECT 1", fetch=True)
        return {"status": "ok", "database": "connected"}
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error))


@app.post("/api/login")
def login(data: LoginRequest):
    return ensure_user(
        data.telegram_id,
        data.nickname,
        data.first_name,
    )


@app.get("/api/profile")
def profile(telegram_id: int):
    user = get_user(telegram_id)

    if not user:
        raise HTTPException(status_code=404, detail="Игрок не найден")

    return user


@app.get("/api/leaderboard")
def leaderboard():
    return db_execute(
        """
        SELECT nickname, balance, sqm
        FROM users
        ORDER BY balance DESC, sqm DESC
        LIMIT 50
        """,
        fetch=True,
    )


@app.post("/api/bank")
def bank(data: BankRequest):
    if data.amount <= 0:
        raise HTTPException(status_code=400, detail="Сумма должна быть больше нуля")

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT balance, bank FROM users WHERE telegram_id = %s FOR UPDATE",
                (data.telegram_id,),
            )
            user = cur.fetchone()

            if not user:
                raise HTTPException(status_code=404, detail="Игрок не найден")

            if data.action == "deposit":
                if float(user["balance"]) < data.amount:
                    raise HTTPException(status_code=400, detail="Недостаточно наличных")

                cur.execute(
                    """
                    UPDATE users
                    SET balance = balance - %s, bank = bank + %s
                    WHERE telegram_id = %s
                    """,
                    (data.amount, data.amount, data.telegram_id),
                )
                message = f"Положено в банк: {money(data.amount)} BYN"

            elif data.action == "withdraw":
                if float(user["bank"]) < data.amount:
                    raise HTTPException(status_code=400, detail="Недостаточно денег на карте")

                cur.execute(
                    """
                    UPDATE users
                    SET bank = bank - %s, balance = balance + %s
                    WHERE telegram_id = %s
                    """,
                    (data.amount, data.amount, data.telegram_id),
                )
                message = f"Снято с карты: {money(data.amount)} BYN"

            else:
                raise HTTPException(status_code=400, detail="Неверное действие")

        conn.commit()

    return {"status": "ok", "message": message}


@app.post("/api/transfer")
def transfer(data: TransferRequest):
    receiver = get_user_by_nickname(data.receiver_nickname)

    if not receiver:
        raise HTTPException(status_code=404, detail="Игрок с таким ником не найден")

    if data.sender_id == receiver["telegram_id"]:
        raise HTTPException(status_code=400, detail="Нельзя перевести самому себе")

    if data.amount <= 0:
        raise HTTPException(status_code=400, detail="Сумма должна быть больше нуля")

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT balance FROM users WHERE telegram_id = %s FOR UPDATE",
                (data.sender_id,),
            )
            sender = cur.fetchone()

            if not sender or float(sender["balance"]) < data.amount:
                raise HTTPException(status_code=400, detail="Недостаточно денег")

            cur.execute(
                "UPDATE users SET balance = balance - %s WHERE telegram_id = %s",
                (data.amount, data.sender_id),
            )
            cur.execute(
                "UPDATE users SET balance = balance + %s WHERE telegram_id = %s",
                (data.amount, receiver["telegram_id"]),
            )
            cur.execute(
                """
                INSERT INTO transfers (sender_id, receiver_id, amount)
                VALUES (%s, %s, %s)
                """,
                (data.sender_id, receiver["telegram_id"], data.amount),
            )

        conn.commit()

    return {
        "status": "ok",
        "message": f"Переведено {money(data.amount)} BYN игроку {receiver['nickname']}",
    }


@app.post("/api/loan")
def loan(data: LoanRequest):
    if data.amount <= 0 or data.amount > LOAN_LIMIT:
        raise HTTPException(
            status_code=400,
            detail=f"Кредит от 1 до {money(LOAN_LIMIT)} BYN",
        )

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT credit FROM users WHERE telegram_id = %s FOR UPDATE",
                (data.telegram_id,),
            )
            user = cur.fetchone()

            if not user:
                raise HTTPException(status_code=404, detail="Игрок не найден")

            if float(user["credit"]) + data.amount > LOAN_LIMIT:
                raise HTTPException(status_code=400, detail="Превышен кредитный лимит")

            total = data.amount * (1 + LOAN_RATE)

            cur.execute(
                """
                UPDATE users
                SET balance = balance + %s, credit = credit + %s
                WHERE telegram_id = %s
                """,
                (data.amount, total, data.telegram_id),
            )
            cur.execute(
                """
                INSERT INTO loans (user_id, amount, status)
                VALUES (%s, %s, 'approved')
                """,
                (data.telegram_id, data.amount),
            )

        conn.commit()

    return {
        "status": "ok",
        "message": f"Кредит выдан: {money(data.amount)} BYN. К возврату: {money(total)} BYN",
    }


@app.post("/api/friends")
def add_friend(data: FriendRequest):
    friend = get_user_by_nickname(data.friend_nickname)

    if not friend:
        raise HTTPException(status_code=404, detail="Игрок не найден")

    if data.telegram_id == friend["telegram_id"]:
        raise HTTPException(status_code=400, detail="Нельзя добавить себя")

    db_execute(
        """
        INSERT INTO friends (owner_id, friend_id)
        VALUES (%s, %s)
        ON CONFLICT DO NOTHING
        """,
        (data.telegram_id, friend["telegram_id"]),
    )

    return {"status": "ok", "message": f"{friend['nickname']} добавлен в друзья"}


@app.get("/api/friends")
def friends(telegram_id: int):
    return db_execute(
        """
        SELECT u.nickname
        FROM friends f
        JOIN users u ON u.telegram_id = f.friend_id
        WHERE f.owner_id = %s
        ORDER BY u.nickname
        """,
        (telegram_id,),
        fetch=True,
    )


@app.post("/api/card-settings")
def card_settings(data: CardSettingsRequest):
    db_execute(
        """
        UPDATE users
        SET card_color = %s,
            card_background = %s,
            card_image = NULLIF(%s, '')
        WHERE telegram_id = %s
        """,
        (
            data.card_color,
            data.card_background,
            data.card_image,
            data.telegram_id,
        ),
    )
    return {"status": "ok", "message": "Настройки карты сохранены"}


@app.get("/api/companies")
def companies(telegram_id: int):
    return db_execute(
        """
        SELECT c.*,
               EXISTS (
                   SELECT 1 FROM user_companies uc
                   WHERE uc.user_id = %s AND uc.company_id = c.id
               ) AS owned
        FROM companies c
        ORDER BY c.price ASC
        """,
        (telegram_id,),
        fetch=True,
    )


@app.post("/api/companies/buy")
def buy_company(data: CompanyBuyRequest):
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM companies WHERE id = %s",
                (data.company_id,),
            )
            company = cur.fetchone()

            if not company:
                raise HTTPException(status_code=404, detail="Объект не найден")

            cur.execute(
                """
                SELECT 1 FROM user_companies
                WHERE user_id = %s AND company_id = %s
                """,
                (data.telegram_id, data.company_id),
            )
            if cur.fetchone():
                raise HTTPException(status_code=400, detail="Объект уже куплен")

            cur.execute(
                "SELECT balance FROM users WHERE telegram_id = %s FOR UPDATE",
                (data.telegram_id,),
            )
            user = cur.fetchone()

            if not user or float(user["balance"]) < float(company["price"]):
                raise HTTPException(status_code=400, detail="Недостаточно денег")

            cur.execute(
                """
                UPDATE users
                SET balance = balance - %s, sqm = sqm + %s
                WHERE telegram_id = %s
                """,
                (company["price"], company["sqm"], data.telegram_id),
            )
            cur.execute(
                """
                INSERT INTO user_companies (user_id, company_id)
                VALUES (%s, %s)
                ON CONFLICT DO NOTHING
                """,
                (data.telegram_id, data.company_id),
            )

        conn.commit()

    return {
        "status": "ok",
        "message": f"Куплено: {company['name']} за {money(company['price'])} BYN",
    }


@app.get("/api/exchange")
def exchange():
    return db_execute(
        "SELECT * FROM exchange_items ORDER BY base_price ASC",
        fetch=True,
    )


@app.post("/api/exchange/trade")
def exchange_trade(data: ExchangeTradeRequest):
    if data.quantity <= 0:
        raise HTTPException(status_code=400, detail="Количество должно быть больше нуля")

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM exchange_items WHERE id = %s",
                (data.item_id,),
            )
            item = cur.fetchone()

            if not item:
                raise HTTPException(status_code=404, detail="Актив не найден")

            price = float(item["current_price"]) * data.quantity

            cur.execute(
                "SELECT balance FROM users WHERE telegram_id = %s FOR UPDATE",
                (data.telegram_id,),
            )
            user = cur.fetchone()

            if not user:
                raise HTTPException(status_code=404, detail="Игрок не найден")

            if data.action == "buy":
                if float(user["balance"]) < price:
                    raise HTTPException(status_code=400, detail="Недостаточно денег")

                cur.execute(
                    "UPDATE users SET balance = balance - %s WHERE telegram_id = %s",
                    (price, data.telegram_id),
                )
                cur.execute(
                    """
                    INSERT INTO exchange_holdings (user_id, item_id, quantity)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (user_id, item_id)
                    DO UPDATE SET quantity = exchange_holdings.quantity + EXCLUDED.quantity
                    """,
                    (data.telegram_id, data.item_id, data.quantity),
                )
                message = f"Куплено: {item['name']} за {money(price)} BYN"

            elif data.action == "sell":
                cur.execute(
                    """
                    SELECT quantity FROM exchange_holdings
                    WHERE user_id = %s AND item_id = %s FOR UPDATE
                    """,
                    (data.telegram_id, data.item_id),
                )
                holding = cur.fetchone()

                if not holding or holding["quantity"] < data.quantity:
                    raise HTTPException(status_code=400, detail="Недостаточно актива")

                cur.execute(
                    """
                    UPDATE exchange_holdings
                    SET quantity = quantity - %s
                    WHERE user_id = %s AND item_id = %s
                    """,
                    (data.quantity, data.telegram_id, data.item_id),
                )
                cur.execute(
                    "UPDATE users SET balance = balance + %s WHERE telegram_id = %s",
                    (price, data.telegram_id),
                )
                message = f"Продано: {item['name']} за {money(price)} BYN"

            else:
                raise HTTPException(status_code=400, detail="Неверное действие")

        conn.commit()

    return {"status": "ok", "message": message}


@app.get("/api/players")
def players():
    return db_execute(
        """
        SELECT telegram_id, nickname, balance, is_admin
        FROM users
        ORDER BY balance DESC
        LIMIT 100
        """,
        fetch=True,
    )


@app.post("/api/messages")
def send_message(data: MessageRequest):
    receiver = get_user_by_nickname(data.receiver_nickname)

    if not receiver:
        raise HTTPException(status_code=404, detail="Игрок не найден")

    db_execute(
        """
        INSERT INTO messages (sender_id, receiver_id, text)
        VALUES (%s, %s, %s)
        """,
        (data.sender_id, receiver["telegram_id"], data.text),
    )

    return {
        "status": "ok",
        "message": f"Сообщение отправлено игроку {receiver['nickname']}",
    }


@app.get("/api/messages")
def messages(telegram_id: int):
    return db_execute(
        """
        SELECT m.*, u.nickname AS sender_name
        FROM messages m
        JOIN users u ON u.telegram_id = m.sender_id
        WHERE m.receiver_id = %s
        ORDER BY m.created_at DESC
        LIMIT 50
        """,
        (telegram_id,),
        fetch=True,
    )


@app.post("/api/admin/add")
def add_admin(data: AdminActionRequest):
    if not is_admin(data.admin_id):
        raise HTTPException(status_code=403, detail="Только администраторы")

    target = get_user_by_nickname(data.target_nickname)

    if not target:
        raise HTTPException(status_code=404, detail="Игрок не найден")

    db_execute(
        "UPDATE users SET is_admin = TRUE WHERE telegram_id = %s",
        (target["telegram_id"],),
    )

    return {"status": "ok", "message": f"{target['nickname']} назначен администратором"}


@app.post("/api/admin/remove")
def remove_admin(data: AdminActionRequest):
    if not is_admin(data.admin_id):
        raise HTTPException(status_code=403, detail="Только администраторы")

    target = get_user_by_nickname(data.target_nickname)

    if not target:
        raise HTTPException(status_code=404, detail="Игрок не найден")

    if target["telegram_id"] == MAIN_ADMIN_ID:
        raise HTTPException(status_code=400, detail="Главного администратора нельзя снять")

    db_execute(
        "UPDATE users SET is_admin = FALSE WHERE telegram_id = %s",
        (target["telegram_id"],),
    )

    return {"status": "ok", "message": f"{target['nickname']} снят с должности администратора"}


@app.post("/api/admin/give-money")
def give_money(data: GiveMoneyRequest):
    if not is_admin(data.admin_id):
        raise HTTPException(status_code=403, detail="Только администраторы")

    target = get_user_by_nickname(data.target_nickname)

    if not target:
        raise HTTPException(status_code=404, detail="Игрок не найден")

    if data.amount <= 0:
        raise HTTPException(status_code=400, detail="Сумма должна быть больше нуля")

    db_execute(
        "UPDATE users SET balance = balance + %s WHERE telegram_id = %s",
        (data.amount, target["telegram_id"]),
    )

    return {
        "status": "ok",
        "message": f"Выдано {money(data.amount)} BYN игроку {target['nickname']}",
    }


@app.post("/api/admin/company")
def add_company(data: AddCompanyRequest):
    if not is_admin(data.admin_id):
        raise HTTPException(status_code=403, detail="Только администраторы")

    db_execute(
        """
        INSERT INTO companies (category, name, price, daily_income, sqm)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (
            data.category,
            data.name,
            data.price,
            data.daily_income,
            data.sqm,
        ),
    )

    return {"status": "ok", "message": "Объект добавлен"}


def init_db():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(SCHEMA)

            cur.executemany(
                """
                INSERT INTO companies
                (category, name, price, daily_income, sqm)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
                """,
                DEFAULT_COMPANIES,
            )

            for name, base, minimum, maximum in DEFAULT_EXCHANGE:
                cur.execute(
                    """
                    INSERT INTO exchange_items
                    (name, base_price, min_price, max_price, current_price)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (name) DO NOTHING
                    """,
                    (name, base, minimum, maximum, base),
                )

        conn.commit()


telegram_application = Application.builder().token(BOT_TOKEN).build()

telegram_application.add_handler(CommandHandler("start", start))
telegram_application.add_handler(CommandHandler("deposit", deposit_command))
telegram_application.add_handler(CommandHandler("withdraw", withdraw_command))
telegram_application.add_handler(CommandHandler("transfer", transfer_command))
telegram_application.add_handler(CommandHandler("loan", loan_command))
telegram_application.add_handler(CommandHandler("friend", friend_command))
telegram_application.add_handler(CommandHandler("message", message_command))
telegram_application.add_handler(CommandHandler("admin", add_admin_command))
telegram_application.add_handler(CommandHandler("unadmin", remove_admin_command))
telegram_application.add_handler(CommandHandler("give", give_money_command))
telegram_application.add_handler(CommandHandler("addcompany", add_company_command))

telegram_application.add_handler(CallbackQueryHandler(profile_callback, pattern="^profile$"))
telegram_application.add_handler(CallbackQueryHandler(leaderboard_callback, pattern="^leaderboard$"))
telegram_application.add_handler(CallbackQueryHandler(bank_callback, pattern="^bank$"))
telegram_application.add_handler(CallbackQueryHandler(exchange_callback, pattern="^exchange$"))
telegram_application.add_handler(CallbackQueryHandler(companies_callback, pattern="^companies$"))
telegram_application.add_handler(CallbackQueryHandler(transfer_callback, pattern="^transfer$"))
telegram_application.add_handler(CallbackQueryHandler(players_callback, pattern="^players$"))
telegram_application.add_handler(CallbackQueryHandler(messages_callback, pattern="^messages$"))
telegram_application.add_handler(CallbackQueryHandler(loans_callback, pattern="^loans$"))
telegram_application.add_handler(CallbackQueryHandler(friends_callback, pattern="^friends$"))
telegram_application.add_handler(CallbackQueryHandler(admin_callback, pattern="^admin$"))
telegram_application.add_handler(CallbackQueryHandler(no_site_callback, pattern="^no_site$"))


@asynccontextmanager
async def lifespan(application: FastAPI):
    init_db()

    await telegram_application.initialize()
    await telegram_application.start()
    await telegram_application.updater.start_polling(
        allowed_updates=Update.ALL_TYPES
    )

    yield

    await telegram_application.updater.stop()
    await telegram_application.stop()
    await telegram_application.shutdown()


app.router.lifespan_context = lifespan


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.getenv("PORT", 8000)),
    )
