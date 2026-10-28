from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import sqlite3
import json

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_db():
    # Создаем подключение к базе данных
    conn = sqlite3.connect("game.db")
    return conn

class BuyRequest(BaseModel):
    user_id: int
    user_name: str
    apartment_name: str
    price: int
    income: int

@app.get("/api/balance/{user_id}")
def get_balance(user_id: int, name: str = "Игрок"):
    conn = get_db()
    cursor = conn.cursor()
    # Создаем таблицу, если её нет. Добавили колонку name (имя игрока)
    cursor.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, name TEXT, amount INTEGER, apartments TEXT DEFAULT '[]')")
    
    cursor.execute("SELECT amount, apartments FROM users WHERE id = ?", (user_id,))
    row = cursor.fetchone()
    
    if not row:
        # Если игрок зашел впервые, даем 100 000 €
        cursor.execute("INSERT INTO users (id, name, amount, apartments) VALUES (?, ?, ?, ?)", (user_id, name, 100000, '[]'))
        conn.commit()
        return {"balance": 100000, "apartments": []}
        
    # Обновляем имя на случай, если игрок сменил его в Telegram
    cursor.execute("UPDATE users SET name = ? WHERE id = ?", (name, user_id))
    conn.commit()
        
    return {"balance": row[0], "apartments": json.loads(row[1])}

@app.post("/api/buy")
def buy_apartment(req: BuyRequest):
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT amount, apartments FROM users WHERE id = ?", (req.user_id,))
    row = cursor.fetchone()
    
    if not row:
        return {"status": "error", "message": "Игрок не найден"}
        
    current_balance = row[0]
    user_apartments = json.loads(row[1])
    
    # Проверяем баланс
    if current_balance < req.price:
        return {"status": "error", "message": "Недостаточно средств!"}
        
    # Списываем деньги, добавляем квартиру
    new_balance = current_balance - req.price
    user_apartments.append({"name": req.apartment_name, "income": req.income})
    
    cursor.execute("UPDATE users SET amount = ?, apartments = ? WHERE id = ?", (new_balance, json.dumps(user_apartments), req.user_id))
    conn.commit()
    
    return {"status": "ok", "message": "Успешно куплено!", "new_balance": new_balance, "apartments": user_apartments}

@app.get("/api/leaderboard")
def get_leaderboard():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, name TEXT, amount INTEGER, apartments TEXT DEFAULT '[]')")
    # Берем топ-5 игроков по балансу
    cursor.execute("SELECT name, amount FROM users ORDER BY amount DESC LIMIT 5")
    rows = cursor.fetchall()
    return {"leaders": [{"name": r[0], "balance": r[1]} for r in rows]}
