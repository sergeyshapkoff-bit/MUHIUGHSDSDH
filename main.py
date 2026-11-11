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

# --- ДИНАМИЧЕСКИЙ КУРС ТОКЕНОВ (С КОЛЕБАНИЯМИ) ---
def get_current_rates():
    hour = int(time.time()) // 3600
    rng = random.Random(hour)
    
    base_rates = {
        "silver": 50, "gold": 500, "diamonds": 5000, "bitcoin": 65000, "tesla": 250
    }
    
    rates = {}
    for token, base in base_rates.items():
        change = rng.uniform(-0.05, 0.05)
        price = int(base * (1 + change))
        trend = "up" if change > 0 else "down"
        rates[token] = {"price": price, "trend": trend}
    return rates

def init_db():
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id bigint primary key,
                name text,
                amount bigint default 220000,
                apartments jsonb default '[]'::jsonb,
                businesses jsonb default '[]'::jsonb,
                last_payout bigint,
                last_roll bigint default 0,
                daily_businesses jsonb default '[]'::jsonb,
                card_number text,
                card_cvc text
            );
        """)
        # Безопасное добавление колонок для старых баз
        cursor.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS businesses jsonb DEFAULT '[]'::jsonb;")
        cursor.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_roll bigint DEFAULT 0;")
        cursor.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS daily_businesses jsonb DEFAULT '[]'::jsonb;")
        conn.commit()
        cursor.close(); conn.close()
        print("БД успешно инициализирована!")
    except Exception as e:
        print("Ошибка БД:", e)

init_db()

# --- МОДЕЛИ ДАННЫХ ---
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
    receiver_id: int
    amount: int

class TokenRequest(BaseModel):
    user_id: int
    token_type: str
    amount: int
    action: str

class BusinessBuyRequest(BaseModel):
    user_id: int
    business_index: int

class SetNameRequest(BaseModel):
    user_id: int
    name: str

class AdminMoneyRequest(BaseModel):
    admin_id: int
    target_id: int
    amount: int

# --- ЛОГИКА ---
def calculate_income(amount, apartments, businesses, last_payout):
    now = int(time.time())
    if not last_payout: last_payout = now
    hours_passed = (now - last_payout) // 3600
    if hours_passed > 0:
        apt_income = sum(int(apt.get("income", 0)) for apt in apartments)
        bus_income = sum(int(bus.get("income", 0)) for bus in businesses)
        total_income = apt_income + bus_income
        
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
        conn = get_db(); cursor = conn.cursor()
        cursor.execute("UPDATE users SET name = %s WHERE id = %s", (req.name, req.user_id))
        conn.commit(); cursor.close(); conn.close()
        return {"status": "ok"}
    except: return {"status": "error"}

@app.get("/api/all_users")
def get_all_users_for_transfer():
    try:
        conn = get_db(); cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT id, name FROM users ORDER BY amount DESC LIMIT 50")
        rows = cursor.fetchall(); cursor.close(); conn.close()
        return {"users": [{"id": r['id'], "name": r['name']} for r in rows]}
    except: return {"users": []}

# --- БИЗНЕСЫ ---
BUSINESS_POOL = [
    {"name": "Киоск", "rarity": "Common", "price": 50000, "income": 1000, "req": 1},
    {"name": "Кофейня", "rarity": "Rare", "price": 250000, "income": 6000, "req": 2},
    {"name": "Автосервис", "rarity": "Epic", "price": 1500000, "income": 40000, "req": 3},
    {"name": "Завод", "rarity": "Mythic", "price": 15000000, "income": 450000, "req": 5},
    {"name": "Нефтевышка", "rarity": "Legendary", "price": 150000000, "income": 5000000, "req": 8},
    {"name": "Космопорт", "rarity": "Chromatic", "price": 2000000000, "income": 80000000, "req": 12}
]

@app.get("/api/businesses/{user_id}")
def get_businesses(user_id: int):
    try:
        conn = get_db(); cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT last_roll, daily_businesses FROM users WHERE id = %s", (user_id,))
        row = cursor.fetchone()
        
        now = int(time.time())
        if now - int(row['last_roll'] or 0) > 86400:
            rolled = random.sample(BUSINESS_POOL, 2)
            cursor.execute("UPDATE users SET last_roll = %s, daily_businesses = %s WHERE id = %s", (now, json.dumps(rolled), user_id))
            conn.commit()
            daily = rolled
        else:
            daily = row['daily_businesses'] if isinstance(row['daily_businesses'], list) else json.loads(row['daily_businesses'] or '[]')
            
        cursor.close(); conn.close()
        return {"businesses": daily}
    except Exception as e: 
        print("Ошибка бизнесов:", e)
        return {"businesses": []}

@app.post("/api/buy_business")
def buy_business(req: BusinessBuyRequest):
    try:
        conn = get_db(); cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT amount, apartments, businesses, daily_businesses FROM users WHERE id = %s", (req.user_id,))
        row = cursor.fetchone()
        
        daily = row['daily_businesses'] if isinstance(row['daily_businesses'], list) else json.loads(row['daily_businesses'] or '[]')
        owned = row['businesses'] if isinstance(row['businesses'], list) else json.loads(row['businesses'] or '[]')
        apts = row['apartments'] if isinstance(row['apartments'], list) else json.loads(row['apartments'] or '[]')
        
        if req.business_index < 0 or req.business_index >= len(daily):
            return {"status": "error", "message": "Бизнес не найден"}
            
        bus = daily[req.business_index]
        
        if len(apts) < bus['req']:
            return {"status": "error", "message": f"Нужно минимум {bus['req']} квартир!"}
            
        if int(row['amount']) < bus['price']:
            return {"status": "error", "message": "Недостаточно денег!"}
            
        new_amount = int(row['amount']) - bus['price']
        owned.append({"name": bus['name'], "income": bus['income'], "rarity": bus['rarity']})
        daily.pop(req.business_index)
        
        cursor.execute("UPDATE users SET amount = %s, businesses = %s, daily_businesses = %s WHERE id = %s", 
                       (new_amount, json.dumps(owned), json.dumps(daily), req.user_id))
        conn.commit(); cursor.close(); conn.close()
        return {"status": "ok", "message": f"Куплен бизнес {bus['name']}!"}
    except Exception as e: return {"status": "error", "message": str(e)}

@app.get("/api/balance/{user_id}")
def get_balance(user_id: int, name: str = "Игрок"):
    try:
        conn = get_db(); cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
        row = cursor.fetchone()
        now = int(time.time())
        
        if not row:
            card_num = "4" + "".join([str(random.randint(0, 9)) for _ in range(15)])
            card_formatted = " ".join([card_num[i:i+4] for i in range(0, 16, 4)])
            cvc = str(random.randint(100, 999))
            
            cursor.execute(
                "INSERT INTO users (id, name, amount, apartments, businesses, last_payout, card_number, card_cvc) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)", 
                (user_id, name, 220000, json.dumps([]), json.dumps([]), now, card_formatted, cvc)
            )
            conn.commit(); cursor.close(); conn.close()
            return {"balance": 220000, "apartments": [], "businesses": [], "earned": 0, "card_number": card_formatted, "card_cvc": cvc, "name": name}
            
        current_balance = int(row['amount'])
        user_apartments = row['apartments'] if isinstance(row['apartments'], list) else (json.loads(row['apartments']) if row['apartments'] else [])
        user_businesses = row['businesses'] if isinstance(row['businesses'], list) else (json.loads(row['businesses']) if row['businesses'] else [])
        last_payout = int(row['last_payout']) if row['last_payout'] else now
        
        new_balance, new_last_payout, earned = calculate_income(current_balance, user_apartments, user_businesses, last_payout)
        
        cursor.execute("UPDATE users SET amount = %s, last_payout = %s WHERE id = %s", (new_balance, new_last_payout, user_id))
        conn.commit(); cursor.close(); conn.close()
            
        return {
            "balance": new_balance, "apartments": user_apartments, "businesses": user_businesses, "earned": earned, 
            "card_number": row['card_number'], "card_cvc": row['card_cvc'], "name": row['name']
        }
    except Exception as e: 
        print("ОШИБКА БАЛАНСА:", e)
        return {"balance": 0, "error": str(e)}

@app.post("/api/trade_token")
def trade_token(req: TokenRequest):
    rates = get_current_rates()
    if req.token_type not in rates: return {"status": "error", "message": "Токен недоступен"}
    rate = rates[req.token_type]['price']; cost = req.amount * rate
    try:
        conn = get_db(); cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT amount FROM users WHERE id = %s", (req.user_id,)); row = cursor.fetchone()
        if req.action == "buy":
            if int(row['amount']) < cost: return {"status": "error", "message": "Мало денег!"}
            cursor.execute(f"UPDATE users SET amount = amount - %s WHERE id = %s", (cost, req.user_id))
        elif req.action == "sell":
            cursor.execute(f"UPDATE users SET amount = amount + %s WHERE id = %s", (cost, req.user_id))
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
        if req.apartment_index < 0 or req.apartment_index >= len(user_apartments): return {"status": "error", "message": "Не найдено"}
        sell_price = int(req.price * 0.7)
        new_balance = current_balance + sell_price; user_apartments.pop(req.apartment_index)
        cursor.execute("UPDATE users SET amount = %s, apartments = %s WHERE id = %s", (new_balance, json.dumps(user_apartments), req.user_id))
        conn.commit(); cursor.close(); conn.close()
        return {"status": "ok", "message": f"Продана за {sell_price} $"}
    except Exception as e: return {"status": "error", "message": str(e)}

@app.post("/api/transfer")
def transfer_money(req: TransferRequest):
    try:
        if req.amount <= 0: return {"status": "error", "message": "Неверная сумма"}
        conn = get_db(); cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT amount FROM users WHERE id = %s", (req.sender_id,)); sender = cursor.fetchone()
        if not sender or int(sender['amount']) < req.amount: return {"status": "error", "message": "Мало средств"}
        cursor.execute("SELECT id, name FROM users WHERE id = %s", (req.receiver_id,)); receiver = cursor.fetchone()
        if not receiver: return {"status": "error", "message": "Игрок не найден"}
        cursor.execute("UPDATE users SET amount = amount - %s WHERE id = %s", (req.amount, req.sender_id))
        cursor.execute("UPDATE users SET amount = amount + %s WHERE id = %s", (req.amount, req.receiver_id))
        conn.commit(); cursor.close(); conn.close()
        return {"status": "ok", "message": f"Переведено {req.amount} $ игроку {receiver['name']}"}
    except Exception as e: return {"status": "error", "message": str(e)}

@app.get("/api/leaderboard")
def get_leaderboard():
    try:
        conn = get_db(); cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT name, amount FROM users ORDER BY amount DESC LIMIT 5")
        rows = cursor.fetchall(); cursor.close(); conn.close()
        return {"leaders": [{"name": r['name'], "balance": int(r['amount'])} for r in rows]}
    except: return {"leaders": []}

# --- АДМИНКА ---
@app.get("/api/admin/users")
def admin_get_users(admin_id: int):
    if admin_id != MAIN_ADMIN_ID: return {"users": []}
    try:
        conn = get_db(); cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT id, name, amount, apartments FROM users")
        rows = cursor.fetchall(); cursor.close(); conn.close()
        return {"users": [{"id": r['id'], "name": r['name'], "balance": int(r['amount']), "apts_count": len(json.loads(r['apartments'] or '[]'))} for r in rows]}
    except: return {"users": []}

@app.post("/api/admin/remove_money")
def admin_remove_money(req: AdminMoneyRequest):
    if req.admin_id != MAIN_ADMIN_ID: return {"status": "error", "message": "Нет прав"}
    try:
        conn = get_db(); cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT amount FROM users WHERE id = %s", (req.target_id,)); row = cursor.fetchone()
        new_balance = max(0, int(row['amount']) - req.amount)
        cursor.execute("UPDATE users SET amount = %s WHERE id = %s", (new_balance, req.target_id))
        conn.commit(); cursor.close(); conn.close()
        return {"status": "ok", "message": f"Списано {req.amount} $"}
    except: return {"status": "error", "message": "Ошибка"}

@app.get("/api/admin/user_apartments/{user_id}")
def admin_get_user_apts(user_id: int):
    try:
        conn = get_db(); cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT apartments FROM users WHERE id = %s", (user_id,))
        row = cursor.fetchone(); cursor.close(); conn.close()
        return {"apartments": json.loads(row['apartments'] or '[]')}
    except: return {"apartments": []}
