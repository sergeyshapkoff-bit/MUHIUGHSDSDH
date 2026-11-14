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
    except Exception: return False


def get_current_rates():
    h = int(time.time()) // 3600
    rng = random.Random(h)
    base = {"silver": 50, "gold": 500, "diamonds": 5000, "bitcoin": 65000, "tesla": 250}
    out = {}
    for k, b in base.items():
        ch = rng.uniform(-0.05, 0.05)
        out[k] = {"price": int(b * (1 + ch)), "trend": "up" if ch > 0 else "down"}
    return out


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
    for attempt in range(1, 4):
        try:
            with db_conn() as conn:
                cur = conn.cursor()
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        id bigint primary key, name text, amount bigint default 220000,
                        apartments jsonb default '[]'::jsonb, businesses jsonb default '[]'::jsonb,
                        last_payout bigint, last_roll bigint default 0,
                        daily_businesses jsonb default '[]'::jsonb,
                        card_number text, card_cvc text,
                        portfolio jsonb default '{}'::jsonb
                    );
                """)
                cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS portfolio jsonb DEFAULT '{}'::jsonb;")
                cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS apartments jsonb DEFAULT '[]'::jsonb;")
                cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS businesses jsonb DEFAULT '[]'::jsonb;")
                cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS daily_businesses jsonb DEFAULT '[]'::jsonb;")
                cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_roll bigint DEFAULT 0;")

                cur.execute("CREATE TABLE IF NOT EXISTS companies (id serial primary key, name text, tiers jsonb default '[]'::jsonb);")
                cur.execute("CREATE TABLE IF NOT EXISTS admins (user_id bigint primary key);")
                
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS messages (
                        id serial primary key,
                        sender_id bigint, sender_name text,
                        receiver_id bigint, text text, created_at bigint
                    );
                """)
                
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS money_requests (
                        id serial primary key,
                        sender_id bigint, sender_name text,
                        receiver_id bigint, amount bigint,
                        status text default 'pending', created_at bigint
                    );
                """)
                
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS friends (
                        id serial primary key,
                        user1_id bigint,
                        user2_id bigint,
                        status text default 'pending',
                        action_user_id bigint,
                        created_at bigint,
                        UNIQUE(user1_id, user2_id)
                    );
                """)
                
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS settings (
                        key text primary key, value text
                    );
                """)
                cur.execute("INSERT INTO settings (key, value) VALUES ('apt_discount', '0') ON CONFLICT DO NOTHING;")
                
                cur.execute("SELECT COUNT(*) FROM companies")
                if cur.fetchone()[0] == 0:
                    for comp in DEFAULT_COMPANIES:
                        cur.execute("INSERT INTO companies (name, tiers) VALUES (%s, %s)",
                                    (comp['name'], json.dumps(comp['tiers'])))
                
                # АВТООЧИСТКА: Удаляем лишние компании у игроков (если было больше 1)
                cur.execute("SELECT id, businesses FROM users")
                for u_row in cur.fetchall():
                    u_id, b_json = u_row
                    b_list = safe_json_load(b_json, [])
                    if len(b_list) > 1:
                        b_list.sort(key=lambda x: x.get('buy_price', 0), reverse=True)
                        cur.execute("UPDATE users SET businesses = %s WHERE id = %s", (json.dumps([b_list[0]]), u_id))

                cur.close()
            print(f"✅ init_db OK (attempt {attempt})")
            return True
        except Exception as e:
            print(f"❌ init_db attempt {attempt} failed: {type(e).__name__}: {e}")
            if attempt < 3: time.sleep(2 * attempt)
    return False

init_db()

class BuyRequest(BaseModel): user_id: int; user_name: str; apartment_name: str; price: int; income: int
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
class DiscountRequest(BaseModel): admin_id: int; percent: int
class TierDiscountRequest(BaseModel): admin_id: int; company_id: int; tier_index: int; percent: int
class MoneyRequestModel(BaseModel): sender_id: int; receiver_id: int; amount: int
class RequestAction(BaseModel): request_id: int; user_id: int
class FriendRequest(BaseModel): sender_id: int; receiver_id: int
class FriendAction(BaseModel): user_id: int; other_id: int


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


# --- ЧАТЫ И ДРУЗЬЯ ---

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
            elif f['status'] == 'pending':
                friend_map[other] = 'pending_out' if f['action_user_id'] == user_id else 'pending_in'

        cur.execute("""
            SELECT u.id, u.name, MAX(m.created_at) as last_msg
            FROM users u
            LEFT JOIN messages m ON (m.sender_id = u.id AND m.receiver_id = %s) OR (m.sender_id = %s AND m.receiver_id = u.id)
            WHERE u.id != %s
            GROUP BY u.id, u.name
            ORDER BY last_msg DESC NULLS LAST, u.amount DESC
            LIMIT 100
        """, (user_id, user_id, user_id))
        users = cur.fetchall()
        
        chats = [{"id": 0, "name": "📢 Администрация", "status": "admin"}]
        for u in users:
            st = friend_map.get(u['id'], 'none')
            chats.append({"id": u['id'], "name": u['name'], "status": st})
            
        cur.close()
    return {"chats": chats}

@app.get("/api/chat_history/{user_id}/{other_id}")
def get_chat_history(user_id: int, other_id: int):
    with db_conn() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        if other_id == 0:
            cur.execute("SELECT * FROM messages WHERE receiver_id = 0 ORDER BY created_at ASC LIMIT 100")
        else:
            cur.execute("SELECT * FROM messages WHERE (sender_id = %s AND receiver_id = %s) OR (sender_id = %s AND receiver_id = %s) ORDER BY created_at ASC LIMIT 100", (user_id, other_id, other_id, user_id))
        msgs = cur.fetchall()

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
            cur.execute("""
                SELECT 1 FROM friends
                WHERE status = 'accepted'
                AND ((user1_id = %s AND user2_id = %s) OR (user1_id = %s AND user2_id = %s))
            """, (req.sender_id, req.receiver_id, req.receiver_id, req.sender_id))
            if not cur.fetchone():
                return {"status": "error", "message": "Вы не друзья! Отправьте запрос в друзья."}

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
    if req.amount <= 0: return {"status": "error", "message": "Сумма > 0"}
    with db_conn() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT 1 FROM friends
            WHERE status = 'accepted'
            AND ((user1_id = %s AND user2_id = %s) OR (user1_id = %s AND user2_id = %s))
        """, (req.sender_id, req.receiver_id, req.receiver_id, req.sender_id))
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
        if int(u['amount']) < r['amount']: return {"status":"error","message":"Мало денег"}
        cur.execute("UPDATE users SET amount = amount - %s WHERE id = %s", (r['amount'], r['receiver_id']))
        cur.execute("UPDATE users SET amount = amount + %s WHERE id = %s", (r['amount'], r['sender_id']))
        cur.execute("UPDATE money_requests SET status = 'accepted' WHERE id = %s", (req.request_id,))
        cur.execute("INSERT INTO messages (sender_id, sender_name, receiver_id, text, created_at) VALUES (%s, %s, %s, %s, %s)", (r['receiver_id'], "Система", r['sender_id'], f"✅ Запрос на {r['amount']} $ принят!", int(time.time())))
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
    if not is_admin(req.admin_id): return {"status": "error", "message": "Нет прав"}
    if req.percent < 0 or req.percent > 90: return {"status": "error", "message": "Скидка 0-90%"}
    
    with db_conn() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT tiers FROM companies WHERE id = %s", (req.company_id,))
        row = cur.fetchone()
        if not row: return {"status": "error", "message": "Компания не найдена"}
        
        tiers = safe_json_load(row['tiers'], [])
        if 0 <= req.tier_index < len(tiers):
            tiers[req.tier_index]['discount'] = req.percent
            cur.execute("UPDATE companies SET tiers = %s WHERE id = %s", (json.dumps(tiers), req.company_id))
            cur.close()
            return {"status": "ok", "message": f"Скидка {req.percent}% установлена!"}
        cur.close()
    return {"status": "error", "message": "Тариф не найден"}

@app.post("/api/admin/add_money")
def admin_add_money(req: AdminMoneyRequest):
    if not is_admin(req.admin_id): return {"status": "error", "message": "Нет прав"}
    
    if req.admin_id != MAIN_ADMIN_ID and req.amount > 300000:
        return {"status": "error", "message": "❌ Лимит! Обычные админы могут выдать не более 300 000 $ за раз."}
        
    with db_conn() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE users SET amount = amount + %s WHERE id = %s", (req.amount, req.target_id))
        cur.close()
    return {"status": "ok"}


# --- БИЗНЕСЫ ---
BUSINESS_POOL = [
    {"name": "Киоск", "rarity": "Common", "price": 50000, "income": 1000, "req": 1, "weight": 50},
    {"name": "Кофейня", "rarity": "Rare", "price": 250000, "income": 6000, "req": 2, "weight": 25},
    {"name": "Автосервис", "rarity": "Epic", "price": 1500000, "income": 40000, "req": 3, "weight": 15},
    {"name": "Завод", "rarity": "Mythic", "price": 15000000, "income": 450000, "req": 5, "weight": 7},
    {"name": "Нефтевышка", "rarity": "Legendary", "price": 150000000, "income": 5000000, "req": 8, "weight": 2.5},
    {"name": "Космопорт", "rarity": "Chromatic", "price": 2000000000, "income": 80000000, "req": 12, "weight": 0.5}
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
        
        # Проверка на 1 компанию
        if len(owned) >= 1:
            return {"status": "error", "message": "У вас уже есть компания! Максимум 1."}
            
        if req.business_index < 0 or req.business_index >= len(daily): return {"status": "error", "message": "Бизнес не найден"}
        bus = daily[req.business_index]
        if len(apts) < bus['req']: return {"status": "error", "message": f"Нужно {bus['req']} квартир!"}
        if int(row['amount']) < bus['price']: return {"status": "error", "message": "Мало денег"}
        
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
    return {"status": "ok", "message": f"Продано за {sell_price} $"}

# --- ОСТАЛЬНОЕ ---

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
                card_num = "4" + "".join(str(random.randint(0, 9)) for _ in range(15))
                card_fmt = " ".join(card_num[i:i+4] for i in range(0, 16, 4))
                cvc = str(random.randint(100, 999))
                cur.execute("INSERT INTO users (id, name, amount, last_payout, card_number, card_cvc) VALUES (%s, %s, %s, %s, %s, %s)", (user_id, name, 220000, now, card_fmt, cvc))
                cur.close()
                return {"balance": 220000, "apartments": [], "businesses": [], "earned": 0, "card_number": card_fmt, "card_cvc": cvc, "name": name, "portfolio": {}}

            cb = int(row['amount'])
            apts = safe_json_load(row['apartments'], [])
            buses = safe_json_load(row['businesses'], [])
            port = safe_json_load(row.get('portfolio'), {})
            lp = int(row['last_payout']) if row['last_payout'] else now

            # АВТООЧИСТКА ПРИ ЗАГРУЗКЕ (если у игрока оказалось 2+ компании)
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

@app.get("/api/token_rates")
def get_rates(): return get_current_rates()

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

@app.post("/api/trade_token")
def trade_token(req: TokenRequest):
    rates = get_current_rates()
    if req.token_type not in rates: return {"status": "error"}
    cost = req.amount * rates[req.token_type]['price']
    with db_conn() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT amount, portfolio FROM users WHERE id = %s", (req.user_id,)); row = cur.fetchone()
        port = safe_json_load(row['portfolio'], {}); cur_qty = int(port.get(req.token_type, 0))
        if req.action == "buy":
            if int(row['amount']) < cost: return {"status": "error", "message": "Мало денег"}
            port[req.token_type] = cur_qty + req.amount
            cur.execute("UPDATE users SET amount = amount - %s, portfolio = %s WHERE id = %s", (cost, json.dumps(port), req.user_id))
        else:
            if cur_qty < req.amount: return {"status": "error", "message": "Мало токенов"}
            port[req.token_type] = cur_qty - req.amount
            cur.execute("UPDATE users SET amount = amount + %s, portfolio = %s WHERE id = %s", (cost, json.dumps(port), req.user_id))
        cur.close()
    return {"status": "ok", "message": "Сделка успешна!"}

@app.post("/api/buy")
def buy_apartment(req: BuyRequest):
    with db_conn() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT amount, apartments FROM users WHERE id = %s", (req.user_id,)); row = cur.fetchone()
        if int(row['amount']) < req.price: return {"status": "error", "message": "Мало денег"}
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
    return {"status": "ok", "message": f"Продана за {sell_price} $"}

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
    return {"status": "ok", "message": f"Переведено {req.amount} $ игроку {r['name']}"}

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
        cur = conn.cursor(); cur.execute("DELETE FROM users"); cur.execute("DELETE FROM messages"); cur.execute("DELETE FROM money_requests"); cur.execute("DELETE FROM friends"); cur.close()
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
