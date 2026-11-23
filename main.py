import os

import psycopg2
from psycopg2.extras import RealDictCursor
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

DATABASE_URL = os.getenv("DATABASE_URL")
BOT_TOKEN = os.getenv("BOT_TOKEN")
MAIN_ADMIN_ID = int(os.getenv("MAIN_ADMIN_ID", "5634302903"))
WEBAPP_URL = os.getenv("WEBAPP_URL", "")

SQM_TAX = 100
LOAN_LIMIT = 1_000_000
LOAN_RATE = 0.10

if not DATABASE_URL:
    raise RuntimeError("Заполни DATABASE_URL в переменных окружения.")

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
    nickname = nickname.strip()

    if not nickname:
        raise HTTPException(status_code=400, detail="Введите никнейм")

    existing = get_user_by_nickname(nickname)

    if existing and existing["telegram_id"] != telegram_id:
        raise HTTPException(status_code=400, detail="Этот никнейм уже занят")

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
    return ensure_user(data.telegram_id, data.nickname, data.first_name)


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

    return {"status": "ok", "message": f"Сообщение отправлено игроку {receiver['nickname']}"}


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

    return {"status": "ok", "message": f"Выдано {money(data.amount)} BYN игроку {target['nickname']}"}


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


@app.on_event("startup")
def startup():
    init_db()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.getenv("PORT", 8000)),
    )
