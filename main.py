from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import sqlite3
import json
import time

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

MAIN_ADMIN_ID = 5634302903 # Твой ID

def get_db():
    conn = sqlite3.connect("game.db")
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
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, name TEXT, amount INTEGER, apartments TEXT DEFAULT '[]', last_payout INTEGER)")
    
    cursor.execute("SELECT amount, apartments, last_payout FROM users WHERE id = ?", (user_id,))
    row = cursor.fetchone()
    now = int(time.time())
    
    if not row:
        cursor.execute("INSERT INTO users (id, name, amount, apartments, last_payout) VALUES (?, ?, ?, ?, ?)", (user_id, name, 100000, '[]', now))
        conn.commit()
        return {"balance": 100000, "apartments": [], "earned": 0}
        
    current_balance = row[0]
    user_apartments = json.loads(row[1])
    last_payout = row[2]
    
    new_balance, new_last_payout, earned = calculate_income(current_balance, user_apartments, last_payout)
    cursor.execute("UPDATE users SET name = ?, amount = ?, last_payout = ? WHERE id = ?", (name, new_balance, new_last_payout, user_id))
    conn.commit()
        
    return {"balance": new_balance, "apartments": user_apartments, "earned": earned}

@app.post("/api/buy")
def buy_apartment(req: BuyRequest):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT amount, apartments, last_payout FROM users WHERE id = ?", (req.user_id,))
    row = cursor.fetchone()
    
    if not row:
        return {"status": "error", "message": "Игрок не найден"}
        
    current_balance = row[0]
    user_apartments = json.loads(row[1])
    last_payout = row[2]
    
    current_balance, last_payout, _ = calculate_income(current_balance, user_apartments, last_payout)
    
    if current_balance < req.price:
        return {"status": "error", "message": "Недостаточно средств!"}
        
    new_balance = current_balance - req.price
    user_apartments.append({"name": req.apartment_name, "income": req.income})
    
    cursor.execute("UPDATE users SET amount = ?, apartments = ?, last_payout = ? WHERE id = ?", (new_balance, json.dumps(user_apartments), last_payout, req.user_id))
    conn.commit()
    
    return {"status": "ok", "message": "Успешно куплено!", "new_balance": new_balance}

@app.get("/api/leaderboard")
def get_leaderboard():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, name TEXT, amount INTEGER, apartments TEXT DEFAULT '[]', last_payout INTEGER)")
    cursor.execute("SELECT name, amount FROM users ORDER BY amount DESC LIMIT 5")
    rows = cursor.fetchall()
    return {"leaders": [{"name": r[0], "balance": r[1]} for r in rows]}

# --- НОВЫЕ ЭНДПОИНТЫ ДЛЯ АДМИНА ---

@app.get("/api/admin/users")
def get_all_users():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, amount FROM users")
    rows = cursor.fetchall()
    # Возвращаем список всех игроков (ID, Имя, Баланс)
    return {"users": [{"id": r[0], "name": r[1], "balance": r[2]} for r in rows]}

@app.post("/api/admin/add_money")
def add_money(req: AddMoneyRequest):
    # Проверка, что запрос делает именно Главный Админ
    if req.admin_id != MAIN_ADMIN_ID:
        return {"status": "error", "message": "У вас нет прав!"}
        
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT amount FROM users WHERE id = ?", (req.target_id,))
    row = cursor.fetchone()
    
    if not row:
        return {"status": "error", "message": "Игрок не найден"}
        
    new_balance = row[0] + req.amount
    cursor.execute("UPDATE users SET amount = ? WHERE id = ?", (new_balance, req.target_id))
    conn.commit()
    
    return {"status": "ok", "message": f"Начислено {req.amount} € игроку {req.target_id}"}
