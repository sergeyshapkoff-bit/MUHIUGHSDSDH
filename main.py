from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2 import OperationalError
import json, time, random, contextlib

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

DATABASE_URL = (
    "postgresql://postgres.zmfepxqnxcvkvdjonzhp:p0LwFeRg9NJ7Cusj"
    "@aws-0-eu-west-1.pooler.supabase.com:6543/postgres"
    "?sslmode=require"
)
MAIN_ADMIN_ID = 5634302903
GUEST_USER_ID = 123456789

def get_db(max_retries: int = 3):
    last_err = None
    for i in range(max_retries):
        try:
            return psycopg2.connect(DATABASE_URL, connect_timeout=10)
        except OperationalError as e:
            last_err = e
            if any(x in str(e).lower() for x in ("too many", "remaining", "timeout", "could not", "closed", "refused")):
                time.sleep(0.5 * (i + 1)); continue
            raise
    raise last_err

@contextlib.contextmanager
def db_conn():
    conn = get_db()
    try:
        yield conn
        conn.commit()
    except Exception:
        try: conn.rollback()
        except Exception: pass
        raise
    finally:
        try: conn.close()
        except Exception: pass

def is_admin(uid: int) -> bool:
    if uid == MAIN_ADMIN_ID: return True
    try:
        with db_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT 1 FROM admins WHERE user_id = %s", (uid,))
            r = cur.fetchone(); cur.close()
            return bool(r)
    except Exception:
        return False

def get_current_rates():
    now = int(time.time())
    hour = now // 3600
    with db_conn() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM exchange_items")
        items = cur.fetchall()
        rates = {}
        for item in items:
            name = item['name'] if item['name'] else item['key'].upper()
            
            if now - item['updated_at'] > 3600:
                rng = random.Random(hour + hash(item['key']))
                change = rng.uniform(-0.15, 0.15)
                new_price = int(item['current_price'] * (1 + change))
                new_price = max(item['min_price'], min(item['max_price'], new_price))
                if new_price == item['current_price']:
                    if item['current_price'] < item['max_price']:
                        new_price = item['current_price'] + 1
                    else:
                        new_price = item['current_price'] - 1
                trend = "up" if new_price > item['current_price'] else "down"
                cur.execute("UPDATE exchange_items SET current_price = %s, trend = %s, updated_at = %s WHERE key = %s", (new_price, trend, now, item['key']))
                rates[item['key']] = {"price": new_price, "trend": trend, "name": name}
            else:
                rates[item['key']] = {"price": item['current_price'], "trend": item['trend'], "name": name}
        return rates

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

DEFAULT_EXCHANGE = [
    {"key": "gold", "name": "Золото", "min": 500, "max": 1200, "base": 850},
    {"key": "ring", "name": "Сплав золота и серебра (кольцо)", "min": 1800, "max": 4000, "base": 2900},
    {"key": "tesla", "name": "Машина тесла", "min": 35000, "max": 42350, "base": 38000},
    {"key": "mcdonalds", "name": "Акции макдональса", "min": 45500, "max": 55000, "base": 50000},
    {"key": "bitcoin", "name": "Биткоин", "min": 60000, "max": 72280, "base": 65000},
]

def init_db():
    for attempt in range(1, 4):
        try:
            with db_conn() as conn:
                cur = conn.cursor()
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        id bigint primary key, name text, amount bigint default 510000,
                        apartments jsonb default '[]'::jsonb, businesses jsonb default '[]'::jsonb,
                        last_payout bigint, last_roll bigint default 0,
                        daily_businesses jsonb default '[]'::jsonb,
                        card_number text, card_cvc text,
                        portfolio jsonb default '{}'::jsonb,
                        last_broadcast_id bigint default 0
                    );
                """)
                cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS portfolio jsonb DEFAULT '{}'::jsonb;")
                cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS apartments jsonb DEFAULT '[]'::jsonb;")
                cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS businesses jsonb DEFAULT '[]'::jsonb;")
                cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS daily_businesses jsonb DEFAULT '[]'::jsonb;")
                cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_roll bigint DEFAULT 0;")
                cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_broadcast_id bigint DEFAULT 0;")

                cur.execute("CREATE TABLE IF NOT EXISTS companies (id serial primary key, name text, tiers jsonb default '[]'::jsonb);")
                cur.execute("TRUNCATE TABLE companies RESTART IDENTITY;")
                
                cur.execute("CREATE TABLE IF NOT EXISTS exchange_items (key text primary key, name text, min_price bigint, max_price bigint, current_price bigint, trend text, updated_at bigint);")
                cur.execute("TRUNCATE TABLE exchange_items;")

                cur.execute("CREATE TABLE IF NOT EXISTS admins (user_id bigint primary key);")
                cur.execute("ALTER TABLE admins DROP COLUMN IF EXISTS expires_at;")
                
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS messages (
                        id serial primary key, sender_id bigint, sender_name text,
                        receiver_id bigint, text text, created_at bigint,
                        is_read boolean default false
                    );
                """)
                cur.execute("ALTER TABLE messages ADD COLUMN IF NOT EXISTS is_read boolean DEFAULT false;")
                
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS money_requests (
                        id serial primary key, sender_id bigint, sender_name text,
                        receiver_id bigint, amount bigint, status text default 'pending', created_at bigint
                    );
                """)
                
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS friends (
                        id serial primary key, user1_id bigint, user2_id bigint,
                        status text default 'pending', action_user_id bigint, created_at bigint,
                        UNIQUE(user1_id, user2_id)
                    );
                """)

                cur.execute("CREATE TABLE IF NOT EXISTS settings (key text primary key, value text);")
                cur.execute("INSERT INTO settings (key, value) VALUES ('apt_discount', '0') ON CONFLICT DO NOTHING;")
                
                for comp in DEFAULT_COMPANIES:
                    cur.execute("INSERT INTO companies (name, tiers) VALUES (%s, %s)", (comp['name'], json.dumps(comp['tiers'])))
                
                now = int(time.time())
                for ex in DEFAULT_EXCHANGE:
                    cur.execute("INSERT INTO exchange_items (key, name, min_price, max_price, current_price, trend, updated_at) VALUES (%s, %s, %s, %s, %s, 'up', %s)", 
                                (ex['key'], ex['name'], ex['min'], ex['max'], ex['base'], now))

                cur.close()
            print(f"✅ init_db OK")
            return True
        except Exception as e:
            print(f"❌ init_db attempt {attempt} failed: {e}")
            if attempt < 3: time.sleep(2 * attempt)
    return False

init_db()

class BuyRequest(BaseModel): user_id: int; user_name: str; apartment_name: str; price: int; income: int
class SellRequest(BaseModel): user_id: int; apartment_index: int; price: int
class DeleteAptRequest(BaseModel): user_id: int; apartment_index: int
class TransferRequest(BaseModel): sender_id: int; receiver_id: int; amount: int
class TokenRequest(BaseModel): user_id: int; token_type: str; amount: int; action: str
class BusinessBuyRequest(BaseModel): user_id: int; business_index: int
class SellBusinessRequest(BaseModel): user_id: int
class SetNameRequest(BaseModel): user_id: int; name: str
class AdminMoneyRequest(BaseModel): admin_id: int; target_id: int; amount: int
class AdminCompanyRequest(BaseModel): admin_id: int; company_name: str; tier_data: dict = None
class AdminAdminRequest(BaseModel): admin_id: int; target_id: int
class MessageRequest(BaseModel): sender_id: int; receiver_id: int; text: str
class DeleteMsgRequest(BaseModel): user_id: int; message_id: int
class BroadcastRequest(BaseModel): admin_id: int; text: str
class TierDiscountRequest(BaseModel): admin_id: int; company_id: int; tier_index: int; percent: int
class MoneyRequestModel(BaseModel): sender_id: int; receiver_id: int; amount: int
class RequestAction(BaseModel): request_id: int; user_id: int
class FriendRequest(BaseModel): sender_id: int; receiver_id: int
class FriendAction(BaseModel): user_id: int; other_id: int
class ExchangeUpdateRequest(BaseModel): admin_id: int; key: str; name: str; min_price: int; max_price: int; current_price: int; trend: str
class ExchangeAddRequest(BaseModel): admin_id: int; key: str; name: str; min_price: int; max_price: int; base_price: int
class AdminRemoveAptRequest(BaseModel): admin_id: int; target_id: int; apt_index: int

def safe_json_load(data, default):
    if isinstance(data, str):
        try: return json.loads(data)
        except: return default
    elif isinstance(data, (list, dict)): return data
    return default

def calculate_income(amount, apts, buses, last_payout):
    now = int(time.time())
    if not last_payout: last_payout = now
    h = (now - last_payout) // 3600
    if h > 0:
        apt_inc = sum(int(a.get("income", 0)) for a in apts if isinstance(a, dict))
        bus_inc = sum(int(b.get("income", 0)) for b in buses if isinstance(b, dict))
        earned = (apt_inc + bus_inc) * h
        return amount + earned, last_payout + h * 3600, earned
    return amount, last_payout, 0

@app.post("/api/admin/force_update_exchange")
def admin_force_update_exchange(req: AdminMoneyRequest):
    if not is_admin(req.admin_id): return {"status": "error"}
    with db_conn() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE exchange_items SET updated_at = 0")
        cur.close()
    return {"status": "ok", "message": "Биржа будет обновлена при следующем запросе"}

@app.get("/api/notifications/{user_id}")
def get_notifications(user_id: int):
    with db_conn() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT id, sender_id, sender_name, text, created_at FROM messages WHERE receiver_id = %s AND sender_id != 0 AND is_read = false ORDER BY created_at DESC LIMIT 1", (user_id,))
        msg = cur.fetchone()
        
        cur.execute("SELECT last_broadcast_id FROM users WHERE id = %s", (user_id,))
        u = cur.fetchone()
        last_b_id = u['last_broadcast_id'] if u else 0
        
        cur.execute("SELECT id, text, created_at FROM messages WHERE receiver_id = 0 AND id > %s ORDER BY created_at DESC LIMIT 1", (last_b_id,))
        broadcast = cur.fetchone()
        
        if broadcast:
            cur.execute("UPDATE users SET last_broadcast_id = %s WHERE id = %s", (broadcast['id'], user_id))
        cur.close()
    return {"message": msg, "broadcast": broadcast}

@app.post("/api/messages/read")
def mark_messages_read(req: FriendAction):
    with db_conn() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE messages SET is_read = true WHERE receiver_id = %s AND sender_id = %s", (req.user_id, req.other_id))
        cur.close()
    return {"status": "ok"}

@app.post("/api/messages/delete")
def delete_message(req: DeleteMsgRequest):
    with db_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM messages WHERE id = %s AND sender_id = %s", (req.message_id, req.user_id))
        cur.close()
    return {"status": "ok"}

@app.get("/api/token_rates")
def get_rates(): return get_current_rates()

@app.post("/api/admin/update_exchange")
def admin_update_exchange(req: ExchangeUpdateRequest):
    if not is_admin(req.admin_id): return {"status": "error"}
    with db_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            UPDATE exchange_items 
            SET name = %s, min_price = %s, max_price = %s, current_price = %s, trend = %s, updated_at = %s
            WHERE key = %s
        """, (req.name, req.min_price, req.max_price, req.current_price, req.trend, int(time.time()), req.key))
        cur.close()
    return {"status": "ok", "message": "Биржа обновлена!"}

@app.post("/api/admin/add_exchange")
def admin_add_exchange(req: ExchangeAddRequest):
    if not is_admin(req.admin_id): return {"status": "error"}
    with db_conn() as conn:
        cur = conn.cursor()
        try:
            cur.execute("""
                INSERT INTO exchange_items (key, name, min_price, max_price, current_price, trend, updated_at)
                VALUES (%s, %s, %s, %s, %s, 'up', %s)
            """, (req.key, req.name, req.min_price, req.max_price, req.base_price, int(time.time())))
            cur.close()
            return {"status": "ok", "message": "Актив добавлен!"}
        except Exception as e:
            return {"status": "error", "message": "Такой ключ уже существует"}

@app.post("/api/trade_token")
def trade_token(req: TokenRequest):
    rates = get_current_rates()
    if req.token_type not in rates: return {"status": "error", "message": "Неизвестный актив"}
    cost = req.amount * rates[req.token_type]['price']
    with db_conn() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT amount, portfolio FROM users WHERE id = %s", (req.user_id,)); row = cur.fetchone()
        port = safe_json_load(row['portfolio'], {}); cur_qty = int(port.get(req.token_type, 0))
        if req.action == "buy":
            if int(row['amount']) < cost: return {"status": "error", "message": "Мало Br"}
            port[req.token_type] = cur_qty + req.amount
            cur.execute("UPDATE users SET amount = amount - %s, portfolio = %s WHERE id = %s", (cost, json.dumps(port), req.user_id))
        else:
            if cur_qty < req.amount: return {"status": "error", "message": "Мало активов"}
            port[req.token_type] = cur_qty - req.amount
            cur.execute("UPDATE users SET amount = amount + %s, portfolio = %s WHERE id = %s", (cost, json.dumps(port), req.user_id))
        cur.close()
    return {"status": "ok", "message": "Сделка успешна!"}

@app.get("/api/chats/{user_id}")
def get_chats(user_id: int):
    with db_conn() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM friends WHERE user1_id = %s OR user2_id = %s", (user_id, user_id))
        friendships = cur.fetchall()
        friend_map = {}
        for f in friendships:
            other = f['user2_id'] if f['user1_id'] == user_id else f['user1_id']
            if f['status'] == 'accepted': friend_map[other] = 'accepted'
            elif f['status'] == 'pending': friend_map[other] = 'pending_out' if f['action_user_id'] == user_id else 'pending_in'

        cur.execute("""
            SELECT u.id, u.name, MAX(m.created_at) as last_msg
            FROM users u LEFT JOIN messages m ON (m.sender_id = u.id AND m.receiver_id = %s) OR (m.sender_id = %s AND m.receiver_id = u.id)
            WHERE u.id != %s GROUP BY u.id, u.name ORDER BY last_msg DESC NULLS LAST, u.amount DESC LIMIT 100
        """, (user_id, user_id, user_id))
        users = cur.fetchall()
        
        chats = [{"id": 0, "name": "📢 Администрация", "status": "admin"}]
        for u in users:
            chats.append({"id": u['id'], "name": u['name'], "status": friend_map.get(u['id'], 'none')})
        cur.close()
    return {"chats": chats}

@app.get("/api/chat_status/{user_id}/{other_id}")
def get_chat_status(user_id: int, other_id: int):
    if other_id == 0: return {"status": "admin"}
    with db_conn() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM friends WHERE (user1_id = %s AND user2_id = %s) OR (user1_id = %s AND user2_id = %s)", (user_id, other_id, other_id, user_id))
        row = cur.fetchone()
        cur.close()
        if not row: return {"status": "none"}
        if row['status'] == 'accepted': return {"status": "accepted"}
        if row['action_user_id'] == user_id: return {"status": "pending_out"}
        return {"status": "pending_in"}

@app.get("/api/chat_history/{user_id}/{other_id}")
def get_chat_history(user_id: int, other_id: int):
    with db_conn() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        if other_id == 0:
            cur.execute("SELECT * FROM messages WHERE receiver_id = 0 ORDER BY created_at ASC LIMIT 100")
            msgs = cur.fetchall()
        else:
            cur.execute("SELECT * FROM messages WHERE (sender_id = %s AND receiver_id = %s) OR (sender_id = %s AND receiver_id = %s) ORDER BY created_at ASC LIMIT 100", (user_id, other_id, other_id, user_id))
            msgs = cur.fetchall()
            cur.execute("UPDATE messages SET is_read = true WHERE receiver_id = %s AND sender_id = %s", (user_id, other_id))

        if other_id == 0: 
            reqs = []
        else:
            cur.execute("SELECT * FROM money_requests WHERE (sender_id = %s AND receiver_id = %s) OR (sender_id = %s AND receiver_id = %s) ORDER BY created_at ASC LIMIT 100", (user_id, other_id, other_id, user_id))
            reqs = cur.fetchall()
            
        cur.close()
    return {"messages": msgs, "requests": reqs}

@app.post("/api/send_message")
def send_message(req: MessageRequest):
    with db_conn() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        if req.receiver_id != 0:
            cur.execute("SELECT 1 FROM friends WHERE status = 'accepted' AND ((user1_id = %s AND user2_id = %s) OR (user1_id = %s AND user2_id = %s))", (req.sender_id, req.receiver_id, req.receiver_id, req.sender_id))
            if not cur.fetchone(): return {"status": "error", "message": "Вы не друзья!"}

        cur.execute("SELECT name FROM users WHERE id = %s", (req.sender_id,))
        row = cur.fetchone(); s_name = row['name'] if row else "Игрок"
        cur.execute("INSERT INTO messages (sender_id, sender_name, receiver_id, text, created_at) VALUES (%s, %s, %s, %s, %s)", (req.sender_id, s_name, req.receiver_id, req.text, int(time.time())))
        cur.close()
    return {"status": "ok"}

@app.post("/api/friends/request")
def friend_request(req: FriendRequest):
    if req.sender_id == req.receiver_id: return {"status": "error"}
    with db_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM friends WHERE (user1_id = %s AND user2_id = %s) OR (user1_id = %s AND user2_id = %s)", (req.sender_id, req.receiver_id, req.receiver_id, req.sender_id))
        if cur.fetchone(): return {"status": "error", "message": "Запрос уже существует"}
        u1, u2 = min(req.sender_id, req.receiver_id), max(req.sender_id, req.receiver_id)
        cur.execute("INSERT INTO friends (user1_id, user2_id, status, action_user_id, created_at) VALUES (%s, %s, 'pending', %s, %s)", (u1, u2, req.sender_id, int(time.time())))
        cur.close()
    return {"status": "ok"}

@app.post("/api/friends/accept")
def friend_accept(req: FriendAction):
    with db_conn() as conn:
        cur = conn.cursor()
        u1, u2 = min(req.user_id, req.other_id), max(req.user_id, req.other_id)
        cur.execute("UPDATE friends SET status = 'accepted' WHERE user1_id = %s AND user2_id = %s AND action_user_id != %s", (u1, u2, req.user_id))
        cur.close()
    return {"status": "ok"}

@app.post("/api/friends/decline")
def friend_decline(req: FriendAction):
    with db_conn() as conn:
        cur = conn.cursor()
        u1, u2 = min(req.user_id, req.other_id), max(req.user_id, req.other_id)
        cur.execute("DELETE FROM friends WHERE user1_id = %s AND user2_id = %s", (u1, u2))
        cur.close()
    return {"status": "ok"}

@app.post("/api/request_money")
def create_money_request(req: MoneyRequestModel):
    if req.amount <= 0: return {"status": "error"}
    with db_conn() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT 1 FROM friends WHERE status = 'accepted' AND ((user1_id = %s AND user2_id = %s) OR (user1_id = %s AND user2_id = %s))", (req.sender_id, req.receiver_id, req.receiver_id, req.sender_id))
        if not cur.fetchone(): return {"status": "error", "message": "Вы не друзья!"}
        cur.execute("SELECT name FROM users WHERE id = %s", (req.sender_id,))
        row = cur.fetchone(); s_name = row['name'] if row else "Игрок"
        cur.execute("INSERT INTO money_requests (sender_id, sender_name, receiver_id, amount, created_at) VALUES (%s, %s, %s, %s, %s)", (req.sender_id, s_name, req.receiver_id, req.amount, int(time.time())))
        cur.close()
    return {"status": "ok"}

@app.post("/api/request_money/accept")
def accept_request(req: RequestAction):
    with db_conn() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM money_requests WHERE id = %s AND status = 'pending'", (req.request_id,))
        r = cur.fetchone()
        if not r or r['receiver_id'] != req.user_id: return {"status":"error","message":"Нет прав"}
        cur.execute("SELECT amount FROM users WHERE id = %s", (req.user_id,))
        u = cur.fetchone()
        if int(u['amount']) < r['amount']: return {"status":"error","message":"Мало Br"}
        cur.execute("UPDATE users SET amount = amount - %s WHERE id = %s", (r['amount'], r['receiver_id']))
        cur.execute("UPDATE users SET amount = amount + %s WHERE id = %s", (r['amount'], r['sender_id']))
        cur.execute("UPDATE money_requests SET status = 'accepted' WHERE id = %s", (req.request_id,))
        cur.execute("INSERT INTO messages (sender_id, sender_name, receiver_id, text, created_at) VALUES (%s, %s, %s, %s, %s)", (r['receiver_id'], "Система", r['sender_id'], f"✅ Запрос на {r['amount']} Br принят!", int(time.time())))
        cur.close()
    return {"status":"ok"}

@app.post("/api/request_money/decline")
def decline_request(req: RequestAction):
    with db_conn() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE money_requests SET status = 'declined' WHERE id = %s AND receiver_id = %s", (req.request_id, req.user_id))
        cur.close()
    return {"status":"ok"}

@app.post("/api/admin/broadcast")
def admin_broadcast(req: BroadcastRequest):
    if not is_admin(req.admin_id): return {"status": "error"}
    with db_conn() as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO messages (sender_id, sender_name, receiver_id, text, created_at) VALUES (%s, %s, 0, %s, %s)", (MAIN_ADMIN_ID, "📢 Администрация", req.text, int(time.time())))
        cur.close()
    return {"status": "ok", "message": "Рассылка отправлена!"}

@app.post("/api/admin/set_tier_discount")
def admin_set_tier_discount(req: TierDiscountRequest):
    if not is_admin(req.admin_id): return {"status": "error"}
    if req.percent < 0 or req.percent > 90: return {"status": "error"}
    with db_conn() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT tiers FROM companies WHERE id = %s", (req.company_id,))
        row = cur.fetchone()
        if not row: return {"status": "error"}
        tiers = safe_json_load(row['tiers'], [])
        if 0 <= req.tier_index < len(tiers):
            tiers[req.tier_index]['discount'] = req.percent
            cur.execute("UPDATE companies SET tiers = %s WHERE id = %s", (json.dumps(tiers), req.company_id))
            cur.close()
            return {"status": "ok", "message": f"Скидка {req.percent}% установлена!"}
        cur.close()
    return {"status": "error"}

@app.post("/api/admin/add_money")
def admin_add_money(req: AdminMoneyRequest):
    if not is_admin(req.admin_id): return {"status": "error"}
    if req.admin_id != MAIN_ADMIN_ID and req.amount > 500000:
        return {"status": "error", "message": "❌ Лимит! Обычные админы могут выдать не более 500 000 Br."}
    with db_conn() as conn:
        cur = conn.cursor(); cur.execute("UPDATE users SET amount = amount + %s WHERE id = %s", (req.amount, req.target_id)); cur.close()
    return {"status": "ok"}

@app.post("/api/admin/remove_apartment")
def admin_remove_apartment(req: AdminRemoveAptRequest):
    if not is_admin(req.admin_id): return {"status": "error"}
    with db_conn() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT apartments FROM users WHERE id = %s", (req.target_id,))
        row = cur.fetchone()
        if row:
            apts = safe_json_load(row['apartments'], [])
            if 0 <= req.apt_index < len(apts):
                apts.pop(req.apt_index)
                cur.execute("UPDATE users SET apartments = %s WHERE id = %s", (json.dumps(apts), req.target_id))
        cur.close()
    return {"status": "ok"}

@app.post("/api/delete_apt")
def delete_apartment(req: DeleteAptRequest):
    with db_conn() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT apartments FROM users WHERE id = %s", (req.user_id,)); row = cur.fetchone()
        apts = safe_json_load(row['apartments'], [])
        if req.apartment_index < 0 or req.apartment_index >= len(apts): return {"status": "error"}
        apts.pop(req.apartment_index)
        cur.execute("UPDATE users SET apartments = %s WHERE id = %s", (json.dumps(apts), req.user_id)); cur.close()
    return {"status": "ok", "message": "Квартира удалена"}

# БИЗНЕСЫ ИЗ ТЕТРАДИ
BUSINESS_POOL = [
    {"name": "Склад", "rarity": "Обычный", "price": 550000, "income": 4500, "req": 1, "weight": 5},
    {"name": "Кабинет", "rarity": "Обычный", "price": 3000000, "income": 5200, "req": 1, "weight": 7},
    {"name": "Центр зал", "rarity": "Редкий", "price": 4500000, "income": 25750, "req": 2, "weight": 10},
    {"name": "Маленький", "rarity": "Редкий", "price": 10000000, "income": 61950, "req": 2, "weight": 16},
    {"name": "Супермаркет", "rarity": "Эпик", "price": 15000000, "income": 44500, "req": 3, "weight": 20},
    {"name": "Киоск", "rarity": "Эпик", "price": 18000000, "income": 100000, "req": 3, "weight": 21},
    {"name": "Нефтяная", "rarity": "Мифик", "price": 65000000, "income": 450500, "req": 5, "weight": 30},
    {"name": "Это офис", "rarity": "Мега", "price": 93850900, "income": 534550, "req": 5, "weight": 35},
    {"name": "Рынок", "rarity": "Мега", "price": 100500000, "income": 1150000, "req": 8, "weight": 37},
    {"name": "Элитный район", "rarity": "Мега", "price": 250000000, "income": 3000000, "req": 8, "weight": 41},
    {"name": "Небоскреб", "rarity": "Ультра", "price": 550000000, "income": 5600000, "req": 12, "weight": 46},
    {"name": "Завод мини", "rarity": "Хром", "price": 1000500000, "income": 11600000, "req": 15, "weight": 55}
]

def get_weighted_business():
    total = sum(b['weight'] for b in BUSINESS_POOL)
    r = random.uniform(0, total); upto = 0
    for b in BUSINESS_POOL:
        if upto + b['weight'] >= r: return b
        upto += b['weight']
    return BUSINESS_POOL[0]

@app.get("/api/businesses/{user_id}")
def get_businesses(user_id: int):
    with db_conn() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT last_roll, daily_businesses FROM users WHERE id = %s", (user_id,))
        row = cur.fetchone()
        now = int(time.time())
        if now - int(row['last_roll'] or 0) > 86400:
            rolled = []
            while len(rolled) < 2:
                b = get_weighted_business()
                if b not in rolled: rolled.append(b)
            cur.execute("UPDATE users SET last_roll = %s, daily_businesses = %s WHERE id = %s", (now, json.dumps(rolled), user_id))
            daily = rolled
        else:
            daily = safe_json_load(row['daily_businesses'], [])
        cur.close()
    return {"businesses": daily}

@app.post("/api/buy_business")
def buy_business(req: BusinessBuyRequest):
    with db_conn() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT amount, apartments, businesses, daily_businesses FROM users WHERE id = %s", (req.user_id,))
        row = cur.fetchone()
        daily = safe_json_load(row['daily_businesses'], [])
        owned = safe_json_load(row['businesses'], [])
        apts = safe_json_load(row['apartments'], [])
        
        if len(owned) >= 1:
            return {"status": "error", "message": "У вас уже есть компания! Максимум 1."}
            
        if req.business_index < 0 or req.business_index >= len(daily): return {"status": "error", "message": "Бизнес не найден"}
        bus = daily[req.business_index]
        if len(apts) < bus['req']: return {"status": "error", "message": f"Нужно {bus['req']} квартир!"}
        if int(row['amount']) < bus['price']: return {"status": "error", "message": "Мало Br"}
        
        new_amount = int(row['amount']) - bus['price']
        owned.append({"name": bus['name'], "income": bus['income'], "rarity": bus['rarity'], "buy_price": bus['price']})
        daily.pop(req.business_index)
        cur.execute("UPDATE users SET amount=%s, businesses=%s, daily_businesses=%s WHERE id=%s", (new_amount, json.dumps(owned), json.dumps(daily), req.user_id))
        cur.close()
    return {"status": "ok", "message": f"Куплен {bus['name']}!"}

@app.post("/api/sell_business")
def sell_business(req: SellBusinessRequest):
    with db_conn() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT amount, businesses FROM users WHERE id = %s", (req.user_id,))
        row = cur.fetchone()
        bus = safe_json_load(row['businesses'], [])
        if len(bus) == 0: return {"status": "error", "message": "Нет компании"}
        
        b = bus[0]
        price = b.get('buy_price', 50000)
        sell_price = int(price * 0.7)
        
        cur.execute("UPDATE users SET amount = amount + %s, businesses = '[]'::jsonb WHERE id = %s", (sell_price, req.user_id))
        cur.close()
    return {"status": "ok", "message": f"Продано за {sell_price} Br"}

@app.get("/api/companies")
def get_companies():
    with db_conn() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT id, name, tiers FROM companies ORDER BY id ASC")
        rows = cur.fetchall(); cur.close()
    comps = []
    for r in rows:
        tiers = safe_json_load(r['tiers'], [])
        for t in tiers:
            disc = t.get('discount', 0)
            t['old_price'] = t['price']
            t['price'] = int(t['price'] * (1 - disc / 100.0))
        tiers.sort(key=lambda x: x['price'])
        comps.append({"id": r['id'], "name": r['name'], "tiers": tiers})
    comps.sort(key=lambda x: x['tiers'][0]['price'] if x['tiers'] else 0)
    return {"companies": comps}

@app.get("/api/balance/{user_id}")
def get_balance(user_id: int, name: str = "Игрок"):
    try:
        with db_conn() as conn:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
            row = cur.fetchone()
            now = int(time.time())
            if not row:
                card_num = "1234" + "".join(str(random.randint(0, 9)) for _ in range(12))
                card_fmt = " ".join(card_num[i:i+4] for i in range(0, 16, 4))
                cvc = str(random.randint(100, 999))
                cur.execute("INSERT INTO users (id, name, amount, last_payout, card_number, card_cvc) VALUES (%s, %s, %s, %s, %s, %s)", (user_id, name, 510000, now, card_fmt, cvc))
                cur.close()
                return {"balance": 510000, "apartments": [], "businesses": [], "earned": 0, "card_number": card_fmt, "card_cvc": cvc, "name": name, "portfolio": {}}

            cb = int(row['amount'])
            apts = safe_json_load(row['apartments'], [])
            buses = safe_json_load(row['businesses'], [])
            port = safe_json_load(row.get('portfolio'), {})
            lp = int(row['last_payout']) if row['last_payout'] else now

            if len(buses) > 1:
                buses.sort(key=lambda x: x.get('buy_price', 0), reverse=True)
                buses = [buses[0]]
                cur.execute("UPDATE users SET businesses = %s WHERE id = %s", (json.dumps(buses), user_id))

            nb, nl, earned = calculate_income(cb, apts, buses, lp)
            cur.execute("UPDATE users SET amount = %s, last_payout = %s WHERE id = %s", (nb, nl, user_id))
            cur.close()
        return {"balance": nb, "apartments": apts, "businesses": buses, "earned": earned, "card_number": row['card_number'], "card_cvc": row['card_cvc'], "name": row['name'], "portfolio": port}
    except Exception as e: return {"balance": 0, "error": str(e)}

@app.get("/api/check_admin/{user_id}")
def check_admin(user_id: int): return {"is_admin": is_admin(user_id)}

@app.post("/api/set_name")
def set_name(req: SetNameRequest):
    with db_conn() as conn:
        cur = conn.cursor(); cur.execute("UPDATE users SET name = %s WHERE id = %s", (req.name, req.user_id)); cur.close()
    return {"status": "ok"}

@app.get("/api/all_users")
def get_all_users_for_transfer():
    with db_conn() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor); cur.execute("SELECT id, name FROM users ORDER BY amount DESC LIMIT 50"); rows = cur.fetchall(); cur.close()
    return {"users": [{"id": r['id'], "name": r['name']} for r in rows]}

@app.post("/api/admin/add_company")
def add_company(req: AdminCompanyRequest):
    if not is_admin(req.admin_id): return {"status": "error"}
    with db_conn() as conn:
        cur = conn.cursor(); cur.execute("INSERT INTO companies (name, tiers) VALUES (%s, '[]')", (req.company_name,)); cur.close()
    return {"status": "ok"}

@app.post("/api/admin/add_tier/{company_id}")
def add_tier(company_id: int, req: AdminCompanyRequest):
    if not is_admin(req.admin_id): return {"status": "error"}
    with db_conn() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor); cur.execute("SELECT tiers FROM companies WHERE id = %s", (company_id,))
        tiers = safe_json_load(cur.fetchone()['tiers'], []); tiers.append(req.tier_data)
        cur.execute("UPDATE companies SET tiers = %s WHERE id = %s", (json.dumps(tiers), company_id)); cur.close()
    return {"status": "ok"}

@app.post("/api/admin/delete_company/{company_id}")
def delete_company(company_id: int, req: AdminCompanyRequest):
    if not is_admin(req.admin_id): return {"status": "error"}
    with db_conn() as conn:
        cur = conn.cursor(); cur.execute("DELETE FROM companies WHERE id = %s", (company_id,)); cur.close()
    return {"status": "ok"}

@app.post("/api/buy")
def buy_apartment(req: BuyRequest):
    with db_conn() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT amount, apartments FROM users WHERE id = %s", (req.user_id,)); row = cur.fetchone()
        if int(row['amount']) < req.price: return {"status": "error", "message": "Мало Br"}
        apts = safe_json_load(row['apartments'], []); apts.append({"name": req.apartment_name, "income": req.income, "buy_price": req.price})
        cur.execute("UPDATE users SET amount = amount - %s, apartments = %s WHERE id = %s", (req.price, json.dumps(apts), req.user_id)); cur.close()
    return {"status": "ok", "message": "Куплено!"}

@app.post("/api/sell")
def sell_apartment(req: SellRequest):
    with db_conn() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT amount, apartments FROM users WHERE id = %s", (req.user_id,)); row = cur.fetchone()
        apts = safe_json_load(row['apartments'], [])
        if req.apartment_index < 0 or req.apartment_index >= len(apts): return {"status": "error"}
        sell_price = int(req.price * 0.7); apts.pop(req.apartment_index)
        cur.execute("UPDATE users SET amount = amount + %s, apartments = %s WHERE id = %s", (sell_price, json.dumps(apts), req.user_id)); cur.close()
    return {"status": "ok", "message": f"Продана за {sell_price} Br"}

@app.post("/api/transfer")
def transfer_money(req: TransferRequest):
    with db_conn() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT amount FROM users WHERE id = %s", (req.sender_id,)); sender = cur.fetchone()
        if not sender or int(sender['amount']) < req.amount: return {"status": "error", "message": "Мало средств"}
        cur.execute("SELECT name FROM users WHERE id = %s", (req.receiver_id,)); r = cur.fetchone()
        if not r: return {"status": "error", "message": "Игрок не найден"}
        cur.execute("UPDATE users SET amount = amount - %s WHERE id = %s", (req.amount, req.sender_id))
        cur.execute("UPDATE users SET amount = amount + %s WHERE id = %s", (req.amount, req.receiver_id)); cur.close()
    return {"status": "ok", "message": f"Переведено {req.amount} Br игроку {r['name']}"}

@app.get("/api/leaderboard")
def get_leaderboard():
    with db_conn() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor); cur.execute("SELECT name, amount FROM users ORDER BY amount DESC LIMIT 5"); rows = cur.fetchall(); cur.close()
    return {"leaders": [{"name": r['name'], "balance": int(r['amount'])} for r in rows]}

@app.get("/api/admin/users")
def admin_get_users(admin_id: int):
    if not is_admin(admin_id): return {"users": []}
    with db_conn() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor); cur.execute("SELECT id, name, amount, apartments FROM users"); rows = cur.fetchall(); cur.close()
    return {"users": [{"id": r['id'], "name": r['name'], "balance": int(r['amount']), "apts_count": len(safe_json_load(r['apartments'], []))} for r in rows]}

@app.post("/api/admin/remove_money")
def admin_remove_money(req: AdminMoneyRequest):
    if not is_admin(req.admin_id): return {"status": "error"}
    with db_conn() as conn:
        cur = conn.cursor(); cur.execute("UPDATE users SET amount = GREATEST(0, amount - %s) WHERE id = %s", (req.amount, req.target_id)); cur.close()
    return {"status": "ok"}

@app.get("/api/admin/user_apartments/{user_id}")
def admin_get_user_apts(user_id: int):
    with db_conn() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor); cur.execute("SELECT apartments FROM users WHERE id = %s", (user_id,)); row = cur.fetchone(); cur.close()
    return {"apartments": safe_json_load(row['apartments'], []) if row else []}

@app.get("/api/admin/user_business/{user_id}")
def admin_get_user_business(user_id: int):
    with db_conn() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor); cur.execute("SELECT businesses FROM users WHERE id = %s", (user_id,)); row = cur.fetchone(); cur.close()
    return {"businesses": safe_json_load(row['businesses'], []) if row else []}

@app.post("/api/admin/remove_business")
def admin_remove_business(req: AdminMoneyRequest):
    if not is_admin(req.admin_id): return {"status": "error"}
    with db_conn() as conn:
        cur = conn.cursor(); cur.execute("UPDATE users SET businesses = '[]'::jsonb WHERE id = %s", (req.target_id,)); cur.close()
    return {"status": "ok"}

@app.post("/api/admin/reset_all")
def admin_reset_all(req: AdminMoneyRequest):
    if req.admin_id != MAIN_ADMIN_ID: return {"status": "error"}
    with db_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM users"); cur.execute("DELETE FROM messages"); cur.execute("DELETE FROM money_requests"); cur.execute("DELETE FROM friends")
        cur.close()
    return {"status": "ok", "message": "Все сброшено!"}

@app.post("/api/admin/add_admin")
def add_admin(req: AdminAdminRequest):
    if req.admin_id != MAIN_ADMIN_ID: return {"status": "error"}
    with db_conn() as conn:
        cur = conn.cursor(); cur.execute("INSERT INTO admins (user_id) VALUES (%s) ON CONFLICT DO NOTHING", (req.target_id,)); cur.close()
    return {"status": "ok"}

@app.post("/api/admin/remove_admin")
def remove_admin(req: AdminAdminRequest):
    if req.admin_id != MAIN_ADMIN_ID: return {"status": "error"}
    with db_conn() as conn:
        cur = conn.cursor(); cur.execute("DELETE FROM admins WHERE user_id = %s", (req.target_id,)); cur.close()
    return {"status": "ok"}

@app.get("/api/admin/list_admins")
def list_admins(admin_id: int):
    if not is_admin(admin_id): return {"admins": []}
    with db_conn() as conn:
        cur = conn.cursor(); cur.execute("SELECT user_id FROM admins"); rows = cur.fetchall(); cur.close()
    return {"admins": [MAIN_ADMIN_ID] + [r[0] for r in rows]}
