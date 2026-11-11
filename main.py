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

def is_admin(uid):
    if uid == MAIN_ADMIN_ID: return True
    try:
        conn = get_db(); cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM admins WHERE user_id = %s", (uid,))
        res = cursor.fetchone(); cursor.close(); conn.close()
        return bool(res)
    except: return False

def get_current_rates():
    hour = int(time.time()) // 3600
    rng = random.Random(hour)
    base_rates = {"silver": 50, "gold": 500, "diamonds": 5000, "bitcoin": 65000, "tesla": 250}
    rates = {}
    for token, base in base_rates.items():
        change = rng.uniform(-0.05, 0.05)
        price = int(base * (1 + change))
        trend = "up" if change > 0 else "down"
        rates[token] = {"price": price, "trend": trend}
    return rates

DEFAULT_COMPANIES = [
    {"name": "Эконом - Класс", "tiers": [
        {"name": "«Заречный парк»", "price": 25000, "income": 210},
        {"name": "«Соколиный край»", "price": 55000, "income": 600},
        {"name": "Остров «Фарбс»", "price": 100000, "income": 1000}
    ]},
    {"name": "Комфорт - Класс", "tiers": [
        {"name": "«Панелька»", "price": 155000, "income": 1350},
        {"name": "ЖК «Мапид»", "price": 300000, "income": 3000},
        {"name": "ЖК «Ясно.Янино»", "price": 660000, "income": 5700},
        {"name": "«Алма Сити»", "price": 1150000, "income": 12000}
    ]},
    {"name": "Премиум - Комфорт", "tiers": [
        {"name": "ЖК «Солнечный»", "price": 3000000, "income": 32000},
        {"name": "«Кирпичный Дом»", "price": 8000000, "income": 55500},
        {"name": "ЖК «Новая Боровая»", "price": 12500000, "income": 140000}
    ]},
    {"name": "Бизнес - Класс", "tiers": [
        {"name": "ЖК «DEPO»", "price": 50000000, "income": 1345600},
        {"name": "ЖК «Минск-Мир»", "price": 100000000, "income": 3000000}
    ]},
    {"name": "Люкс", "tiers": [
        {"name": "Пентхаус", "price": 125500555, "income": 6000007}
    ]},
    {"name": "Бизнес - Люкс", "tiers": [
        {"name": "ЖК «Малиновка»", "price": 222200000, "income": 8000000},
        {"name": "ЖК «Небосреб 2.0»", "price": 500000000, "income": 10500000},
        {"name": "ЖК «Клевер парк»", "price": 1000000000, "income": 25550975},
        {"name": "ЖК «Последняя Слеза»", "price": 5000000000, "income": 100000000}
    ]}
]

def init_db():
    try:
        conn = get_db()
        cursor = conn.cursor()
        # Добавили колонку portfolio
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id bigint primary key, name text, amount bigint default 220000,
                apartments jsonb default '[]'::jsonb, businesses jsonb default '[]'::jsonb,
                last_payout bigint, last_roll bigint default 0, daily_businesses jsonb default '[]'::jsonb,
                card_number text, card_cvc text, portfolio jsonb default '{}'::jsonb
            );
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS companies (
                id serial primary key, name text, tiers jsonb default '[]'::jsonb
            );
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                user_id bigint primary key
            );
        """)
        
        # Безопасное добавление колонки на случай, если таблица уже была создана
        cursor.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS portfolio jsonb DEFAULT '{}'::jsonb;")
        
        conn.commit()
        
        cursor.execute("SELECT COUNT(*) FROM companies")
        if cursor.fetchone()[0] == 0:
            for comp in DEFAULT_COMPANIES:
                cursor.execute("INSERT INTO companies (name, tiers) VALUES (%s, %s)", (comp['name'], json.dumps(comp['tiers'])))
            conn.commit()
            
        cursor.close()
        conn.close()
    except Exception as e: 
        print("Ошибка БД:", e)

init_db()

class BuyRequest(BaseModel):
    user_id: int; user_name: str; apartment_name: str; price: int; income: int
class SellRequest(BaseModel):
    user_id: int; apartment_index: int; price: int
class TransferRequest(BaseModel):
    sender_id: int; receiver_id: int; amount: int
class TokenRequest(BaseModel):
    user_id: int; token_type: str; amount: int; action: str
class BusinessBuyRequest(BaseModel):
    user_id: int; business_index: int
class SetNameRequest(BaseModel):
    user_id: int; name: str
class AdminMoneyRequest(BaseModel):
    admin_id: int; target_id: int; amount: int
class AdminCompanyRequest(BaseModel):
    admin_id: int; company_name: str; tier_data: dict = None
class AdminAdminRequest(BaseModel):
    admin_id: int; target_id: int

def safe_json_load(data, default):
    if isinstance(data, str):
        try: return json.loads(data)
        except: return default
    elif isinstance(data, (list, dict)): return data
    return default

def calculate_income(amount, apartments, businesses, last_payout):
    now = int(time.time())
    if not last_payout: last_payout = now
    hours_passed = (now - last_payout) // 3600
    if hours_passed > 0:
        apt_inc = sum(int(a.get("income", 0)) for a in apartments if isinstance(a, dict))
        bus_inc = sum(int(b.get("income", 0)) for b in businesses if isinstance(b, dict))
        earned = (apt_inc + bus_inc) * hours_passed
        amount += earned
        last_payout += hours_passed * 3600
        return amount, last_payout, earned
    return amount, last_payout, 0

@app.get("/api/check_admin/{user_id}")
def check_admin(user_id: int):
    return {"is_admin": is_admin(user_id)}

@app.post("/api/admin/add_admin")
def add_admin(req: AdminAdminRequest):
    if req.admin_id != MAIN_ADMIN_ID: return {"status": "error", "message": "Только Главный админ может добавлять"}
    try:
        conn = get_db(); cursor = conn.cursor()
        cursor.execute("INSERT INTO admins (user_id) VALUES (%s) ON CONFLICT DO NOTHING", (req.target_id,))
        conn.commit(); cursor.close(); conn.close()
        return {"status": "ok", "message": "Админ добавлен!"}
    except Exception as e: return {"status": "error", "message": str(e)}

@app.post("/api/admin/remove_admin")
def remove_admin(req: AdminAdminRequest):
    if req.admin_id != MAIN_ADMIN_ID: return {"status": "error", "message": "Только Главный админ может удалять"}
    try:
        conn = get_db(); cursor = conn.cursor()
        cursor.execute("DELETE FROM admins WHERE user_id = %s", (req.target_id,))
        conn.commit(); cursor.close(); conn.close()
        return {"status": "ok", "message": "Админ удален!"}
    except Exception as e: return {"status": "error", "message": str(e)}

@app.get("/api/admin/list_admins")
def list_admins(admin_id: int):
    if not is_admin(admin_id): return {"admins": []}
    try:
        conn = get_db(); cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM admins")
        rows = cursor.fetchall()
        cursor.close(); conn.close()
        admins = [MAIN_ADMIN_ID] + [r[0] for r in rows]
        return {"admins": admins}
    except: return {"admins": [MAIN_ADMIN_ID]}

@app.get("/api/token_rates")
def get_rates(): return get_current_rates()

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

@app.get("/api/companies")
def get_companies():
    try:
        conn = get_db(); cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT id, name, tiers FROM companies ORDER BY id ASC")
        rows = cursor.fetchall(); cursor.close(); conn.close()
        return {"companies": [{"id": r['id'], "name": r['name'], "tiers": safe_json_load(r['tiers'], [])} for r in rows]}
    except: return {"companies": []}

@app.post("/api/admin/add_company")
def add_company(req: AdminCompanyRequest):
    if not is_admin(req.admin_id): return {"status": "error"}
    try:
        conn = get_db(); cursor = conn.cursor()
        cursor.execute("INSERT INTO companies (name, tiers) VALUES (%s, %s)", (req.company_name, '[]'))
        conn.commit(); cursor.close(); conn.close()
        return {"status": "ok", "message": "Компания добавлена!"}
    except: return {"status": "error"}

@app.post("/api/admin/add_tier/{company_id}")
def add_tier(company_id: int, req: AdminCompanyRequest):
    if not is_admin(req.admin_id): return {"status": "error"}
    try:
        conn = get_db(); cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT tiers FROM companies WHERE id = %s", (company_id,))
        row = cursor.fetchone()
        tiers = safe_json_load(row['tiers'], [])
        tiers.append(req.tier_data)
        cursor.execute("UPDATE companies SET tiers = %s WHERE id = %s", (json.dumps(tiers), company_id))
        conn.commit(); cursor.close(); conn.close()
        return {"status": "ok", "message": "Тариф добавлен!"}
    except Exception as e: return {"status": "error", "message": str(e)}

@app.post("/api/admin/delete_company/{company_id}")
def delete_company(company_id: int, req: AdminCompanyRequest):
    if not is_admin(req.admin_id): return {"status": "error"}
    try:
        conn = get_db(); cursor = conn.cursor()
        cursor.execute("DELETE FROM companies WHERE id = %s", (company_id,))
        conn.commit(); cursor.close(); conn.close()
        return {"status": "ok", "message": "Компания удалена!"}
    except: return {"status": "error"}

BUSINESS_POOL = [
    {"name": "Киоск", "rarity": "Common", "price": 50000, "income": 1000, "req": 1, "weight": 50},
    {"name": "Кофейня", "rarity": "Rare", "price": 250000, "income": 6000, "req": 2, "weight": 25},
    {"name": "Автосервис", "rarity": "Epic", "price": 1500000, "income": 40000, "req": 3, "weight": 15},
    {"name": "Завод", "rarity": "Mythic", "price": 15000000, "income": 450000, "req": 5, "weight": 7},
    {"name": "Нефтевышка", "rarity": "Legendary", "price": 150000000, "income": 5000000, "req": 8, "weight": 2.5},
    {"name": "Космопорт", "rarity": "Chromatic", "price": 2000000000, "income": 80000000, "req": 12, "weight": 0.5}
]

def get_weighted_business():
    total_weight = sum(b['weight'] for b in BUSINESS_POOL)
    r = random.uniform(0, total_weight)
    upto = 0
    for b in BUSINESS_POOL:
        if upto + b['weight'] >= r: return b
        upto += b['weight']
    return BUSINESS_POOL[0]

@app.get("/api/businesses/{user_id}")
def get_businesses(user_id: int):
    try:
        conn = get_db(); cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT last_roll, daily_businesses FROM users WHERE id = %s", (user_id,))
        row = cursor.fetchone()
        now = int(time.time())
        if now - int(row['last_roll'] or 0) > 86400:
            rolled = []
            while len(rolled) < 2:
                b = get_weighted_business()
                if b not in rolled: rolled.append(b)
            cursor.execute("UPDATE users SET last_roll = %s, daily_businesses = %s WHERE id = %s", (now, json.dumps(rolled), user_id))
            conn.commit(); daily = rolled
        else:
            daily = safe_json_load(row['daily_businesses'], [])
        cursor.close(); conn.close()
        return {"businesses": daily}
    except: return {"businesses": []}

@app.post("/api/buy_business")
def buy_business(req: BusinessBuyRequest):
    try:
        conn = get_db(); cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT amount, apartments, businesses, daily_businesses FROM users WHERE id = %s", (req.user_id,))
        row = cursor.fetchone()
        daily = safe_json_load(row['daily_businesses'], [])
        owned = safe_json_load(row['businesses'], [])
        apts = safe_json_load(row['apartments'], [])
        
        if req.business_index < 0 or req.business_index >= len(daily): return {"status": "error", "message": "Бизнес не найден"}
        bus = daily[req.business_index]
        if len(apts) < bus['req']: return {"status": "error", "message": f"Нужно минимум {bus['req']} квартир!"}
        if int(row['amount']) < bus['price']: return {"status": "error", "message": "Недостаточно денег!"}
            
        new_amount = int(row['amount']) - bus['price']
        owned.append({"name": bus['name'], "income": bus['income'], "rarity": bus['rarity']})
        daily.pop(req.business_index)
        cursor.execute("UPDATE users SET amount = %s, businesses = %s, daily_businesses = %s WHERE id = %s", (new_amount, json.dumps(owned), json.dumps(daily), req.user_id))
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
            cursor.execute("INSERT INTO users (id, name, amount, last_payout, card_number, card_cvc) VALUES (%s, %s, %s, %s, %s, %s)", (user_id, name, 220000, now, card_formatted, cvc))
            conn.commit(); cursor.close(); conn.close()
            return {"balance": 220000, "apartments": [], "businesses": [], "earned": 0, "card_number": card_formatted, "card_cvc": cvc, "name": name, "portfolio": {}}
            
        current_balance = int(row['amount'])
        user_apartments = safe_json_load(row['apartments'], [])
        user_businesses = safe_json_load(row['businesses'], [])
        user_portfolio = safe_json_load(row.get('portfolio'), {})
        last_payout = int(row['last_payout']) if row['last_payout'] else now
        
        new_balance, new_last_payout, earned = calculate_income(current_balance, user_apartments, user_businesses, last_payout)
        
        cursor.execute("UPDATE users SET amount = %s, last_payout = %s WHERE id = %s", (new_balance, new_last_payout, user_id))
        conn.commit(); cursor.close(); conn.close()
            
        return {"balance": new_balance, "apartments": user_apartments, "businesses": user_businesses, "earned": earned, "card_number": row['card_number'], "card_cvc": row['card_cvc'], "name": row['name'], "portfolio": user_portfolio}
    except Exception as e: return {"balance": 0, "error": str(e)}

@app.post("/api/trade_token")
def trade_token(req: TokenRequest):
    rates = get_current_rates()
    if req.token_type not in rates: return {"status": "error", "message": "Неизвестный токен"}
    
    cost = req.amount * rates[req.token_type]['price']
    
    try:
        conn = get_db(); cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT amount, portfolio FROM users WHERE id = %s", (req.user_id,))
        row = cursor.fetchone()
        
        portfolio = safe_json_load(row['portfolio'], {})
        current_qty = int(portfolio.get(req.token_type, 0))
        
        if req.action == "buy":
            if int(row['amount']) < cost: 
                return {"status": "error", "message": "Недостаточно денег!"}
            
            portfolio[req.token_type] = current_qty + req.amount
            cursor.execute("UPDATE users SET amount = amount - %s, portfolio = %s WHERE id = %s", (cost, json.dumps(portfolio), req.user_id))
            
        elif req.action == "sell":
            if current_qty < req.amount: 
                return {"status": "error", "message": "Недостаточно токенов!"}
            
            portfolio[req.token_type] = current_qty - req.amount
            cursor.execute("UPDATE users SET amount = amount + %s, portfolio = %s WHERE id = %s", (cost, json.dumps(portfolio), req.user_id))
            
        conn.commit(); cursor.close(); conn.close()
        return {"status": "ok", "message": "Сделка успешна!"}
    except Exception as e: 
        return {"status": "error", "message": str(e)}

@app.post("/api/buy")
def buy_apartment(req: BuyRequest):
    try:
        conn = get_db(); cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT amount, apartments FROM users WHERE id = %s", (req.user_id,)); row = cursor.fetchone()
        if int(row['amount']) < req.price: return {"status": "error", "message": "Мало средств!"}
        new_balance = int(row['amount']) - req.price
        user_apartments = safe_json_load(row['apartments'], [])
        user_apartments.append({"name": req.apartment_name, "income": req.income, "buy_price": req.price})
        cursor.execute("UPDATE users SET amount = %s, apartments = %s WHERE id = %s", (new_balance, json.dumps(user_apartments), req.user_id))
        conn.commit(); cursor.close(); conn.close()
        return {"status": "ok", "message": "Куплено!"}
    except Exception as e: return {"status": "error", "message": str(e)}

@app.post("/api/sell")
def sell_apartment(req: SellRequest):
    try:
        conn = get_db(); cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT amount, apartments FROM users WHERE id = %s", (req.user_id,)); row = cursor.fetchone()
        user_apartments = safe_json_load(row['apartments'], [])
        if req.apartment_index < 0 or req.apartment_index >= len(user_apartments): return {"status": "error"}
        sell_price = int(req.price * 0.7)
        new_balance = int(row['amount']) + sell_price
        user_apartments.pop(req.apartment_index)
        cursor.execute("UPDATE users SET amount = %s, apartments = %s WHERE id = %s", (new_balance, json.dumps(user_apartments), req.user_id))
        conn.commit(); cursor.close(); conn.close()
        return {"status": "ok", "message": f"Продана за {sell_price} $"}
    except: return {"status": "error"}

@app.post("/api/transfer")
def transfer_money(req: TransferRequest):
    try:
        conn = get_db(); cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT amount FROM users WHERE id = %s", (req.sender_id,)); sender = cursor.fetchone()
        if not sender or int(sender['amount']) < req.amount: return {"status": "error", "message": "Мало средств"}
        cursor.execute("SELECT id, name FROM users WHERE id = %s", (req.receiver_id,)); receiver = cursor.fetchone()
        if not receiver: return {"status": "error", "message": "Игрок не найден"}
        cursor.execute("UPDATE users SET amount = amount - %s WHERE id = %s", (req.amount, req.sender_id))
        cursor.execute("UPDATE users SET amount = amount + %s WHERE id = %s", (req.amount, req.receiver_id))
        conn.commit(); cursor.close(); conn.close()
        return {"status": "ok", "message": f"Переведено {req.amount} $ игроку {receiver['name']}"}
    except: return {"status": "error"}

@app.get("/api/leaderboard")
def get_leaderboard():
    try:
        conn = get_db(); cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT name, amount FROM users ORDER BY amount DESC LIMIT 5")
        rows = cursor.fetchall(); cursor.close(); conn.close()
        return {"leaders": [{"name": r['name'], "balance": int(r['amount'])} for r in rows]}
    except: return {"leaders": []}

@app.get("/api/admin/users")
def admin_get_users(admin_id: int):
    if not is_admin(admin_id): return {"users": []}
    try:
        conn = get_db(); cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT id, name, amount, apartments FROM users")
        rows = cursor.fetchall(); cursor.close(); conn.close()
        return {"users": [{"id": r['id'], "name": r['name'], "balance": int(r['amount']), "apts_count": len(safe_json_load(r['apartments'], []))} for r in rows]}
    except: return {"users": []}

@app.post("/api/admin/add_money")
def admin_add_money(req: AdminMoneyRequest):
    if not is_admin(req.admin_id): return {"status": "error", "message": "Нет прав"}
    try:
        conn = get_db(); cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT amount FROM users WHERE id = %s", (req.target_id,)); row = cursor.fetchone()
        new_balance = int(row['amount']) + req.amount
        cursor.execute("UPDATE users SET amount = %s WHERE id = %s", (new_balance, req.target_id))
        conn.commit(); cursor.close(); conn.close()
        return {"status": "ok", "message": f"Выдано {req.amount} $"}
    except: return {"status": "error", "message": "Ошибка"}

@app.post("/api/admin/remove_money")
def admin_remove_money(req: AdminMoneyRequest):
    if not is_admin(req.admin_id): return {"status": "error", "message": "Нет прав"}
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
        return {"apartments": safe_json_load(row['apartments'], [])}
    except: return {"apartments": []}

@app.post("/api/admin/reset_all")
def admin_reset_all(req: AdminMoneyRequest):
    if req.admin_id != MAIN_ADMIN_ID: return {"status": "error", "message": "Только Главный админ"}
    try:
        conn = get_db(); cursor = conn.cursor()
        cursor.execute("DELETE FROM users")
        conn.commit(); cursor.close(); conn.close()
        return {"status": "ok", "message": "Все игроки удалены!"}
    except Exception as e: return {"status": "error", "message": str(e)}
