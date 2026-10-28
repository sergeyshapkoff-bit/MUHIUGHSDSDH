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
TOKEN_RATE = 1000 # 1 тыковка = 1000 евро

def get_db():
    return psycopg2.connect(DATABASE_URL)

def init_db():
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id bigint primary key,
                name text,
                amount bigint default 100000,
                apartments jsonb default '[]'::jsonb,
                last_payout bigint,
                card_number text,
                card_cvc text,
                tokens bigint default 0
            );
        """)
        # Добавляем колонки, если таблица уже есть
        try: cursor.execute("ALTER TABLE users ADD COLUMN card_number TEXT;")
        except: pass
        try: cursor.execute("ALTER TABLE users ADD COLUMN card_cvc TEXT;")
        except: pass
        try: cursor.execute("ALTER TABLE users ADD COLUMN tokens bigint default 0;")
        except: pass
        
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print("Ошибка инициализации БД:", e)

init_db()

# Модели данных
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
    amount: int # Сколько тыковок купить/продать

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
                "INSERT INTO users (id, name, amount, apartments, last_payout, card_number, card_cvc, tokens) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)", 
                (user_id, name, 100000, json.dumps([]), now, card_formatted, cvc, 0)
            )
            conn.commit()
            cursor.close(); conn.close()
            return {"balance": 100000, "apartments": [], "earned": 0, "card_number": card_formatted, "card_cvc": cvc, "tokens": 0}
            
        current_balance = int(row['amount'])
        user_apartments = row['apartments'] if isinstance(row['apartments'], list) else (json.loads(row['apartments']) if row['apartments'] else [])
        last_payout = int(row['last_payout']) if row['last_payout'] else now
        tokens = int(row['tokens']) if row['tokens'] else 0
        
        new_balance, new_last_payout, earned = calculate_income(current_balance, user_apartments, last_payout)
        
        cursor.execute("UPDATE users SET name = %s, amount = %s, last_payout = %s WHERE id = %s", (name, new_balance, new_last_payout, user_id))
        conn.commit()
        cursor.close(); conn.close()
            
        return {"balance": new_balance, "apartments": user_apartments, "earned": earned, "card_number": row['card_number'], "card_cvc": row['card_cvc'], "tokens": tokens}
    except Exception as e:
        return {"balance": 0, "error": str(e)}

# --- БИРЖА ТЫКОВОК ---
@app.post("/api/buy_tokens")
def buy_tokens(req: TokenRequest):
    try:
        conn = get_db()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT amount FROM users WHERE id = %s", (req.user_id,))
        row = cursor.fetchone()
        
        cost = req.amount * TOKEN_RATE
        if int(row['amount']) < cost:
            return {"status": "error", "message": "Недостаточно денег!"}
            
        cursor.execute("UPDATE users SET amount = amount - %s, tokens = tokens + %s WHERE id = %s", (cost, req.amount, req.user_id))
        conn.commit()
        cursor.close(); conn.close()
        return {"status": "ok", "message": f"Куплено {req.amount} 🎃"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/api/sell_tokens")
def sell_tokens(req: TokenRequest):
    try:
        conn = get_db()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT tokens FROM users WHERE id = %s", (req.user_id,))
        row = cursor.fetchone()
        
        if int(row['tokens']) < req.amount:
            return {"status": "error", "message": "Недостаточно тыковок!"}
            
        profit = req.amount * TOKEN_RATE
        cursor.execute("UPDATE users SET amount = amount + %s, tokens = tokens - %s WHERE id = %s", (profit, req.amount, req.user_id))
        conn.commit()
        cursor.close(); conn.close()
        return {"status": "ok", "message": f"Продано {req.amount} 🎃"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# Остальные функции без изменений...
@app.post("/api/buy")
def buy_apartment(req: BuyRequest):
    try:
        conn = get_db()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT amount, apartments, last_payout FROM users WHERE id = %s", (req.user_id,))
        row = cursor.fetchone()
        
        current_balance = int(row['amount'])
        user_apartments = row['apartments'] if isinstance(row['apartments'], list) else (json.loads(row['apartments']) if row['apartments'] else [])
        last_payout = int(row['last_payout']) if row['last_payout'] else int(time.time())
        
        current_balance, last_payout, _ = calculate_income(current_balance, user_apartments, last_payout)
        
        if current_balance < req.price:
            return {"status": "error", "message": "Недостаточно средств!"}
            
        new_balance = current_balance - req.price
        user_apartments.append({"name": req.apartment_name, "income": req.income, "buy_price": req.price})
        
        cursor.execute("UPDATE users SET amount = %s, apartments = %s, last_payout = %s WHERE id = %s", (new_balance, json.dumps(user_apartments), last_payout, req.user_id))
        conn.commit()
        cursor.close(); conn.close()
        return {"status": "ok", "message": "Успешно куплено!", "new_balance": new_balance}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/api/sell")
def sell_apartment(req: SellRequest):
    try:
        conn = get_db()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT amount, apartments, last_payout FROM users WHERE id = %s", (req.user_id,))
        row = cursor.fetchone()
        
        current_balance = int(row['amount'])
        user_apartments = row['apartments'] if isinstance(row['apartments'], list) else (json.loads(row['apartments']) if row['apartments'] else [])
        last_payout = int(row['last_payout']) if row['last_payout'] else int(time.time())
        
        if req.apartment_index < 0 or req.apartment_index >= len(user_apartments):
            return {"status": "error", "message": "Квартира не найдена"}
            
        sell_price = int(req.price * 0.7)
        current_balance, last_payout, _ = calculate_income(current_balance, user_apartments, last_payout)
        
        new_balance = current_balance + sell_price
        user_apartments.pop(req.apartment_index)
        
        cursor.execute("UPDATE users SET amount = %s, apartments = %s, last_payout = %s WHERE id = %s", (new_balance, json.dumps(user_apartments), last_payout, req.user_id))
        conn.commit()
        cursor.close(); conn.close()
        return {"status": "ok", "message": f"Квартира продана за {sell_price} €", "new_balance": new_balance}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/api/transfer")
def transfer_money(req: TransferRequest):
    try:
        if req.amount <= 0: return {"status": "error", "message": "Сумма должна быть больше 0"}
        clean_card = req.card_number.replace(" ", "")
        conn = get_db()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        cursor.execute("SELECT amount FROM users WHERE id = %s", (req.sender_id,))
        sender = cursor.fetchone()
        if not sender or int(sender['amount']) < req.amount: return {"status": "error", "message": "Недостаточно средств!"}
            
        cursor.execute("SELECT id, name FROM users WHERE card_number = %s AND card_cvc = %s", (clean_card, req.card_cvc))
        receiver = cursor.fetchone()
        if not receiver: return {"status": "error", "message": "Игрок с такой картой не найден!"}
        if receiver['id'] == req.sender_id: return {"status": "error", "message": "Нельзя перевести на свою карту!"}
            
        cursor.execute("UPDATE users SET amount = amount - %s WHERE id = %s", (req.amount, req.sender_id))
        cursor.execute("UPDATE users SET amount = amount + %s WHERE id = %s", (req.amount, receiver['id']))
        conn.commit()
        cursor.close(); conn.close()
        return {"status": "ok", "message": f"Переведено {req.amount} € игроку {receiver['name']}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/leaderboard")
def get_leaderboard():
    try:
        conn = get_db()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT name, amount FROM users ORDER BY amount DESC LIMIT 5")
        rows = cursor.fetchall()
        cursor.close(); conn.close()
        return {"leaders": [{"name": r['name'], "balance": int(r['amount'])} for r in rows]}
    except: return {"leaders": []}

@app.get("/api/admin/users")
def get_all_users():
    try:
        conn = get_db()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT id, name, amount, card_number, card_cvc FROM users")
        rows = cursor.fetchall()
        cursor.close(); conn.close()
        return {"users": [{"id": r['id'], "name": r['name'], "balance": int(r['amount']), "card": r['card_number'], "cvc": r['card_cvc']} for r in rows]}
    except: return {"users": []}

@app.post("/api/admin/add_money")
def add_money(req: AddMoneyRequest):
    if req.admin_id != MAIN_ADMIN_ID: return {"status": "error", "message": "Нет прав!"}
    try:
        conn = get_db()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT amount FROM users WHERE id = %s", (req.target_id,))
        row = cursor.fetchone()
        new_balance = int(row['amount']) + req.amount
        cursor.execute("UPDATE users SET amount = %s WHERE id = %s", (new_balance, req.target_id))
        conn.commit()
        cursor.close(); conn.close()
        return {"status": "ok", "message": f"Начислено {req.amount} €"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
