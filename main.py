from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2 import OperationalError
import json, time, random, contextlib, hashlib

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

DATABASE_URL = "postgresql://postgres.zmfepxqnxcvkvdjonzhp:p0LwFeRg9NJ7Cusj@aws-0-eu-west-1.pooler.supabase.com:6543/postgres?sslmode=require"
MAIN_ADMIN_ID = 5634302903
SQM_TAX = 300              # Br за 1 м² в день
LOAN_LIMIT = 1000000       # Максимальная сумма кредита

BUSINESS_POOL = [
    {"name": "Киоск", "rarity": "Обычный", "price": 550000, "income": 4500, "req": 5, "weight": 1000},
    {"name": "Кофейня", "rarity": "Обычный", "price": 1000000, "income": 8200, "req": 7, "weight": 800},
    {"name": "Ресторан", "rarity": "Редкий", "price": 4500000, "income": 25750, "req": 10, "weight": 300},
    {"name": "Автомойка", "rarity": "Редкий", "price": 7500000, "income": 42000, "req": 2, "weight": 200},
    {"name": "Маленький", "rarity": "Редкий", "price": 10000000, "income": 61950, "req": 2, "weight": 150},
    {"name": "Пиццерия", "rarity": "Эпик", "price": 12000000, "income": 80000, "req": 3, "weight": 80},
    {"name": "Супермаркет", "rarity": "Эпик", "price": 15000000, "income": 44500, "req": 3, "weight": 70},
    {"name": "Киоск-Люкс", "rarity": "Эпик", "price": 18000000, "income": 100000, "req": 3, "weight": 60},
    {"name": "Фитнес-клуб", "rarity": "Эпик", "price": 35000000, "income": 185000, "req": 4, "weight": 50},
    {"name": "Нефтяная", "rarity": "Мифик", "price": 65000000, "income": 450500, "req": 5, "weight": 20},
    {"name": "Банк", "rarity": "Мифик", "price": 80000000, "income": 500000, "req": 6, "weight": 15},
    {"name": "офис", "rarity": "Мега", "price": 93850900, "income": 534550, "req": 5, "weight": 10},
    {"name": "Рынок", "rarity": "Мега", "price": 100500000, "income": 1150000, "req": 8, "weight": 5},
    {"name": "Автосалон", "rarity": "Мега", "price": 180000000, "income": 2000000, "req": 8, "weight": 4},
    {"name": "Элитный район", "rarity": "Мега", "price": 250000000, "income": 3000000, "req": 8, "weight": 3},
    {"name": "Небоскреб", "rarity": "Ультра", "price": 550000000, "income": 5600000, "req": 12, "weight": 2},
    {"name": "IT-компания", "rarity": "Ультра", "price": 750000000, "income": 8500000, "req": 13, "weight": 1},
    {"name": "Завод мини", "rarity": "Хром", "price": 1000500000, "income": 11600000, "req": 15, "weight": 0.5},
    {"name": "Аэропорт", "rarity": "Хром", "price": 2000000000, "income": 25000000, "req": 18, "weight": 0.1},
    {"name": "Космодром", "rarity": "Хром", "price": 5000000000, "income": 80000000, "req": 20, "weight": 0.01},
]

def get_business_pool_hash() -> str:
    return hashlib.md5(json.dumps(BUSINESS_POOL, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]

DEFAULT_EXCHANGE = [
    {"key": "gold", "name": "Золото", "min": 500, "max": 1200, "base": 850},
    {"key": "bitcoin", "name": "Биткоин", "min": 60000, "max": 72280, "base": 65000},
]

DEFAULT_COMPANIES = [
    {"name": "Эконом - Класс", "tiers": [
        {"name": "ЖК «Мапид»", "price": 200000, "income": 1650, "sqm": 7},
        {"name": "Грушевка", "price": 345000, "income": 2860, "sqm": 11},
        {"name": "ЖК «Малиновый Рай»", "price": 500000, "income": 3750, "sqm": 12}
    ]},
    {"name": "Комфорт - Класс", "tiers": [
        {"name": "ЖК «Новая Боровая»", "price": 1450000, "income": 10000, "sqm": 15},
        {"name": "Северный Берег", "price": 3000000, "income": 16500, "sqm": 15},
        {"name": "ЖК «Речной порт»", "price": 3500000, "income": 22000, "sqm": 23},
        {"name": "Михалово", "price": 5250000, "income": 29500, "sqm": 24},
        {"name": "ЖК «Саввинская 17»", "price": 11500000, "income": 55000, "sqm": 28},
        {"name": "ЖК «Изумрудный бор»", "price": 16700000, "income": 75000, "sqm": 31}
    ]},
    {"name": "Премиум - Комфорт", "tiers": [
        {"name": "ЖК - Minsk World", "price": 25000000, "income": 140500, "sqm": 35},
        {"name": "ЖК «Пирс»", "price": 27500000, "income": 185500, "sqm": 43}
    ]},
    {"name": "Бизнес - Класс", "tiers": [
        {"name": "ЖК «Солнечный»", "price": 35555500, "income": 250000, "sqm": 50},
        {"name": "ЖК «Зелёная гавань»", "price": 50000000, "income": 350000, "sqm": 50},
        {"name": "Квартал Depo", "price": 150000000, "income": 500000, "sqm": 50},
        {"name": "ЖК «Айвазовский City»", "price": 255000000, "income": 625000, "sqm": 55}
    ]},
    {"name": "Люкс", "tiers": [
        {"name": "Central Park Tower", "price": 500000000, "income": 1350000, "sqm": 64},
        {"name": "ЖК «Француз»", "price": 1000000000, "income": 5000000, "sqm": 100},
        {"name": "ЖК «АДМ»", "price": 1500000000, "income": 17000000, "sqm": 105}
    ]},
    {"name": "Бизнес - Люкс", "tiers": [
        {"name": "Хрущевка", "price": 15000000000, "income": 80000000, "sqm": 18}
    ]}
]


def get_db(max_retries=3):
    for i in range(max_retries):
        try:
            return psycopg2.connect(DATABASE_URL, connect_timeout=10)
        except OperationalError as e:
            if i == max_retries - 1: raise e
            time.sleep(0.5 * (i + 1))

@contextlib.contextmanager
def db_conn():
    conn = get_db()
    try:
        yield conn; conn.commit()
    except:
        conn.rollback(); raise
    finally:
        conn.close()

def is_admin(uid: int) -> bool:
    if uid == MAIN_ADMIN_ID: return True
    with db_conn() as conn:
        cur = conn.cursor(); cur.execute("SELECT 1 FROM admins WHERE user_id = %s", (uid,)); r = cur.fetchone(); cur.close()
        return bool(r)

def safe_json_load(data, default):
    if isinstance(data, str):
        try: return json.loads(data)
        except: return default
    return data if isinstance(data, (list, dict)) else default

def get_current_rates():
    now = int(time.time()); interval = 300
    with db_conn() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor); cur.execute("SELECT * FROM exchange_items"); items = cur.fetchall()
        rates = {}
        for item in items:
            if now - item['updated_at'] > interval or item['updated_at'] == 0:
                rng = random.Random(now * 31 + (hash(item['key']) & 0xffffffff) + item['current_price'])
                change = rng.uniform(-0.08, 0.08)
                new_price = max(item['min_price'], min(item['max_price'], int(item['current_price'] * (1 + change))))
                if new_price == item['current_price']: new_price += 1 if new_price < item['max_price'] else -1
                trend = "up" if new_price > item['current_price'] else "down"
                cur.execute("UPDATE exchange_items SET current_price=%s, trend=%s, updated_at=%s WHERE key=%s", (new_price, trend, now, item['key']))
                rates[item['key']] = {"price": new_price, "trend": trend, "name": item['name']}
            else:
                rates[item['key']] = {"price": item['current_price'], "trend": item['trend'], "name": item['name']}
        return rates


def init_db():
    with db_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id bigint primary key, name text, amount bigint default 510000,
                apartments jsonb default '[]'::jsonb, businesses jsonb default '[]'::jsonb,
                last_payout bigint, last_roll bigint default 0, daily_businesses jsonb default '[]'::jsonb,
                card_number text, card_cvc text, portfolio jsonb default '{}'::jsonb,
                last_broadcast_id bigint default 0, business_pool_hash text default '',
                loan_debt bigint default 0, loan_interest int default 0, loan_last_penalty bigint default 0,
                last_tax bigint default 0
            );
        """)
        for col, t in [
            ("portfolio", "jsonb DEFAULT '{}'::jsonb"),
            ("apartments", "jsonb DEFAULT '[]'::jsonb"),
            ("businesses", "jsonb DEFAULT '[]'::jsonb"),
            ("daily_businesses", "jsonb DEFAULT '[]'::jsonb"),
            ("last_roll", "bigint DEFAULT 0"),
            ("last_broadcast_id", "bigint DEFAULT 0"),
            ("business_pool_hash", "text DEFAULT ''"),
            ("loan_debt", "bigint DEFAULT 0"),
            ("loan_interest", "int DEFAULT 0"),
            ("loan_last_penalty", "bigint DEFAULT 0"),
            ("last_tax", "bigint DEFAULT 0"),
        ]:
            cur.execute(f"ALTER TABLE users ADD COLUMN IF NOT EXISTS {col} {t};")

        cur.execute("CREATE TABLE IF NOT EXISTS admins (user_id bigint primary key);")
        cur.execute("CREATE TABLE IF NOT EXISTS messages (id serial primary key, sender_id bigint, sender_name text, receiver_id bigint, text text, created_at bigint, is_read boolean default false);")
        cur.execute("CREATE TABLE IF NOT EXISTS money_requests (id serial primary key, sender_id bigint, sender_name text, receiver_id bigint, amount bigint, status text default 'pending', created_at bigint);")
        cur.execute("CREATE TABLE IF NOT EXISTS friends (id serial primary key, user1_id bigint, user2_id bigint, status text default 'pending', action_user_id bigint, created_at bigint, UNIQUE(user1_id, user2_id));")
        cur.execute("CREATE TABLE IF NOT EXISTS loan_requests (id serial primary key, user_id bigint, user_name text, amount bigint, status text default 'pending', created_at bigint);")

        cur.execute("CREATE TABLE IF NOT EXISTS companies (id serial primary key, name text, tiers jsonb default '[]'::jsonb);")
        cur.execute("TRUNCATE TABLE companies RESTART IDENTITY")
        for c in DEFAULT_COMPANIES:
            cur.execute("INSERT INTO companies (name, tiers) VALUES (%s, %s)", (c['name'], json.dumps(c['tiers'])))

        cur.execute("CREATE TABLE IF NOT EXISTS exchange_items (key text primary key, name text, min_price bigint, max_price bigint, current_price bigint, trend text, updated_at bigint);")
        cur.execute("TRUNCATE TABLE exchange_items")
        for e in DEFAULT_EXCHANGE:
            cur.execute("INSERT INTO exchange_items VALUES (%s,%s,%s,%s,%s,'up',%s)", (e['key'], e['name'], e['min'], e['max'], e['base'], int(time.time())))
        cur.close()

init_db()


# ===== Pydantic =====
class BuyRequest(BaseModel): user_id: int; user_name: str; apartment_name: str; price: int; income: int; sqm: int
class SellRequest(BaseModel): user_id: int; apartment_index: int; price: int
class TransferRequest(BaseModel): sender_id: int; receiver_id: int; amount: int
class TokenRequest(BaseModel): user_id: int; token_type: str; amount: int; action: str
class BusinessBuyRequest(BaseModel): user_id: int; business_index: int
class SellBusinessRequest(BaseModel): user_id: int
class SetNameRequest(BaseModel): user_id: int; name: str
class AdminMoneyRequest(BaseModel): admin_id: int; target_id: int; amount: int
class AdminCompanyRequest(BaseModel): admin_id: int; company_name: str; tier_data: dict = None
class AdminAdminRequest(BaseModel): admin_id: int; target_id: int
class MessageRequest(BaseModel): sender_id: int; receiver_id: int; text: str
class BroadcastRequest(BaseModel): admin_id: int; text: str
class MoneyRequestModel(BaseModel): sender_id: int; receiver_id: int; amount: int
class RequestAction(BaseModel): request_id: int; user_id: int
class FriendRequest(BaseModel): sender_id: int; receiver_id: int
class FriendAction(BaseModel): user_id: int; other_id: int
class AdminRemoveAptRequest(BaseModel): admin_id: int; target_id: int; apt_index: int
class LoanRequestModel(BaseModel): user_id: int; amount: int
class LoanActionModel(BaseModel): admin_id: int; request_id: int; approve: bool; percent: int = 0
class PayTaxRequest(BaseModel): user_id: int

class CompanyAddReq(BaseModel): admin_id: int; name: str
class TierAddReq(BaseModel): admin_id: int; name: str; price: int; income: int; sqm: int
class DiscountReq(BaseModel): admin_id: int; company_id: int; tier_index: int; percent: int
class ExchangeAddReq(BaseModel): admin_id: int; key: str; name: str; min_price: int; max_price: int; base_price: int
class ExchangeUpdateReq(BaseModel): admin_id: int; key: str; name: str; min_price: int; max_price: int; current_price: int; trend: str


def calculate_income(amount, apts, buses, last_payout):
    now = int(time.time()); h = (now - (last_payout or now)) // 3600
    if h > 0:
        earned = (sum(int(a.get("income", 0)) for a in apts) + sum(int(b.get("income", 0)) for b in buses)) * h
        return amount + earned, last_payout + h * 3600, earned
    return amount, last_payout, 0


# ===== NOTIFICATIONS =====
@app.get("/api/notifications/{user_id}")
def get_notifications(user_id: int):
    with db_conn() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT id, sender_id, sender_name, text FROM messages WHERE receiver_id = %s AND sender_id != 0 AND is_read = false ORDER BY created_at DESC LIMIT 1", (user_id,)); msg = cur.fetchone()
        cur.execute("SELECT last_broadcast_id FROM users WHERE id = %s", (user_id,)); u = cur.fetchone(); last_b_id = u['last_broadcast_id'] if u else 0
        cur.execute("SELECT id, text FROM messages WHERE receiver_id = 0 AND id > %s ORDER BY created_at DESC LIMIT 1", (last_b_id,)); broadcast = cur.fetchone()
        if broadcast: cur.execute("UPDATE users SET last_broadcast_id = %s WHERE id = %s", (broadcast['id'], user_id))
        cur.close()
    return {"message": msg, "broadcast": broadcast}

@app.post("/api/messages/read")
def mark_read(req: FriendAction):
    with db_conn() as conn: cur = conn.cursor(); cur.execute("UPDATE messages SET is_read = true WHERE receiver_id = %s AND sender_id = %s", (req.user_id, req.other_id)); cur.close()
    return {"status": "ok"}

# ===== EXCHANGE =====
@app.get("/api/token_rates")
def get_rates(): return get_current_rates()

@app.post("/api/trade_token")
def trade_token(req: TokenRequest):
    rates = get_current_rates()
    if req.token_type not in rates: return {"status": "error", "message": "Неизвестный актив"}
    cost = req.amount * rates[req.token_type]['price']
    with db_conn() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT amount, portfolio FROM users WHERE id = %s", (req.user_id,)); row = cur.fetchone(); port = safe_json_load(row['portfolio'], {})
        if req.action == "buy":
            if int(row['amount']) < cost: return {"status": "error", "message": "Мало Br"}
            port[req.token_type] = int(port.get(req.token_type, 0)) + req.amount
            cur.execute("UPDATE users SET amount = amount - %s, portfolio = %s WHERE id = %s", (cost, json.dumps(port), req.user_id))
        else:
            if int(port.get(req.token_type, 0)) < req.amount: return {"status": "error", "message": "Мало активов"}
            port[req.token_type] -= req.amount
            cur.execute("UPDATE users SET amount = amount + %s, portfolio = %s WHERE id = %s", (cost, json.dumps(port), req.user_id))
        cur.close()
    return {"status": "ok", "message": "Сделка успешна!"}

# ===== CHATS =====
@app.get("/api/chats/{user_id}")
def get_chats(user_id: int):
    with db_conn() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM friends WHERE user1_id = %s OR user2_id = %s", (user_id, user_id)); friend_map = {}
        for f in cur.fetchall():
            other = f['user2_id'] if f['user1_id'] == user_id else f['user1_id']
            if f['status'] == 'accepted': friend_map[other] = 'accepted'
            elif f['status'] == 'pending': friend_map[other] = 'pending_out' if f['action_user_id'] == user_id else 'pending_in'
        cur.execute("SELECT u.id, u.name FROM users u WHERE u.id != %s ORDER BY u.amount DESC LIMIT 50", (user_id,))
        chats = [{"id": 0, "name": "📢 Администрация", "status": "admin"}] + [{"id": u['id'], "name": u['name'], "status": friend_map.get(u['id'], 'none')} for u in cur.fetchall()]
        cur.close()
    return {"chats": chats}

@app.get("/api/chat_status/{user_id}/{other_id}")
def get_chat_status(user_id: int, other_id: int):
    if other_id == 0: return {"status": "admin"}
    with db_conn() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor); cur.execute("SELECT * FROM friends WHERE (user1_id=%s AND user2_id=%s) OR (user1_id=%s AND user2_id=%s)", (user_id, other_id, other_id, user_id)); row = cur.fetchone(); cur.close()
        if not row: return {"status": "none"}
        return {"status": "accepted" if row['status'] == 'accepted' else ("pending_out" if row['action_user_id'] == user_id else "pending_in")}

@app.get("/api/chat_history/{user_id}/{other_id}")
def get_chat_history(user_id: int, other_id: int):
    with db_conn() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        if other_id == 0:
            cur.execute("SELECT * FROM messages WHERE receiver_id = 0 ORDER BY created_at ASC LIMIT 100"); msgs = cur.fetchall(); reqs = []
        else:
            cur.execute("SELECT * FROM messages WHERE (sender_id=%s AND receiver_id=%s) OR (sender_id=%s AND receiver_id=%s) ORDER BY created_at ASC LIMIT 100", (user_id, other_id, other_id, user_id)); msgs = cur.fetchall()
            cur.execute("UPDATE messages SET is_read = true WHERE receiver_id = %s AND sender_id = %s", (user_id, other_id))
            cur.execute("SELECT * FROM money_requests WHERE (sender_id=%s AND receiver_id=%s) OR (sender_id=%s AND receiver_id=%s) ORDER BY created_at ASC LIMIT 100", (user_id, other_id, other_id, user_id)); reqs = cur.fetchall()
        cur.close()
    return {"messages": msgs, "requests": reqs}

@app.post("/api/send_message")
def send_message(req: MessageRequest):
    with db_conn() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        if req.receiver_id != 0:
            cur.execute("SELECT 1 FROM friends WHERE status='accepted' AND ((user1_id=%s AND user2_id=%s) OR (user1_id=%s AND user2_id=%s))", (req.sender_id, req.receiver_id, req.receiver_id, req.sender_id))
            if not cur.fetchone(): return {"status": "error", "message": "Вы не друзья!"}
        cur.execute("SELECT name FROM users WHERE id = %s", (req.sender_id,)); name = cur.fetchone()['name']
        cur.execute("INSERT INTO messages (sender_id, sender_name, receiver_id, text, created_at) VALUES (%s,%s,%s,%s,%s)", (req.sender_id, name, req.receiver_id, req.text, int(time.time())))
        cur.close()
    return {"status": "ok"}

@app.post("/api/friends/request")
def friend_request(req: FriendRequest):
    if req.sender_id == req.receiver_id: return {"status": "error"}
    with db_conn() as conn:
        cur = conn.cursor(); u1, u2 = min(req.sender_id, req.receiver_id), max(req.sender_id, req.receiver_id)
        cur.execute("INSERT INTO friends (user1_id, user2_id, status, action_user_id, created_at) VALUES (%s,%s,'pending',%s,%s) ON CONFLICT DO NOTHING", (u1, u2, req.sender_id, int(time.time()))); cur.close()
    return {"status": "ok"}

@app.post("/api/friends/accept")
def friend_accept(req: FriendAction):
    with db_conn() as conn:
        cur = conn.cursor(); u1, u2 = min(req.user_id, req.other_id), max(req.user_id, req.other_id)
        cur.execute("UPDATE friends SET status='accepted' WHERE user1_id=%s AND user2_id=%s AND action_user_id != %s", (u1, u2, req.user_id)); cur.close()
    return {"status": "ok"}

@app.post("/api/friends/decline")
def friend_decline(req: FriendAction):
    with db_conn() as conn:
        cur = conn.cursor(); u1, u2 = min(req.user_id, req.other_id), max(req.user_id, req.other_id)
        cur.execute("DELETE FROM friends WHERE user1_id=%s AND user2_id=%s", (u1, u2)); cur.close()
    return {"status": "ok"}

@app.post("/api/request_money")
def req_money(req: MoneyRequestModel):
    if req.amount <= 0: return {"status": "error"}
    with db_conn() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT name FROM users WHERE id = %s", (req.sender_id,)); name = cur.fetchone()['name']
        cur.execute("INSERT INTO money_requests (sender_id, sender_name, receiver_id, amount, created_at) VALUES (%s,%s,%s,%s,%s)", (req.sender_id, name, req.receiver_id, req.amount, int(time.time()))); cur.close()
    return {"status": "ok"}

@app.post("/api/request_money/accept")
def accept_req(req: RequestAction):
    with db_conn() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM money_requests WHERE id = %s AND status = 'pending' AND receiver_id = %s", (req.request_id, req.user_id)); r = cur.fetchone()
        if not r: return {"status":"error","message":"Нет прав"}
        cur.execute("SELECT amount FROM users WHERE id = %s", (req.user_id,))
        if int(cur.fetchone()['amount']) < r['amount']: return {"status":"error","message":"Мало Br"}
        cur.execute("UPDATE users SET amount = amount - %s WHERE id = %s", (r['amount'], r['receiver_id']))
        cur.execute("UPDATE users SET amount = amount + %s WHERE id = %s", (r['amount'], r['sender_id']))
        cur.execute("UPDATE money_requests SET status = 'accepted' WHERE id = %s", (req.request_id,)); cur.close()
    return {"status":"ok"}

@app.post("/api/request_money/decline")
def decline_req(req: RequestAction):
    with db_conn() as conn: cur = conn.cursor(); cur.execute("UPDATE money_requests SET status='declined' WHERE id=%s AND receiver_id=%s", (req.request_id, req.user_id)); cur.close()
    return {"status":"ok"}

# ===== BUSINESSES =====
@app.get("/api/businesses/{user_id}")
def get_businesses(user_id: int):
    with db_conn() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT last_roll, daily_businesses, business_pool_hash FROM users WHERE id = %s", (user_id,)); row = cur.fetchone()
        now = int(time.time()); current_hash = get_business_pool_hash(); daily = safe_json_load(row['daily_businesses'], [])
        pool_names = {b['name'] for b in BUSINESS_POOL}
        if (now - int(row['last_roll'] or 0) > 86400) or not daily or row['business_pool_hash'] != current_hash or any(b.get('name') not in pool_names for b in daily):
            rolled = []
            while len(rolled) < 2:
                b = random.choices(BUSINESS_POOL, weights=[x['weight'] for x in BUSINESS_POOL])[0]
                if b not in rolled: rolled.append(b)
            cur.execute("UPDATE users SET last_roll=%s, daily_businesses=%s, business_pool_hash=%s WHERE id=%s", (now, json.dumps(rolled), current_hash, user_id)); daily = rolled
        cur.close()
    return {"businesses": daily}

@app.post("/api/buy_business")
def buy_business(req: BusinessBuyRequest):
    with db_conn() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT amount, apartments, businesses, daily_businesses FROM users WHERE id = %s", (req.user_id,)); row = cur.fetchone()
        daily = safe_json_load(row['daily_businesses'], []); owned = safe_json_load(row['businesses'], [])
        if owned: return {"status": "error", "message": "У вас уже есть компания!"}
        if req.business_index >= len(daily): return {"status": "error"}
        bus = daily[req.business_index]
        if len(safe_json_load(row['apartments'], [])) < bus['req']: return {"status": "error", "message": f"Нужно {bus['req']} квартир!"}
        if int(row['amount']) < bus['price']: return {"status": "error", "message": "Мало Br"}
        owned.append({"name": bus['name'], "income": bus['income'], "rarity": bus['rarity'], "buy_price": bus['price']}); daily.pop(req.business_index)
        cur.execute("UPDATE users SET amount=amount-%s, businesses=%s, daily_businesses=%s WHERE id=%s", (bus['price'], json.dumps(owned), json.dumps(daily), req.user_id)); cur.close()
    return {"status": "ok", "message": f"Куплен {bus['name']}!"}

@app.post("/api/sell_business")
def sell_business(req: SellBusinessRequest):
    with db_conn() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor); cur.execute("SELECT businesses FROM users WHERE id = %s", (req.user_id,)); bus = safe_json_load(cur.fetchone()['businesses'], [])
        if not bus: return {"status": "error"}
        sell_price = int(bus[0].get('buy_price', 0) * 0.7)
        cur.execute("UPDATE users SET amount = amount + %s, businesses = '[]'::jsonb WHERE id = %s", (sell_price, req.user_id)); cur.close()
    return {"status": "ok", "message": f"Продано за {sell_price} Br"}

# ===== COMPANIES =====
@app.get("/api/companies")
def get_companies():
    with db_conn() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor); cur.execute("SELECT id, name, tiers FROM companies ORDER BY id ASC"); rows = cur.fetchall(); cur.close()
    comps = []
    for r in rows:
        tiers = safe_json_load(r['tiers'], [])
        for t in tiers:
            t['old_price'] = t['price']
            t['price'] = int(t['price'] * (1 - t.get('discount', 0) / 100.0))
        comps.append({"id": r['id'], "name": r['name'], "tiers": sorted(tiers, key=lambda x: x['price'])})
    return {"companies": sorted(comps, key=lambda x: x['tiers'][0]['price'] if x['tiers'] else 0)}

# ===== BALANCE =====
@app.get("/api/balance/{user_id}")
def get_balance(user_id: int, name: str = "Игрок"):
    try:
        with db_conn() as conn:
            cur = conn.cursor(cursor_factory=RealDictCursor); cur.execute("SELECT * FROM users WHERE id = %s", (user_id,)); row = cur.fetchone(); now = int(time.time())
            if not row:
                card = "1234" + "".join(str(random.randint(0, 9)) for _ in range(12)); fmt = " ".join(card[i:i+4] for i in range(0, 16, 4))
                cvc = str(random.randint(100,999))
                cur.execute("INSERT INTO users (id, name, amount, last_payout, card_number, card_cvc, last_tax) VALUES (%s,%s,510000,%s,%s,%s,%s)", (user_id, name, now, fmt, cvc, now))
                cur.close()
                return {"balance": 510000, "apartments": [], "businesses": [], "earned": 0, "card_number": fmt, "card_cvc": cvc,
                        "name": name, "portfolio": {}, "loan_debt": 0, "loan_interest": 0, "tax_debt": 0, "daily_tax": 0, "tax_days": 0}

            # Штраф по кредиту
            loan_debt = int(row.get('loan_debt') or 0); loan_last = int(row.get('loan_last_penalty') or 0)
            if loan_debt > 0 and loan_last > 0:
                days = (now - loan_last) // 86400
                if days > 0:
                    loan_debt = int(loan_debt * (1.01 ** days))
                    cur.execute("UPDATE users SET loan_debt=%s, loan_last_penalty=%s WHERE id=%s", (loan_debt, now, user_id))

            apts = safe_json_load(row['apartments'], [])
            total_sqm = sum(int(a.get('sqm', 0)) for a in apts)
            daily_tax = total_sqm * SQM_TAX

            # Налог: считаем дни только с последней оплаты (или регистрации)
            last_tax = int(row.get('last_tax') or now)
            if total_sqm == 0:
                cur.execute("UPDATE users SET last_tax = %s WHERE id = %s", (now, user_id))
                tax_days = 0; tax_debt = 0
            else:
                tax_days = (now - last_tax) // 86400
                tax_debt = daily_tax * tax_days

            buses = safe_json_load(row['businesses'], [])
            if len(buses) > 1:
                buses = [buses[0]]; cur.execute("UPDATE users SET businesses = %s WHERE id = %s", (json.dumps(buses), user_id))
            nb, nl, earned = calculate_income(int(row['amount']), apts, buses, int(row['last_payout']) if row['last_payout'] else now)

            cur.execute("UPDATE users SET amount = %s, last_payout = %s WHERE id = %s", (nb, nl, user_id)); cur.close()
        return {"balance": nb, "apartments": apts, "businesses": buses, "earned": earned,
                "card_number": row['card_number'], "card_cvc": row['card_cvc'], "name": row['name'],
                "portfolio": safe_json_load(row.get('portfolio'), {}), "loan_debt": loan_debt,
                "loan_interest": row.get('loan_interest', 0), "tax_debt": tax_debt,
                "daily_tax": daily_tax, "tax_days": tax_days}
    except Exception as e: return {"balance": 0, "error": str(e)}

@app.post("/api/pay_tax")
def pay_tax(req: PayTaxRequest):
    with db_conn() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor); cur.execute("SELECT * FROM users WHERE id = %s", (req.user_id,)); row = cur.fetchone()
        now = int(time.time()); apts = safe_json_load(row['apartments'], []); total_sqm = sum(int(a.get('sqm', 0)) for a in apts); daily_tax = total_sqm * SQM_TAX
        last_tax = int(row['last_tax'] or now); tax_days = (now - last_tax) // 86400; tax_debt = daily_tax * tax_days
        if tax_debt <= 0: return {"status": "ok", "message": "Нет задолженности"}
        if int(row['amount']) < tax_debt: return {"status": "error", "message": f"Не хватает {tax_debt - int(row['amount'])} Br!"}
        cur.execute("UPDATE users SET amount = amount - %s, last_tax = %s WHERE id = %s", (tax_debt, now, req.user_id)); cur.close()
    return {"status": "ok", "message": f"Налог оплачен! Списано {tax_debt} Br."}

@app.post("/api/buy")
def buy_apartment(req: BuyRequest):
    with db_conn() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor); cur.execute("SELECT amount, apartments, last_tax FROM users WHERE id = %s", (req.user_id,)); row = cur.fetchone()
        if int(row['amount']) < req.price: return {"status": "error", "message": "Мало Br"}
        apts = safe_json_load(row['apartments'], [])
        # если это первая квартира — стартуем отсчёт налога с текущего момента
        if len(apts) == 0:
            cur.execute("UPDATE users SET last_tax = %s WHERE id = %s", (int(time.time()), req.user_id))
        apts.append({"name": req.apartment_name, "income": req.income, "buy_price": req.price, "sqm": req.sqm})
        cur.execute("UPDATE users SET amount = amount - %s, apartments = %s WHERE id = %s", (req.price, json.dumps(apts), req.user_id)); cur.close()
    return {"status": "ok"}

@app.post("/api/sell")
def sell_apartment(req: SellRequest):
    with db_conn() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor); cur.execute("SELECT apartments FROM users WHERE id = %s", (req.user_id,)); apts = safe_json_load(cur.fetchone()['apartments'], [])
        if req.apartment_index >= len(apts): return {"status": "error"}
        sell_price = int(req.price * 0.7); apts.pop(req.apartment_index)
        cur.execute("UPDATE users SET amount = amount + %s, apartments = %s WHERE id = %s", (sell_price, json.dumps(apts), req.user_id)); cur.close()
    return {"status": "ok", "message": f"Продана за {sell_price} Br"}

@app.post("/api/transfer")
def transfer_money(req: TransferRequest):
    with db_conn() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor); cur.execute("SELECT amount FROM users WHERE id = %s", (req.sender_id,)); sender = cur.fetchone()
        if not sender or int(sender['amount']) < req.amount: return {"status": "error", "message": "Мало средств"}
        cur.execute("UPDATE users SET amount = amount - %s WHERE id = %s", (req.amount, req.sender_id))
        cur.execute("UPDATE users SET amount = amount + %s WHERE id = %s", (req.amount, req.receiver_id)); cur.close()
    return {"status": "ok", "message": "Переведено!"}

@app.get("/api/leaderboard")
def leaderboard():
    with db_conn() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor); cur.execute("SELECT name, amount FROM users ORDER BY amount DESC LIMIT 5"); rows = cur.fetchall(); cur.close()
    return {"leaders": [{"name": r['name'], "balance": int(r['amount'])} for r in rows]}

@app.post("/api/set_name")
def set_name(req: SetNameRequest):
    with db_conn() as conn: cur = conn.cursor(); cur.execute("UPDATE users SET name = %s WHERE id = %s", (req.name, req.user_id)); cur.close()
    return {"status": "ok"}

@app.get("/api/all_users")
def all_users():
    with db_conn() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor); cur.execute("SELECT id, name FROM users ORDER BY amount DESC LIMIT 50"); rows = cur.fetchall(); cur.close()
    return {"users": [{"id": r['id'], "name": r['name']} for r in rows]}

# ===== LOANS =====
@app.post("/api/loan/request")
def req_loan(req: LoanRequestModel):
    if req.amount <= 0: return {"status": "error", "message": "Сумма должна быть больше 0"}
    if req.amount > LOAN_LIMIT: return {"status": "error", "message": f"❌ Максимум {LOAN_LIMIT:,} Br"}
    with db_conn() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor); cur.execute("SELECT loan_debt, name FROM users WHERE id=%s", (req.user_id,)); u = cur.fetchone()
        if u['loan_debt'] > 0: return {"status": "error", "message": "У вас уже есть кредит!"}
        cur.execute("SELECT 1 FROM loan_requests WHERE user_id=%s AND status='pending'", (req.user_id,))
        if cur.fetchone(): return {"status": "error", "message": "У вас уже есть активная заявка"}
        cur.execute("INSERT INTO loan_requests (user_id, user_name, amount, created_at) VALUES (%s,%s,%s,%s)", (req.user_id, u['name'], req.amount, int(time.time()))); cur.close()
    return {"status": "ok", "message": "Заявка отправлена!"}

@app.get("/api/admin/loan/list")
def admin_loans_list(admin_id: int):
    if not is_admin(admin_id): return {"requests": []}
    with db_conn() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor); cur.execute("SELECT * FROM loan_requests WHERE status='pending' ORDER BY created_at ASC"); res = cur.fetchall(); cur.close()
    return {"requests": res}

@app.post("/api/admin/loan/action")
def admin_loan_action(req: LoanActionModel):
    if not is_admin(req.admin_id): return {"status": "error"}
    with db_conn() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor); cur.execute("SELECT * FROM loan_requests WHERE id=%s AND status='pending'", (req.request_id,)); r = cur.fetchone()
        if r:
            if req.approve:
                cur.execute("UPDATE users SET amount=amount+%s, loan_debt=%s, loan_interest=%s, loan_last_penalty=%s WHERE id=%s",
                            (r['amount'], r['amount'], req.percent, int(time.time()), r['user_id']))
            cur.execute("UPDATE loan_requests SET status=%s WHERE id=%s", ('approved' if req.approve else 'rejected', req.request_id))
        cur.close()
    return {"status": "ok"}

@app.post("/api/loan/repay")
def repay_loan(req: LoanRequestModel):
    with db_conn() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor); cur.execute("SELECT amount, loan_debt FROM users WHERE id=%s", (req.user_id,)); row = cur.fetchone()
        if int(row['amount']) < row['loan_debt']: return {"status": "error", "message": "Недостаточно Br!"}
        cur.execute("UPDATE users SET amount=amount-loan_debt, loan_debt=0, loan_interest=0, loan_last_penalty=0 WHERE id=%s", (req.user_id,)); cur.close()
    return {"status": "ok", "message": "Кредит погашен!"}

# ===== ADMIN =====
@app.get("/api/check_admin/{user_id}")
def check_admin(user_id: int): return {"is_admin": is_admin(user_id)}

@app.post("/api/admin/broadcast")
def broadcast(req: BroadcastRequest):
    if not is_admin(req.admin_id): return {"status": "error"}
    with db_conn() as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO messages (sender_id, sender_name, receiver_id, text, created_at) VALUES (%s,'📢 Администрация',0,%s,%s)", (MAIN_ADMIN_ID, req.text, int(time.time()))); cur.close()
    return {"status": "ok", "message": "Рассылка отправлена!"}

@app.post("/api/admin/add_money")
def add_money(req: AdminMoneyRequest):
    if not is_admin(req.admin_id): return {"status": "error"}
    if req.admin_id != MAIN_ADMIN_ID and req.amount > 500000: return {"status": "error", "message": "Лимит 500 000 Br"}
    with db_conn() as conn: cur = conn.cursor(); cur.execute("UPDATE users SET amount = amount + %s WHERE id = %s", (req.amount, req.target_id)); cur.close()
    return {"status": "ok"}

@app.post("/api/admin/remove_money")
def remove_money(req: AdminMoneyRequest):
    if not is_admin(req.admin_id): return {"status": "error"}
    with db_conn() as conn: cur = conn.cursor(); cur.execute("UPDATE users SET amount = GREATEST(0, amount - %s) WHERE id = %s", (req.amount, req.target_id)); cur.close()
    return {"status": "ok"}

@app.post("/api/admin/remove_apartment")
def remove_apt(req: AdminRemoveAptRequest):
    if not is_admin(req.admin_id): return {"status": "error"}
    with db_conn() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor); cur.execute("SELECT apartments FROM users WHERE id = %s", (req.target_id,)); apts = safe_json_load(cur.fetchone()['apartments'], [])
        if req.apt_index < len(apts): apts.pop(req.apt_index); cur.execute("UPDATE users SET apartments = %s WHERE id = %s", (json.dumps(apts), req.target_id))
        cur.close()
    return {"status": "ok"}

@app.get("/api/admin/users")
def admin_users(admin_id: int):
    if not is_admin(admin_id): return {"users": []}
    with db_conn() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor); cur.execute("SELECT id, name, amount, apartments FROM users"); rows = cur.fetchall(); cur.close()
    return {"users": [{"id": r['id'], "name": r['name'], "balance": int(r['amount']), "apts_count": len(safe_json_load(r['apartments'], []))} for r in rows]}

@app.get("/api/admin/user_apartments/{user_id}")
def admin_user_apts(user_id: int):
    with db_conn() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor); cur.execute("SELECT apartments FROM users WHERE id=%s", (user_id,)); row = cur.fetchone(); cur.close()
    return {"apartments": safe_json_load(row['apartments'], []) if row else []}

@app.post("/api/admin/reset_all")
def reset_all(req: AdminMoneyRequest):
    if req.admin_id != MAIN_ADMIN_ID: return {"status": "error", "message": "Только главный админ"}
    with db_conn() as conn:
        cur = conn.cursor()
        for t in ["users", "messages", "money_requests", "friends", "loan_requests"]:
            cur.execute(f"DELETE FROM {t}")
        cur.close()
    return {"status": "ok", "message": "Всё сброшено!"}

@app.post("/api/admin/add_company")
def add_company(req: CompanyAddReq):
    if not is_admin(req.admin_id): return {"status": "error"}
    with db_conn() as conn:
        cur = conn.cursor(); cur.execute("INSERT INTO companies (name, tiers) VALUES (%s, '[]')", (req.name,)); cur.close()
    return {"status": "ok"}

@app.post("/api/admin/delete_company/{cid}")
def del_company(cid: int, req: AdminMoneyRequest):
    if not is_admin(req.admin_id): return {"status": "error"}
    with db_conn() as conn: cur = conn.cursor(); cur.execute("DELETE FROM companies WHERE id = %s", (cid,)); cur.close()
    return {"status": "ok"}

@app.post("/api/admin/add_tier/{cid}")
def add_tier(cid: int, req: TierAddReq):
    if not is_admin(req.admin_id): return {"status": "error"}
    with db_conn() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor); cur.execute("SELECT tiers FROM companies WHERE id = %s", (cid,)); row = cur.fetchone()
        if not row: return {"status": "error"}
        tiers = safe_json_load(row['tiers'], [])
        tiers.append({"name": req.name, "price": req.price, "income": req.income, "sqm": req.sqm})
        cur.execute("UPDATE companies SET tiers = %s WHERE id = %s", (json.dumps(tiers), cid)); cur.close()
    return {"status": "ok"}

@app.post("/api/admin/set_discount")
def set_discount(req: DiscountReq):
    if not is_admin(req.admin_id): return {"status": "error"}
    with db_conn() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor); cur.execute("SELECT tiers FROM companies WHERE id = %s", (req.company_id,)); row = cur.fetchone()
        if not row: return {"status": "error"}
        tiers = safe_json_load(row['tiers'], [])
        if 0 <= req.tier_index < len(tiers):
            tiers[req.tier_index]['discount'] = req.percent
            cur.execute("UPDATE companies SET tiers = %s WHERE id = %s", (json.dumps(tiers), req.company_id))
        cur.close()
    return {"status": "ok"}

@app.post("/api/admin/force_update_exchange")
def force_exchange(req: AdminMoneyRequest):
    if not is_admin(req.admin_id): return {"status": "error"}
    with db_conn() as conn: cur = conn.cursor(); cur.execute("UPDATE exchange_items SET updated_at = 0"); cur.close()
    return {"status": "ok", "message": "Биржа обновлена!"}

@app.post("/api/admin/add_exchange")
def add_exchange(req: ExchangeAddReq):
    if not is_admin(req.admin_id): return {"status": "error"}
    with db_conn() as conn:
        cur = conn.cursor()
        try:
            cur.execute("INSERT INTO exchange_items VALUES (%s,%s,%s,%s,%s,'up',%s)", (req.key, req.name, req.min_price, req.max_price, req.base_price, int(time.time())))
        except Exception:
            return {"status": "error", "message": "Такой ключ уже существует"}
        cur.close()
    return {"status": "ok"}

@app.post("/api/admin/update_exchange")
def update_exchange(req: ExchangeUpdateReq):
    if not is_admin(req.admin_id): return {"status": "error"}
    with db_conn() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE exchange_items SET name=%s, min_price=%s, max_price=%s, current_price=%s, trend=%s, updated_at=%s WHERE key=%s",
            (req.name, req.min_price, req.max_price, req.current_price, req.trend, int(time.time()), req.key)); cur.close()
    return {"status": "ok"}
