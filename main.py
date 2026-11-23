import os
import random
import asyncio
from datetime import datetime, timedelta

import psycopg2
from psycopg2.extras import RealDictCursor
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    WebAppInfo,
)
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
DAILY_INCOME_HOUR = 12

if not DATABASE_URL or not BOT_TOKEN:
    raise RuntimeError("Заполни DATABASE_URL и BOT_TOKEN в переменных окружения.")

app = FastAPI(title="NEON CITY API")

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
    username TEXT,
    first_name TEXT,
    balance NUMERIC(18,2) NOT NULL DEFAULT 0,
    bank NUMERIC(18,2) NOT NULL DEFAULT 0,
    credit NUMERIC(18,2) NOT NULL DEFAULT 0,
    sqm INTEGER NOT NULL DEFAULT 0,
    card_color TEXT NOT NULL DEFAULT '#7c3aed',
    card_background TEXT NOT NULL DEFAULT '#111827',
    card_image TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS admins (
    telegram_id BIGINT PRIMARY KEY,
    is_main BOOLEAN NOT NULL DEFAULT FALSE,
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

CREATE TABLE IF NOT EXISTS admin_messages (
    id BIGSERIAL PRIMARY KEY,
    sender_id BIGINT NOT NULL REFERENCES users(telegram_id),
    text TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_messages_receiver
ON messages(receiver_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_messages_sender
ON messages(sender_id, created_at DESC);
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


def db_execute(query, params=(), fetch=False, many=False):
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if many:
                cur.executemany(query, params)
            else:
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


def ensure_user(user):
    telegram_id = user.id
    username = user.username or ""
    first_name = user.first_name or "Игрок"

    db_execute(
        """
        INSERT INTO users (telegram_id, username, first_name)
        VALUES (%s, %s, %s)
        ON CONFLICT (telegram_id) DO UPDATE
        SET username = EXCLUDED.username,
            first_name = EXCLUDED.first_name
        """,
        (telegram_id, username, first_name),
    )

    if telegram_id == MAIN_ADMIN_ID:
        db_execute(
            """
            INSERT INTO admins (telegram_id, is_main)
            VALUES (%s, TRUE)
            ON CONFLICT (telegram_id) DO UPDATE
            SET is_main = TRUE
            """,
            (telegram_id,),
        )

    return get_user(telegram_id)


def is_admin(telegram_id):
    rows = db_execute(
        "SELECT 1 FROM admins WHERE telegram_id = %s",
        (telegram_id,),
        fetch=True,
    )
    return bool(rows)


def is_main_admin(telegram_id):
    return telegram_id == MAIN_ADMIN_ID


def money(value):
    return f"{float(value):,.2f}".replace(",", " ")


def main_menu_keyboard(webapp_url=""):
    buttons = [
        [InlineKeyboardButton("👤 Профиль", callback_data="profile")],
        [InlineKeyboardButton("📈 Биржа", callback_data="exchange")],
        [InlineKeyboardButton("🏦 Банк", callback_data="bank")],
        [InlineKeyboardButton("🏢 Бизнес", callback_data="companies")],
        [InlineKeyboardButton("💸 Перевод", callback_data="transfer")],
        [InlineKeyboardButton("👥 Игроки", callback_data="players")],
        [InlineKeyboardButton("💬 Чаты", callback_data="chats")],
        [InlineKeyboardButton("💳 Кредит", callback_data="loans")],
        [InlineKeyboardButton("🤝 Друзья", callback_data="friends")],
        [InlineKeyboardButton("⚙️ Настройки", callback_data="settings")],
    ]

    if webapp_url:
        buttons.insert(
            0,
            [InlineKeyboardButton(
                "🌐 Открыть NEON CITY",
                web_app=WebAppInfo(url=webapp_url),
            )],
        )

    if is_main_admin(MAIN_ADMIN_ID):
        buttons.append(
            [InlineKeyboardButton("🛡 Админ-панель", callback_data="admin")]
        )

    return InlineKeyboardMarkup(buttons)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = ensure_user(update.effective_user)
    text = (
        f"🌆 <b>NEON CITY</b>\n\n"
        f"Привет, <b>{user['first_name']}</b>!\n\n"
        f"💰 Баланс: <b>{money(user['balance'])} BYN</b>\n"
        f"🏦 Банк: <b>{money(user['bank'])} BYN</b>\n"
        f"🌍 Земля: <b>{user['sqm']} км²</b>\n\n"
        f"Налог: <b>{money(SQM_TAX)} BYN за км² в день</b>"
    )
    await update.message.reply_text(
        text,
        reply_markup=main_menu_keyboard(WEBAPP_URL),
        parse_mode="HTML",
    )


async def profile_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = ensure_user(query.from_user)

    text = (
        f"👤 <b>Профиль</b>\n\n"
        f"Имя: <b>{user['first_name']}</b>\n"
        f"Telegram ID: <code>{user['telegram_id']}</code>\n\n"
        f"💰 Наличные: <b>{money(user['balance'])} BYN</b>\n"
        f"🏦 Банк: <b>{money(user['bank'])} BYN</b>\n"
        f"💳 Кредит: <b>{money(user['credit'])} BYN</b>\n"
        f"🌍 Земля: <b>{user['sqm']} км²</b>"
    )

    await query.edit_message_text(
        text,
        reply_markup=main_menu_keyboard(WEBAPP_URL),
        parse_mode="HTML",
    )


async def bank_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = ensure_user(query.from_user)

    text = (
        f"🏦 <b>NEON BANK</b>\n\n"
        f"💳 Карта: <b>NEON CARD</b>\n"
        f"💰 Наличные: <b>{money(user['balance'])} BYN</b>\n"
        f"🏦 На карте: <b>{money(user['bank'])} BYN</b>\n\n"
        f"Выбери действие:"
    )

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📥 Положить 1 000", callback_data="bank_deposit_1000"),
            InlineKeyboardButton("📤 Снять 1 000", callback_data="bank_withdraw_1000"),
        ],
        [
            InlineKeyboardButton("📥 Положить всё", callback_data="bank_deposit_all"),
            InlineKeyboardButton("📤 Снять всё", callback_data="bank_withdraw_all"),
        ],
        [InlineKeyboardButton("⬅️ Меню", callback_data="menu")],
    ])

    await query.edit_message_text(text, reply_markup=keyboard, parse_mode="HTML")


async def bank_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    telegram_id = query.from_user.id
    action = query.data

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT balance, bank FROM users WHERE telegram_id = %s FOR UPDATE",
                (telegram_id,),
            )
            user = cur.fetchone()

            if not user:
                await query.edit_message_text("Пользователь не найден.")
                return

            if action == "bank_deposit_all":
                amount = float(user["balance"])
            elif action == "bank_withdraw_all":
                amount = float(user["bank"])
            else:
                amount = 1_000.0

            if "deposit" in action:
                if amount <= 0 or float(user["balance"]) < amount:
                    await query.answer("Недостаточно наличных.", show_alert=True)
                    return
                cur.execute(
                    """
                    UPDATE users
                    SET balance = balance - %s,
                        bank = bank + %s
                    WHERE telegram_id = %s
                    """,
                    (amount, amount, telegram_id),
                )
                text = f"✅ Положено в банк: <b>{money(amount)} BYN</b>"
            else:
                if amount <= 0 or float(user["bank"]) < amount:
                    await query.answer("На карте недостаточно денег.", show_alert=True)
                    return
                cur.execute(
                    """
                    UPDATE users
                    SET bank = bank - %s,
                        balance = balance + %s
                    WHERE telegram_id = %s
                    """,
                    (amount, amount, telegram_id),
                )
                text = f"✅ Снято с карты: <b>{money(amount)} BYN</b>"

        conn.commit()

    await query.edit_message_text(
        text,
        reply_markup=main_menu_keyboard(WEBAPP_URL),
        parse_mode="HTML",
    )


async def companies_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    companies = db_execute(
        """
        SELECT c.*, EXISTS (
            SELECT 1 FROM user_companies uc
            WHERE uc.user_id = %s AND uc.company_id = c.id
        ) AS owned
        FROM companies c
        ORDER BY c.price ASC
        """,
        (query.from_user.id,),
        fetch=True,
    )

    if not companies:
        text = "🏢 Бизнесов пока нет. Попроси администратора добавить объекты."
    else:
        lines = ["🏢 <b>Бизнес и недвижимость</b>\n"]
        for item in companies:
            status = "✅ Куплено" if item["owned"] else "🛒 Доступно"
            lines.append(
                f"{status} <b>{item['name']}</b>\n"
                f"Категория: {item['category']}\n"
                f"Цена: {money(item['price'])} BYN\n"
                f"Доход: {money(item['daily_income'])} BYN/день\n"
                f"Площадь: {item['sqm']} км²\n"
            )
        text = "\n".join(lines)

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🛒 Купить бизнес", callback_data="buy_company")],
        [InlineKeyboardButton("⬅️ Меню", callback_data="menu")],
    ])

    await query.edit_message_text(text, reply_markup=keyboard, parse_mode="HTML")


async def buy_company_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    companies = db_execute(
        """
        SELECT c.*
        FROM companies c
        WHERE NOT EXISTS (
            SELECT 1 FROM user_companies uc
            WHERE uc.user_id = %s AND uc.company_id = c.id
        )
        ORDER BY c.price ASC
        """,
        (query.from_user.id,),
        fetch=True,
    )

    if not companies:
        await query.edit_message_text(
            "У тебя уже есть все доступные объекты.",
            reply_markup=main_menu_keyboard(WEBAPP_URL),
        )
        return

    keyboard = []
    for item in companies[:20]:
        keyboard.append([
            InlineKeyboardButton(
                f"{item['name']} — {money(item['price'])} BYN",
                callback_data=f"company_buy_{item['id']}",
            )
        ])
    keyboard.append([InlineKeyboardButton("⬅️ Меню", callback_data="menu")])

    await query.edit_message_text(
        "🛒 <b>Выбери объект для покупки:</b>",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )


async def company_buy_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    telegram_id = query.from_user.id
    company_id = int(query.data.replace("company_buy_", ""))

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM companies WHERE id = %s",
                (company_id,),
            )
            company = cur.fetchone()

            if not company:
                await query.answer("Объект не найден.", show_alert=True)
                return

            cur.execute(
                """
                SELECT 1 FROM user_companies
                WHERE user_id = %s AND company_id = %s
                """,
                (telegram_id, company_id),
            )
            if cur.fetchone():
                await query.answer("Этот объект уже куплен.", show_alert=True)
                return

            cur.execute(
                "SELECT balance, sqm FROM users WHERE telegram_id = %s FOR UPDATE",
                (telegram_id,),
            )
            user = cur.fetchone()

            price = float(company["price"])
            if not user or float(user["balance"]) < price:
                await query.answer("Недостаточно денег.", show_alert=True)
                return

            cur.execute(
                """
                UPDATE users
                SET balance = balance - %s,
                    sqm = sqm + %s
                WHERE telegram_id = %s
                """,
                (price, company["sqm"], telegram_id),
            )
            cur.execute(
                """
                INSERT INTO user_companies (user_id, company_id)
                VALUES (%s, %s)
                ON CONFLICT DO NOTHING
                """,
                (telegram_id, company_id),
            )

        conn.commit()

    await query.edit_message_text(
        f"✅ Куплено: <b>{company['name']}</b>\n"
        f"💰 Списано: <b>{money(company['price'])} BYN</b>\n"
        f"📈 Доход: <b>{money(company['daily_income'])} BYN в день</b>",
        reply_markup=main_menu_keyboard(WEBAPP_URL),
        parse_mode="HTML",
    )


async def exchange_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    items = db_execute(
        "SELECT * FROM exchange_items ORDER BY base_price ASC",
        fetch=True,
    )

    if not items:
        text = "📈 Биржа пока пуста."
    else:
        lines = ["📈 <b>NEON EXCHANGE</b>\n"]
        for item in items:
            lines.append(
                f"<b>{item['name']}</b>\n"
                f"Цена: {money(item['current_price'])} BYN\n"
                f"Диапазон: {money(item['min_price'])} — {money(item['max_price'])} BYN\n"
            )
        text = "\n".join(lines)

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🛒 Купить", callback_data="exchange_buy")],
        [InlineKeyboardButton("📤 Продать", callback_data="exchange_sell")],
        [InlineKeyboardButton("⬅️ Меню", callback_data="menu")],
    ])

    await query.edit_message_text(text, reply_markup=keyboard, parse_mode="HTML")


async def exchange_trade_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    mode = "buy" if query.data == "exchange_buy" else "sell"

    items = db_execute(
        "SELECT * FROM exchange_items ORDER BY base_price ASC",
        fetch=True,
    )

    keyboard = []
    for item in items[:20]:
        keyboard.append([
            InlineKeyboardButton(
                f"{item['name']} — {money(item['current_price'])} BYN",
                callback_data=f"exchange_{mode}_{item['id']}",
            )
        ])
    keyboard.append([InlineKeyboardButton("⬅️ Меню", callback_data="menu")])

    await query.edit_message_text(
        f"{'🛒 Покупка' if mode == 'buy' else '📤 Продажа'} на бирже:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def exchange_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    telegram_id = query.from_user.id
    parts = query.data.split("_")
    mode = parts[1]
    item_id = int(parts[2])
    quantity = 1

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM exchange_items WHERE id = %s",
                (item_id,),
            )
            item = cur.fetchone()

            if not item:
                await query.answer("Товар не найден.", show_alert=True)
                return

            price = float(item["current_price"]) * quantity

            cur.execute(
                "SELECT balance FROM users WHERE telegram_id = %s FOR UPDATE",
                (telegram_id,),
            )
            user = cur.fetchone()

            if not user:
                await query.answer("Пользователь не найден.", show_alert=True)
                return

            if mode == "buy":
                if float(user["balance"]) < price:
                    await query.answer("Недостаточно денег.", show_alert=True)
                    return

                cur.execute(
                    "UPDATE users SET balance = balance - %s WHERE telegram_id = %s",
                    (price, telegram_id),
                )
                cur.execute(
                    """
                    INSERT INTO exchange_holdings (user_id, item_id, quantity)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (user_id, item_id)
                    DO UPDATE SET quantity = exchange_holdings.quantity + EXCLUDED.quantity
                    """,
                    (telegram_id, item_id, quantity),
                )
                text = f"✅ Куплено: <b>{item['name']}</b> за {money(price)} BYN"
            else:
                cur.execute(
                    """
                    SELECT quantity FROM exchange_holdings
                    WHERE user_id = %s AND item_id = %s FOR UPDATE
                    """,
                    (telegram_id, item_id),
                )
                holding = cur.fetchone()

                if not holding or holding["quantity"] < quantity:
                    await query.answer("У тебя нет этого актива.", show_alert=True)
                    return

                cur.execute(
                    """
                    UPDATE exchange_holdings
                    SET quantity = quantity - %s
                    WHERE user_id = %s AND item_id = %s
                    """,
                    (quantity, telegram_id, item_id),
                )
                cur.execute(
                    "UPDATE users SET balance = balance + %s WHERE telegram_id = %s",
                    (price, telegram_id),
                )
                text = f"✅ Продано: <b>{item['name']}</b> за {money(price)} BYN"

        conn.commit()

    await query.edit_message_text(
        text,
        reply_markup=main_menu_keyboard(WEBAPP_URL),
        parse_mode="HTML",
    )


async def transfer_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    await query.edit_message_text(
        "💸 <b>Перевод игроку</b>\n\n"
        "Отправь команду в формате:\n"
        "<code>/перевод TELEGRAM_ID СУММА</code>\n\n"
        "Пример:\n"
        "<code>/перевод 5634302903 1000</code>",
        reply_markup=main_menu_keyboard(WEBAPP_URL),
        parse_mode="HTML",
    )


async def transfer_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 2:
        await update.message.reply_text(
            "Формат: <code>/перевод TELEGRAM_ID СУММА</code>",
            parse_mode="HTML",
        )
        return

    try:
        receiver_id = int(context.args[0])
        amount = float(context.args[1].replace(",", "."))
    except ValueError:
        await update.message.reply_text("ID и сумма должны быть числами.")
        return

    sender_id = update.effective_user.id

    if sender_id == receiver_id:
        await update.message.reply_text("Нельзя перевести деньги самому себе.")
        return

    if amount <= 0:
        await update.message.reply_text("Сумма должна быть больше нуля.")
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
                """
                INSERT INTO users (telegram_id, first_name)
                VALUES (%s, 'Игрок')
                ON CONFLICT (telegram_id) DO NOTHING
                """,
                (receiver_id,),
            )

            cur.execute(
                "UPDATE users SET balance = balance - %s WHERE telegram_id = %s",
                (amount, sender_id),
            )
            cur.execute(
                "UPDATE users SET balance = balance + %s WHERE telegram_id = %s",
                (amount, receiver_id),
            )
            cur.execute(
                """
                INSERT INTO transfers (sender_id, receiver_id, amount)
                VALUES (%s, %s, %s)
                """,
                (sender_id, receiver_id, amount),
            )

        conn.commit()

    await update.message.reply_text(
        f"✅ Переведено <b>{money(amount)} BYN</b> игроку\n"
        f"ID: <code>{receiver_id}</code>",
        parse_mode="HTML",
    )


async def players_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    players = db_execute(
        """
        SELECT telegram_id, first_name, username, balance
        FROM users
        ORDER BY balance DESC
        LIMIT 30
        """,
        fetch=True,
    )

    lines = ["👥 <b>Игроки NEON CITY</b>\n"]
    for player in players:
        username = f"@{player['username']}" if player["username"] else "—"
        lines.append(
            f"<b>{player['first_name']}</b> {username}\n"
            f"ID: <code>{player['telegram_id']}</code>\n"
            f"💰 {money(player['balance'])} BYN\n"
        )

    await query.edit_message_text(
        "\n".join(lines),
        reply_markup=main_menu_keyboard(WEBAPP_URL),
        parse_mode="HTML",
    )


async def chats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    messages = db_execute(
        """
        SELECT m.*, u.first_name
        FROM messages m
        JOIN users u ON u.telegram_id = m.sender_id
        WHERE m.receiver_id = %s
        ORDER BY m.created_at DESC
        LIMIT 10
        """,
        (query.from_user.id,),
        fetch=True,
    )

    if not messages:
        text = "💬 Личных сообщений пока нет."
    else:
        lines = ["💬 <b>Последние сообщения</b>\n"]
        for message in messages:
            lines.append(
                f"<b>{message['first_name']}</b>:\n{message['text']}\n"
            )
        text = "\n".join(lines)

    await query.edit_message_text(
        text,
        reply_markup=main_menu_keyboard(WEBAPP_URL),
        parse_mode="HTML",
    )


async def loans_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = ensure_user(query.from_user)

    text = (
        f"💳 <b>Кредит</b>\n\n"
        f"Лимит: <b>{money(LOAN_LIMIT)} BYN</b>\n"
        f"Ставка: <b>{int(LOAN_RATE * 100)}%</b>\n"
        f"Текущий долг: <b>{money(user['credit'])} BYN</b>\n\n"
        f"Отправь команду:\n"
        f"<code>/кредит СУММА</code>"
    )

    await query.edit_message_text(
        text,
        reply_markup=main_menu_keyboard(WEBAPP_URL),
        parse_mode="HTML",
    )


async def loan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Формат: <code>/кредит СУММА</code>", parse_mode="HTML")
        return

    try:
        amount = float(context.args[0].replace(",", "."))
    except ValueError:
        await update.message.reply_text("Сумма должна быть числом.")
        return

    if amount <= 0 or amount > LOAN_LIMIT:
        await update.message.reply_text(
            f"Сумма кредита должна быть от 1 до {money(LOAN_LIMIT)} BYN."
        )
        return

    telegram_id = update.effective_user.id

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT credit FROM users WHERE telegram_id = %s FOR UPDATE",
                (telegram_id,),
            )
            user = cur.fetchone()

            if not user:
                await update.message.reply_text("Сначала нажми /start.")
                return

            if float(user["credit"]) + amount > LOAN_LIMIT:
                await update.message.reply_text("Превышен кредитный лимит.")
                return

            cur.execute(
                """
                UPDATE users
                SET balance = balance + %s,
                    credit = credit + %s
                WHERE telegram_id = %s
                """,
                (amount, amount * (1 + LOAN_RATE), telegram_id),
            )
            cur.execute(
                "INSERT INTO loans (user_id, amount, status) VALUES (%s, %s, 'approved')",
                (telegram_id, amount),
            )

        conn.commit()

    await update.message.reply_text(
        f"✅ Кредит одобрен: <b>{money(amount)} BYN</b>\n"
        f"К возврату: <b>{money(amount * (1 + LOAN_RATE))} BYN</b>",
        parse_mode="HTML",
    )


async def friends_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    friends = db_execute(
        """
        SELECT u.telegram_id, u.first_name, u.username
        FROM friends f
        JOIN users u ON u.telegram_id = f.friend_id
        WHERE f.owner_id = %s
        ORDER BY u.first_name
        """,
        (query.from_user.id,),
        fetch=True,
    )

    if not friends:
        text = "🤝 Друзей пока нет.\n\nДобавить: <code>/друг TELEGRAM_ID</code>"
    else:
        lines = ["🤝 <b>Твои друзья</b>\n"]
        for friend in friends:
            username = f"@{friend['username']}" if friend["username"] else ""
            lines.append(
                f"<b>{friend['first_name']}</b> {username}\n"
                f"ID: <code>{friend['telegram_id']}</code>"
            )
        text = "\n".join(lines)

    await query.edit_message_text(
        text,
        reply_markup=main_menu_keyboard(WEBAPP_URL),
        parse_mode="HTML",
    )


async def friend_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Формат: <code>/друг TELEGRAM_ID</code>", parse_mode="HTML")
        return

    try:
        friend_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("ID должен быть числом.")
        return

    owner_id = update.effective_user.id

    if owner_id == friend_id:
        await update.message.reply_text("Нельзя добавить себя в друзья.")
        return

    try:
        db_execute(
            """
            INSERT INTO users (telegram_id, first_name)
            VALUES (%s, 'Игрок')
            ON CONFLICT (telegram_id) DO NOTHING
            """,
            (friend_id,),
        )
        db_execute(
            """
            INSERT INTO friends (owner_id, friend_id)
            VALUES (%s, %s)
            ON CONFLICT DO NOTHING
            """,
            (owner_id, friend_id),
        )
    except psycopg2.errors.ForeignKeyViolation:
        await update.message.reply_text("Игрок с таким ID не найден.")
        return

    await update.message.reply_text("✅ Игрок добавлен в друзья.")


async def settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = ensure_user(query.from_user)

    text = (
        "⚙️ <b>Настройки карты</b>\n\n"
        f"Текущий цвет: <code>{user['card_color']}</code>\n"
        f"Фон карты: <code>{user['card_background']}</code>\n\n"
        "Отправь команду:\n"
        "<code>/карта #FF0000 #111111</code>\n\n"
        "Первый цвет — акцент карты, второй — фон.\n\n"
        "Изображение карты:\n"
        "<code>/картинка https://ссылка-на-картинку</code>"
    )

    await query.edit_message_text(
        text,
        reply_markup=main_menu_keyboard(WEBAPP_URL),
        parse_mode="HTML",
    )


async def card_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 2:
        await update.message.reply_text(
            "Формат: <code>/карта #FF0000 #111111</code>",
            parse_mode="HTML",
        )
        return

    color, background = context.args

    db_execute(
        """
        UPDATE users
        SET card_color = %s,
            card_background = %s
        WHERE telegram_id = %s
        """,
        (color, background, update.effective_user.id),
    )

    await update.message.reply_text("✅ Внешний вид карты обновлён.")


async def card_image_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Формат: <code>/картинка https://ссылка</code>",
            parse_mode="HTML",
        )
        return

    db_execute(
        "UPDATE users SET card_image = %s WHERE telegram_id = %s",
        (context.args[0], update.effective_user.id),
    )

    await update.message.reply_text("✅ Изображение карты обновлено.")


async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
