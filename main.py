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
    conn = sqlite3.connect("game.db")
    return conn

# Модель данных для покупки
class BuyRequest(BaseModel):
    user_id: int
    apartment_name: str
    price: int
    income: int

@app.get("/api/balance/{user_id}")
def get_balance(user_id: int):
    conn = get_db()
    cursor = conn.cursor()
    # Создаем таблицу пользователей (добавили колонку apartments)
    cursor.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, amount INTEGER, apartments TEXT DEFAULT '[]')")
    
    cursor.execute("SELECT amount, apartments FROM users WHERE id = ?", (user_id,))
    row = cursor.fetchone()
    
    if not row:
        # Даем новому игроку 100 000 евро на старт, чтобы он мог купить первую квартиру
        cursor.execute("INSERT INTO users (id, amount, apartments) VALUES (?, ?, ?)", (user_id, 100000, '[]'))
        conn.commit()
        return {"balance": 100000, "apartments": []}
        
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
    
    # Проверяем, хватает ли денег
    if current_balance < req.price:
        return {"status": "error", "message": "Недостаточно средств!"}
        
    # Списываем деньги и добавляем квартиру
    new_balance = current_balance - req.price
    user_apartments.append({"name": req.apartment_name, "income": req.income})
    
    cursor.execute("UPDATE users SET amount = ?, apartments = ? WHERE id = ?", (new_balance, json.dumps(user_apartments), req.user_id))
    conn.commit()
    
    return {"status": "ok", "message": "Успешно куплено!", "new_balance": new_balance, "apartments": user_apartments}
