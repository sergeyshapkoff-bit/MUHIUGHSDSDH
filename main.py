from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import psycopg2
from psycopg2.extras import RealDictCursor
import json
import time

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ВСТАВЬ СЮДА СВОЮ ССЫЛКУ ИЗ SUPABASE (замени ТВОЙ_ПАРОЛЬ на свой пароль)
DATABASE_URL = "postgresql://postgres:[1atP7cKaZFJInn5q]@db.zmfepxqnxcvkvdjonzhp.supabase.co:5432/postgres"

MAIN_ADMIN_ID = 5634302903 

def get_db():
    # Добавляем sslmode=require, иначе Supabase не пустит сервер
    url = DATABASE_URL
    if "?sslmode=require" not in url:
        url += "?sslmode=require"
    conn = psycopg2.connect(url)
    return conn

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
    if not last_payout:
        last_payout = now
        
    time_passed = now - last_payout
    hours_passed = time_passed // 3600
    
    if hours_passed > 0:
        total_income_per_hour = sum(apt.get("income", 0) for apt in apartments)
        earned = total_income_per_hour * hours_passed
        amount += earned
        last_payout = last_payout + (hours_passed * 3600)
        return amount, last_payout, earned
    
    return amount, last_payout, 0

@app.get("/api/balance/{user_id}")
def get_balance(user_id: int, name: str = "Игрок"):
    conn = get_db()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    cursor.execute("SELECT amount, apartments, last_payout FROM users WHERE id = %s", (user_id,))
    row = cursor.fetchone()
    now = int(time.time())
    
    if not row:
        # Новый игрок получает 100 000
        cursor.execute(
            "INSERT INTO users (id, name, amount, apartments, last_payout) VALUES (%s, %s, %s, %s, %s)", 
            (user_id, name, 100000, json.dumps([]), now)
        )
        conn.commit()
        cursor.close()
        conn.close()
        return {"balance": 100000, "apartments": [], "earned": 0}
        
    current_balance = row['amount']
    user_apartments = row['apartments'] if isinstance(row['apartments'], list) else json.loads(row['apartments'])
    last_payout = row['last_payout']
    
    new_balance, new_last_payout, earned = calculate_income(current_balance, user_apartments, last_payout)
    
    cursor.execute(
        "UPDATE users SET name = %s, amount = %s, last_payout = %s WHERE id = %s", 
        (name, new_balance, new_last_payout, user_id)
    )
    conn.commit()
    cursor.close()
    conn.close()
        
    return {"balance": new_balance, "apartments": user_apartments, "earned": earned}

@app.post("/api/buy")
def buy_apartment(req: BuyRequest):
    conn = get_db()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    cursor.execute("SELECT amount, apartments, last_payout FROM users WHERE id = %s", (req.user_id,))
    row = cursor.fetchone()
    
    if not row:
        cursor.close()
        conn.close()
        return {"status": "error", "message": "Игрок не найден"}
        
    current_balance = row['amount']
    user_apartments = row['apartments'] if isinstance(row['apartments'], list) else json.loads(row['apartments'])
    last_payout = row['last_payout']
    
    current_balance, last_payout, _ = calculate_income(current_balance, user_apartments, last_payout)
    
    if current_balance < req.price:
        cursor.close()
        conn.close()
        return {"status": "error", "message": "Недостаточно средств!"}
        
    new_balance = current_balance - req.price
    user_apartments.append({"name": req.apartment_name, "income": req.income})
    
    cursor.execute(
        "UPDATE users SET amount = %s, apartments = %s, last_payout = %s WHERE id = %s", 
        (new_balance, json.dumps(user_apartments), last_payout, req.user_id)
    )
    conn.commit()
    cursor.close()
    conn.close()
    
    return {"status": "ok", "message": "Успешно куплено!", "new_balance": new_balance}

@app.get("/api/leaderboard")
def get_leaderboard():
    conn = get_db()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute("SELECT name, amount FROM users ORDER BY amount DESC LIMIT 5")
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return {"leaders": [{"name": r['name'], "balance": r['amount']} for r in rows]}

@app.get("/api/admin/users")
def get_all_users():
    conn = get_db()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute("SELECT id, name, amount FROM users")
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return {"users": [{"id": r['id'], "name": r['name'], "balance": r['amount']} for r in rows]}

@app.post("/api/admin/add_money")
def add_money(req: AddMoneyRequest):
    if req.admin_id != MAIN_ADMIN_ID:
        return {"status": "error", "message": "У вас нет прав!"}
        
    conn = get_db()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute("SELECT amount FROM users WHERE id = %s", (req.target_id,))
    row = cursor.fetchone()
    
    if not row:
        cursor.close()
        conn.close()
        return {"status": "error", "message": "Игрок не найден"}
        
    new_balance = row['amount'] + req.amount
    cursor.execute("UPDATE users SET amount = %s WHERE id = %s", (new_balance, req.target_id))
    conn.commit()
    cursor.close()
    conn.close()
    
    return {"status": "ok", "message": f"Начислено {req.amount} € игроку {req.target_id}"}
