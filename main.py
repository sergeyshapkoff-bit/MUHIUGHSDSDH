from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import psycopg2
from psycopg2.extras import RealDictCursor
import json
import time
import random

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DATABASE_URL = "postgresql://postgres.zmfepxqnxcvkvdjonzhp:p0LwFeRg9NJ7Cusj@aws-0-eu-west-1.pooler.supabase.com:5432/postgres?sslmode=require"
MAIN_ADMIN_ID = 5634302903 

def get_db():
    return psycopg2.connect(DATABASE_URL)

def get_current_rates():
    day = int(time.time()) // 86400
    rng = random.Random(day)
    return {
        "gold": rng.randint(400, 600),
        "diamonds": rng.randint(4000, 6000),
        "crypto": rng.randint(35000, 65000)
    }

def init_db():
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id bigint primary key,
                name text,
                amount bigint default 140000, 
                apartments jsonb default '[]'::jsonb,
                last_payout bigint,
                card_number text,
                card_cvc text,
                gold bigint default 0,
                diamonds bigint default 0,
                crypto bigint default 0
            );
        """)
        conn.commit()
        cursor.close(); conn.close()
    except Exception as e:
        print("Ошибка инициализации БД:", e)

init_db()

class BuyRequest(BaseModel):
    user_id: int
    user_name: str
    apartment_name: str
    price: int
    income: int

class SellRequest(BaseModel):
    user_id: int
    apartment_index: int
    price: int

class TransferRequest(BaseModel):
    sender_id: int
    card_number: str
    card_cvc: str
    amount: int

class AddMoneyRequest(BaseModel):
    admin_id: int
    target_id: int
    amount: int

class TokenRequest(BaseModel):
    user_id: int
    token_type: str
    amount: int
    action: str

class SetNameRequest(BaseModel):
    user_id: int
    name: str

def calculate_income(amount, apartments, last_payout):
    now = int(time.time())
    if not last_payout: last_payout = now
    hours_passed = (now - last_payout) // 3600
    if hours_passed > 0:
        total_income = sum(int(apt.get("income", 0)) for apt in apartments)
        earned = total_income * hours_passed
        amount += earned
        last_payout += hours_passed * 3600
        return amount, last_payout, earned
    return amount, last_payout, 0

@app.get("/api/token_rates")
def get_rates():
    return get_current_rates()

@app.post("/api/set_name")
def set_name(req: SetNameRequest):
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET name = %s WHERE id = %s", (req.name, req.user_id))
        conn.commit()
        cursor.close(); conn.close()
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/balance/{user_id}")
def get_balance(user_id: int, name: str = "Игрок"):
    try:
        conn = get_db()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
        row = cursor.fetchone()
        now = int(time.time())
        
        if not row:
            card_num = "4" + "".join([str(random.randint(0, 9)) for _ in range(15)])
            card_formatted = " ".join([card_num[i:i+4] for i in range(0, 16, 4)])
            cvc = str(random.randint(100, 999))
            
            cursor.execute(
                "INSERT INTO users (id, name, amount, apartments, last_payout, card_number, card_cvc) VALUES (%s, %s, %s, %s, %s, %s, %s)", 
                (user_id, name, 140000, json.dumps([]), now, card_formatted, cvc)
            )
            conn.commit()
            cursor.close(); conn.close()
            return {"balance": 140000, "apartments": [], "earned": 0, "card_number": card_formatted, "card_cvc": cvc, "gold": 0, "diamonds": 0, "crypto": 0, "name": name}
            
        current_balance = int(row['amount'])
        user_apartments = row['apartments'] if isinstance(row['apartments'], list) else (json.loads(row['apartments']) if row['apartments'] else [])
        last_payout = int(row['last_payout']) if row['last_payout'] else now
        
        new_balance, new_last_payout, earned = calculate_income(current_balance, user_apartments, last_payout)
        
        # Имя не перезаписываем автоматически, если оно уже есть (чтобы кастомный ник не сбрасывался)
        if not row['name'] or row['name'] == "Игрок":
             cursor.execute("UPDATE users SET name = %s WHERE id = %s", (name, user_id))
             
        cursor.execute("UPDATE users SET amount = %s, last_payout = %s WHERE id = %s", (new_balance, new_last_payout, user_id))
        conn.commit()
        cursor.close(); conn.close()
            
        return {
            "balance": new_balance, "apartments": user_apartments, "earned": earned, 
            "card_number": row['card_number'], "card_cvc": row['card_cvc'],
            "gold": int(row.get('gold') or 0), "diamonds": int(row.get('diamonds') or 0), "crypto": int(row.get('crypto') or 0),
            "name": row['name']
        }
    except Exception as e:
        return {"balance": 0, "error": str(e)}

# --- СБРОС ВСЕХ ---
@app.post("/api/admin/reset_all")
def reset_all(req: AddMoneyRequest):
    if req.admin_id != MAIN_ADMIN_ID: return {"status": "error", "message": "Нет прав!"}
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("DROP TABLE IF EXISTS users;")
        conn.commit()
        cursor.close(); conn.close()
        init_db() # Пересоздаем пустую таблицу
        return {"status": "ok", "message": "Все игроки удалены, баланс сброшен до 140к!"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# ... остальные функции (trade_token, buy, sell, transfer, leaderboard) остаются без изменений ...
@app.post("/api/trade_token")
def trade_token(req: TokenRequest):
    rates = get_current_rates()
    if req.token_type not in rates: return {"status": "error", "message": "Неизвестный токен"}
    if req.amount <= 0 or req.amount > 1000000: return {"status": "error", "message": "Неверное количество"}
    rate = rates[req.token_type]; cost = req.amount * rate
    try:
        conn = get_db(); cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT * FROM users WHERE id = %s", (req.user_id,)); row = cursor.fetchone()
        if not row: return {"status": "error", "message": "Игрок не найден"}
        if req.action == "buy":
            if int(row['amount']) < cost: return {"status": "error", "message": "Недостаточно денег!"}
            cursor.execute(f"UPDATE users SET amount = amount - %s, {req.token_type} = COALESCE({req.token_type}, 0) + %s WHERE id = %s", (cost, req.amount, req.user_id))
        elif req.action == "sell":
            if int(row.get(req.token_type) or 0) < req.amount: return {"status": "error", "message": "Недостаточно токенов!"}
            cursor.execute(f"UPDATE users SET amount = amount + %s, {req.token_type} = COALESCE({req.token_type}, 0) - %s WHERE id = %s", (cost, req.amount, req.user_id))
        conn.commit(); cursor.close(); conn.close()
        return {"status": "ok", "message": "Сделка успешна!"}
    except Exception as e: return {"status": "error", "message": str(e)}

@app.post("/api/buy")
def buy_apartment(req: BuyRequest):
    try:
        conn = get_db(); cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT amount, apartments, last_payout FROM users WHERE id = %s", (req.user_id,)); row = cursor.fetchone()
        current_balance = int(row['amount']); user_apartments = row['apartments'] if isinstance(row['apartments'], list) else (json.loads(row['apartments']) if row['apartments'] else [])
        last_payout = int(row['last_payout']) if row['last_payout'] else int(time.time())
        current_balance, last_payout, _ = calculate_income(current_balance, user_apartments, last_payout)
        if current_balance < req.price: return {"status": "error", "message": "Недостаточно средств!"}
        new_balance = current_balance - req.price
        user_apartments.append({"name": req.apartment_name, "income": req.income, "buy_price": req.price})
        cursor.execute("UPDATE users SET amount = %s, apartments = %s, last_payout = %s WHERE id = %s", (new_balance, json.dumps(user_apartments), last_payout, req.user_id))
        conn.commit(); cursor.close(); conn.close()
        return {"status": "ok", "message": "Куплено!"}
    except Exception as e: return {"status": "error", "message": str(e)}

@app.post("/api/sell")
def sell_apartment(req: SellRequest):
    try:
        conn = get_db(); cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT amount, apartments, last_payout FROM users WHERE id = %s", (req.user_id,)); row = cursor.fetchone()
        current_balance = int(row['amount']); user_apartments = row['apartments'] if isinstance(row['apartments'], list) else (json.loads(row['apartments']) if row['apartments'] else [])
        last_payout = int(row['last_payout']) if row['last_payout'] else int(time.time())
        if req.apartment_index < 0 or req.apartment_index >= len(user_apartments): return {"status": "error", "message": "Не найдено"}
        sell_price = int(req.price * 0.7)
        current_balance, last_payout, _ = calculate_income(current_balance, user_apartments, last_payout)
        new_balance = current_balance + sell_price; user_apartments.pop(req.apartment_index)
        cursor.execute("UPDATE users SET amount = %s, apartments = %s, last_payout = %s WHERE id = %s", (new_balance, json.dumps(user_apartments), last_payout, req.user_id))
        conn.commit(); cursor.close(); conn.close()
        return {"status": "ok", "message": f"Продана за {sell_price} €"}
    except Exception as e: return {"status": "error", "message": str(e)}

@app.post("/api/transfer")
def transfer_money(req: TransferRequest):
    try:
        clean_card = req.card_number.replace(" ", "")
        conn = get_db(); cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT amount FROM users WHERE id = %s", (req.sender_id,)); sender = cursor.fetchone()
        if not sender or int(sender['amount']) < req.amount: return {"status": "error", "message": "Недостаточно средств!"}
        cursor.execute("SELECT id, name FROM users WHERE REPLACE(card_number, ' ', '') = %s AND card_cvc = %s", (clean_card, req.card_cvc)); receiver = cursor.fetchone()
        if not receiver: return {"status": "error", "message": "Игрок не найден!"}
        if receiver['id'] == req.sender_id: return {"status": "error", "message": "Это ваша карта!"}
        cursor.execute("UPDATE users SET amount = amount - %s WHERE id = %s", (req.amount, req.sender_id))
        cursor.execute("UPDATE users SET amount = amount + %s WHERE id = %s", (req.amount, receiver['id']))
        conn.commit(); cursor.close(); conn.close()
        return {"status": "ok", "message": f"Переведено {req.amount} € игроку {receiver['name']}"}
    except Exception as e: return {"status": "error", "message": str(e)}

@app.get("/api/leaderboard")
def get_leaderboard():
    try:
        conn = get_db(); cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT name, amount FROM users ORDER BY amount DESC LIMIT 5")
        rows = cursor.fetchall(); cursor.close(); conn.close()
        return {"leaders": [{"name": r['name'], "balance": int(r['amount'])} for r in rows]}
    except: return {"leaders": []}

@app.get("/api/admin/users")
def get_all_users():
    try:
        conn = get_db(); cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT id, name, amount, card_number, card_cvc FROM users")
        rows = cursor.fetchall(); cursor.close(); conn.close()
        return {"users": [{"id": r['id'], "name": r['name'], "balance": int(r['amount']), "card": r['card_number'], "cvc": r['card_cvc']} for r in rows]}
    except: return {"users": []}

@app.post("/api/admin/add_money")
def add_money(req: AddMoneyRequest):
    if req.admin_id != MAIN_ADMIN_ID: return {"status": "error", "message": "Нет прав!"}
    try:
        conn = get_db(); cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT amount FROM users WHERE id = %s", (req.target_id,)); row = cursor.fetchone()
        new_balance = int(row['amount']) + req.amount
        cursor.execute("UPDATE users SET amount = %s WHERE id = %s", (new_balance, req.target_id))
        conn.commit(); cursor.close(); conn.close()
        return {"status": "ok", "message": f"Выдано {req.amount} €"}
    except Exception as e: return {"status": "error", "message": str(e)}
