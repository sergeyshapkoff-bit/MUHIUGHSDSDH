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

# Твоя ссылка на базу данных Supabase
DATABASE_URL = "postgresql://postgres.zmfepxqnxcvkvdjonzhp:p0LwFeRg9NJ7Cusj@aws-0-eu-west-1.pooler.supabase.com:5432/postgres?sslmode=require"

MAIN_ADMIN_ID = 5634302903 

def get_db():
    return psycopg2.connect(DATABASE_URL)

class BuyRequest(BaseModel):
    user_id: int
    user_name: str
    apartment_name: str
    price: int
    income: int

class AddMoneyRequest(BaseModel):
    admin_id: int
    target_id: int
    amount: int

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
            # Генерируем карту для нового игрока
            card_num = "4" + "".join([str(random.randint(0, 9)) for _ in range(15)])
            card_formatted = " ".join([card_num[i:i+4] for i in range(0, 16, 4)])
            cvc = str(random.randint(100, 999))
            
            cursor.execute(
                "INSERT INTO users (id, name, amount, apartments, last_payout, card_number, card_cvc) VALUES (%s, %s, %s, %s, %s, %s, %s)", 
                (user_id, name, 100000, json.dumps([]), now, card_formatted, cvc)
            )
            conn.commit()
            cursor.close(); conn.close()
            return {"balance": 100000, "apartments": [], "earned": 0, "card_number": card_formatted, "card_cvc": cvc}
            
        current_balance = int(row['amount'])
        user_apartments = row['apartments'] if isinstance(row['apartments'], list) else json.loads(row['apartments'])
        last_payout = int(row['last_payout']) if row['last_payout'] else now
        
        new_balance, new_last_payout, earned = calculate_income(current_balance, user_apartments, last_payout)
        
        cursor.execute("UPDATE users SET name = %s, amount = %s, last_payout = %s WHERE id = %s", (name, new_balance, new_last_payout, user_id))
        conn.commit()
        cursor.close(); conn.close()
            
        return {"balance": new_balance, "apartments": user_apartments, "earned": earned, "card_number": row['card_number'], "card_cvc": row['card_cvc']}
    except Exception as e:
        return {"balance": 0, "error": str(e)}

@app.post("/api/buy")
def buy_apartment(req: BuyRequest):
    try:
        conn = get_db()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT amount, apartments, last_payout FROM users WHERE id = %s", (req.user_id,))
        row = cursor.fetchone()
        
        current_balance = int(row['amount'])
        user_apartments = row['apartments'] if isinstance(row['apartments'], list) else json.loads(row['apartments'])
        last_payout = int(row['last_payout']) if row['last_payout'] else int(time.time())
        
        current_balance, last_payout, _ = calculate_income(current_balance, user_apartments, last_payout)
        
        if current_balance < req.price:
            return {"status": "error", "message": "Недостаточно средств!"}
            
        new_balance = current_balance - req.price
        user_apartments.append({"name": req.apartment_name, "income": req.income})
        
        cursor.execute("UPDATE users SET amount = %s, apartments = %s, last_payout = %s WHERE id = %s", (new_balance, json.dumps(user_apartments), last_payout, req.user_id))
        conn.commit()
        cursor.close(); conn.close()
        return {"status": "ok", "message": "Успешно куплено!", "new_balance": new_balance}
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
