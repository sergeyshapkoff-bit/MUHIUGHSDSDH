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

def get_db():
    conn = sqlite3.connect("game.db")
    return conn

# Модель данных для покупки
class BuyRequest(BaseModel):
    user_id: int
    user_name: str
    apartment_name: str
    price: int
    income: int

# Вспомогательная функция для начисления дохода
def calculate_income(amount, apartments, last_payout):
    now = int(time.time())
    if not last_payout:
        last_payout = now
        
    time_passed = now - last_payout
    hours_passed = time_passed // 3600 # 1 час = 3600 секунд
    
    if hours_passed > 0:
        # Считаем общий доход в час со всех квартир
        total_income_per_hour = sum(apt.get("income", 0) for apt in apartments)
        earned = total_income_per_hour * hours_passed
        amount += earned
        
        # Обновляем время последней выплаты (чтобы остаток минут переносился)
        last_payout = last_payout + (hours_passed * 3600)
        
        return amount, last_payout, earned
    
    return amount, last_payout, 0

@app.get("/api/balance/{user_id}")
def get_balance(user_id: int, name: str = "Игрок"):
    conn = get_db()
    cursor = conn.cursor()
    # Добавили колонку last_payout (время последней выплаты)
    cursor.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, name TEXT, amount INTEGER, apartments TEXT DEFAULT '[]', last_payout INTEGER)")
    
    cursor.execute("SELECT amount, apartments, last_payout FROM users WHERE id = ?", (user_id,))
    row = cursor.fetchone()
    
    now = int(time.time())
    
    if not row:
        # Новый игрок: баланс 100 000, квартир нет, время выплаты - сейчас
        cursor.execute("INSERT INTO users (id, name, amount, apartments, last_payout) VALUES (?, ?, ?, ?, ?)", (user_id, name, 100000, '[]', now))
        conn.commit()
        return {"balance": 100000, "apartments": [], "earned": 0}
        
    current_balance = row[0]
    user_apartments = json.loads(row[1])
    last_payout = row[2]
    
    # Начисляем доход за прошедшее время
    new_balance, new_last_payout, earned = calculate_income(current_balance, user_apartments, last_payout)
    
    # Обновляем данные игрока (имя и новые деньги)
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
    
    # Перед покупкой сначала начисляем накопленное, чтобы баланс был актуальным
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
