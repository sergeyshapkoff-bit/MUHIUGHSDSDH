import os

import psycopg2
from psycopg2.extras import RealDictCursor
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

DATABASE_URL = os.getenv("DATABASE_URL")
MAIN_ADMIN_ID = int(os.getenv("MAIN_ADMIN_ID", "5634302903"))
SQM_TAX = 100
LOAN_LIMIT = 1_000_000
LOAN_RATE = 0.10

if not DATABASE_URL:
    raise RuntimeError("Заполни DATABASE_URL в переменных окружения.")

app = FastAPI(title="NEON CITY")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    telegram_id BIGINT PRIMARY KEY,
    nickname TEXT UNIQUE NOT NULL,
    first_name TEXT,
    balance NUMERIC(18,2) NOT NULL DEFAULT 0,
    bank NUMERIC(18,2) NOT NULL DEFAULT 0,
    credit NUMERIC(18,2) NOT NULL DEFAULT 0,
    sqm INTEGER NOT NULL DEFAULT 0,
    card_color TEXT NOT NULL DEFAULT '#7c3aed',
    card_background TEXT NOT NULL DEFAULT '#111827',
    card_image TEXT,
    is_admin BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS friends (
    id BIGSERIAL PRIMARY KEY,
    owner_id BIGINT NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
    friend_id BIGINT NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(owner_id, friend_id)
);

CREATE TABLE IF NOT EXISTS transfers (
    id BIGSERIAL PRIMARY KEY,
    sender_id BIGINT NOT NULL REFERENCES users(telegram_id),
    receiver_id BIGINT NOT NULL REFERENCES users(telegram_id),
    amount NUMERIC(18,2) NOT NULL CHECK (amount > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS loans (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(telegram_id),
    amount NUMERIC(18,2) NOT NULL CHECK (amount > 0),
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS companies (
    id BIGSERIAL PRIMARY KEY,
    category TEXT NOT NULL,
    name TEXT NOT NULL,
    price NUMERIC(18,2) NOT NULL CHECK (price >= 0),
    daily_income NUMERIC(18,2) NOT NULL CHECK (daily_income >= 0),
    sqm INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS user_companies (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
    company_id BIGINT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    purchased_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(user_id, company_id)
);

CREATE TABLE IF NOT EXISTS exchange_items (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    base_price NUMERIC(18,2) NOT NULL,
    min_price NUMERIC(18,2) NOT NULL,
    max_price NUMERIC(18,2) NOT NULL,
    current_price NUMERIC(18,2) NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS exchange_holdings (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
    item_id BIGINT NOT NULL REFERENCES exchange_items(id) ON DELETE CASCADE,
    quantity INTEGER NOT NULL DEFAULT 0 CHECK (quantity >= 0),
    UNIQUE(user_id, item_id)
);

CREATE TABLE IF NOT EXISTS messages (
    id BIGSERIAL PRIMARY KEY,
    sender_id BIGINT NOT NULL REFERENCES users(telegram_id),
    receiver_id BIGINT NOT NULL REFERENCES users(telegram_id),
    text TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_users_nickname
ON users(nickname);

CREATE INDEX IF NOT EXISTS idx_users_balance
ON users(balance DESC);

CREATE INDEX IF NOT EXISTS idx_messages_receiver
ON messages(receiver_id, created_at DESC);
"""

DEFAULT_COMPANIES = [
    ("Магазин", "Киоск", 10_000, 300, 1),
    ("Магазин", "Мини-маркет", 50_000, 1_200, 3),
    ("Магазин", "Супермаркет", 250_000, 5_000, 10),
    ("Кафе", "Кофейня", 100_000, 2_000, 5),
    ("Кафе", "Ресторан", 500_000, 9_000, 15),
    ("Авто", "Автомойка", 150_000, 3_000, 6),
    ("Авто", "Автосалон", 1_000_000, 18_000, 25),
    ("Недвижимость", "Квартира", 300_000, 4_000, 20),
    ("Недвижимость", "Офис", 800_000, 12_000, 40),
    ("Недвижимость", "Торговый центр", 5_000_000, 70_000, 150),
]

DEFAULT_EXCHANGE = [
    ("Gold", 5_000, 3_000, 8_000),
    ("Silver", 2_500, 1_500, 4_000),
    ("Ring", 8_000, 5_000, 12_000),
    ("Tesla", 100_000, 70_000, 150_000),
    ("McDonald's", 250_000, 180_000, 350_000),
    ("Bitcoin", 500_000, 300_000, 900_000),
    ("Ethereum", 300_000, 180_000, 550_000),
    ("Oil", 150_000, 100_000, 250_000),
]


def get_db():
    return psycopg2.connect(DATABASE_URL, connect_timeout=10)


def db_execute(query, params=(), fetch=False):
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, params)
            rows = cur.fetchall() if fetch else None
        conn.commit()
    return rows


def get_user(telegram_id):
    rows = db_execute(
        "SELECT * FROM users WHERE telegram_id = %s",
        (telegram_id,),
        fetch=True,
    )
    return rows[0] if rows else None


def get_user_by_nickname(nickname):
    rows = db_execute(
        "SELECT * FROM users WHERE LOWER(nickname) = LOWER(%s)",
        (nickname,),
        fetch=True,
    )
    return rows[0] if rows else None


def ensure_user(telegram_id, nickname, first_name="Игрок"):
    nickname = nickname.strip()

    if not nickname:
        raise HTTPException(status_code=400, detail="Введите никнейм")

    existing = get_user_by_nickname(nickname)

    if existing and existing["telegram_id"] != telegram_id:
        raise HTTPException(status_code=400, detail="Этот никнейм уже занят")

    db_execute(
        """
        INSERT INTO users (telegram_id, nickname, first_name)
        VALUES (%s, %s, %s)
        ON CONFLICT (telegram_id) DO UPDATE
        SET nickname = EXCLUDED.nickname,
            first_name = EXCLUDED.first_name
        """,
        (telegram_id, nickname, first_name),
    )

    if telegram_id == MAIN_ADMIN_ID:
        db_execute(
            """
            UPDATE users
            SET is_admin = TRUE
            WHERE telegram_id = %s
            """,
            (telegram_id,),
        )

    return get_user(telegram_id)


def is_admin(telegram_id):
    user = get_user(telegram_id)
    return bool(user and user["is_admin"])


def money(value):
    return f"{float(value):,.2f}".replace(",", " ")


class LoginRequest(BaseModel):
    telegram_id: int
    nickname: str
    first_name: str = "Игрок"


class BankRequest(BaseModel):
    telegram_id: int
    amount: float
    action: str


class TransferRequest(BaseModel):
    sender_id: int
    receiver: str
    amount: float


class LoanRequest(BaseModel):
    telegram_id: int
    amount: float


class FriendRequest(BaseModel):
    telegram_id: int
    friend_nickname: str


class CardSettingsRequest(BaseModel):
    telegram_id: int
    card_color: str = "#7c3aed"
    card_background: str = "#111827"
    card_image: str = ""


class CompanyBuyRequest(BaseModel):
    telegram_id: int
    company_id: int


class ExchangeTradeRequest(BaseModel):
    telegram_id: int
    item_id: int
    quantity: int = 1
    action: str


class MessageRequest(BaseModel):
    sender_id: int
    receiver_nickname: str
    text: str


class AdminActionRequest(BaseModel):
    admin_id: int
    target_nickname: str


class GiveMoneyRequest(BaseModel):
    admin_id: int
    target_nickname: str
    amount: float


class AddCompanyRequest(BaseModel):
    admin_id: int
    category: str
    name: str
    price: float
    daily_income: float
    sqm: int


@app.get("/", response_class=HTMLResponse)
def home():
    return """<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NEON CITY</title>
<style>
*{box-sizing:border-box}
body{margin:0;min-height:100vh;font-family:Arial,sans-serif;color:#e5e7eb;background:radial-gradient(circle at 15% 15%,#1e1b4b,transparent 55%),radial-gradient(circle at 85% 10%,#312e81,transparent 50%),#05060f}
.wrap{max-width:1000px;margin:0 auto;padding:24px 16px 70px}
.title{font-size:44px;font-weight:900;text-align:center;color:#fff;text-shadow:0 0 20px #7c3aed,0 0 40px #06b6d4}
.subtitle{text-align:center;color:#94a3b8;margin-bottom:26px}
.card{background:rgba(15,23,42,.85);border:1px solid rgba(124,58,237,.45);border-radius:22px;padding:22px;margin-bottom:18px;box-shadow:0 0 30px rgba(124,58,237,.18)}
input,textarea,select,button{width:100%;padding:13px;border-radius:12px;border:1px solid #334155;background:#0f172a;color:#fff;font-size:15px;margin-bottom:10px}
button{background:linear-gradient(90deg,#7c3aed,#06b6d4);border:none;font-weight:700;cursor:pointer}
button:disabled{opacity:.5}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}
.result{white-space:pre-wrap;margin-top:12px;color:#a5f3fc;font-size:14px}
h2{margin-top:0;color:#c4b5fd}
.hidden{display:none}
.nav{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-bottom:20px}
.nav button{padding:12px}
table{width:100%;border-collapse:collapse;font-size:14px}
th,td{padding:9px;border-bottom:1px solid #1e293b;text-align:left}
th{color:#a78bfa}
.badge{display:inline-block;padding:3px 9px;border-radius:999px;background:#7c3aed;color:#fff;font-size:12px}
</style>
</head>
<body>
<div class="wrap">
<div class="title">NEON CITY</div>
<div class="subtitle">Игровая экономика, бизнес и биржа</div>

<div id="auth" class="card">
<h2>Вход или регистрация</h2>
<input id="login_id" placeholder="Твой Telegram ID">
<input id="login_nick" placeholder="Придумай никнейм">
<input id="login_name" placeholder="Имя">
<button onclick="login()">Войти</button>
<div id="auth_result" class="result"></div>
</div>

<div id="game" class="hidden">
<div class="nav">
<button onclick="show('profile')">Профиль</button>
<button onclick="show('leaderboard')">Лидеры</button>
<button onclick="show('bank')">Банк</button>
<button onclick="show('exchange')">Биржа</button>
<button onclick="show('companies')">Бизнес</button>
<button onclick="show('transfer')">Перевод</button>
<button onclick="show('players')">Игроки</button>
<button onclick="show('chats')">Чаты</button>
<button onclick="show('loans')">Кредит</button>
<button onclick="show('friends')">Друзья</button>
<button onclick="show('settings')">Карта</button>
<button id="admin_button" class="hidden" onclick="show('admin')">Админка</button>
</div>

<div id="profile" class="card hidden">
<h2>Профиль</h2>
<div id="profile_info"></div>
</div>

<div id="leaderboard" class="card hidden">
<h2>Таблица лидеров</h2>
<button onclick="loadLeaderboard()">Обновить</button>
<div id="leaderboard_info"></div>
</div>

<div id="bank" class="card hidden">
<h2>NEON BANK</h2>
<div id="bank_info"></div>
<input id="bank_amount" placeholder="Сумма">
<div class="grid">
<button onclick="bank('deposit')">Положить</button>
<button onclick="bank('withdraw')">Снять</button>
</div>
<div id="bank_result" class="result"></div>
</div>

<div id="exchange" class="card hidden">
<h2>Биржа</h2>
<button onclick="loadExchange()">Обновить цены</button>
<div id="exchange_info"></div>
<input id="exchange_item" placeholder="Название актива">
<input id="exchange_quantity" placeholder="Количество" value="1">
<div class="grid">
<button onclick="trade('buy')">Купить</button>
<button onclick="trade('sell')">Продать</button>
</div>
<div id="exchange_result" class="result"></div>
</div>

<div id="companies" class="card hidden">
<h2>Бизнес и недвижимость</h2>
<button onclick="loadCompanies()">Показать объекты</button>
<input id="company_id" placeholder="ID объекта для покупки">
<button onclick="buyCompany()">Купить объект</button>
<div id="companies_info" class="result"></div>
</div>

<div id="transfer" class="card hidden">
<h2>Перевод игроку</h2>
<input id="receiver_nick" placeholder="Никнейм получателя">
<input id="transfer_amount" placeholder="Сумма">
<button onclick="transfer()">Перевести</button>
<div id="transfer_result" class="result"></div>
</div>

<div id="players" class="card hidden">
<h2>Игроки</h2>
<button onclick="loadPlayers()">Обновить список</button>
<div id="players_info"></div>
</div>

<div id="chats" class="card hidden">
<h2>Сообщения</h2>
<input id="message_nick" placeholder="Никнейм получателя">
<textarea id="message_text" placeholder="Текст сообщения"></textarea>
<button onclick="sendMessage()">Отправить</button>
<button onclick="loadMessages()">Обновить сообщения</button>
<div id="messages_info" class="result"></div>
</div>

<div id="loans" class="card hidden">
<h2>Кредит</h2>
<div id="loan_info"></div>
<input id="loan_amount" placeholder="Сумма кредита">
<button onclick="takeLoan()">Оформить кредит</button>
<div id="loan_result" class="result"></div>
</div>

<div id="friends" class="card hidden">
<h2>Друзья</h2>
<input id="friend_nick" placeholder="Никнейм друга">
<button onclick="addFriend()">Добавить друга</button>
<button onclick="loadFriends()">Показать друзей</button>
<div id="friends_info" class="result"></div>
</div>

<div id="settings" class="card hidden">
<h2>Настройки карты</h2>
<input id="card_color" placeholder="Цвет карты, например #7c3aed">
<input id="card_background" placeholder="Фон карты, например #111827">
<input id="card_image" placeholder="Ссылка на изображение карты">
<button onclick="saveCard()">Сохранить</button>
<div id="card_result" class="result"></div>
</div>

<div id="admin" class="card hidden">
<h2>Админ-панель</h2>
<input id="admin_nick" placeholder="Никнейм игрока">
<div class="grid">
<button onclick="makeAdmin()">Назначить админом</button>
<button onclick="removeAdmin()">Снять админа</button>
</div>
<input id="give_amount" placeholder="Сумма для выдачи">
<button onclick="giveMoney()">Выдать деньги</button>
<input id="company_category" placeholder="Категория бизнеса">
<input id="company_name" placeholder="Название бизнеса">
<input id="company_price" placeholder="Цена">
<input id="company_income" placeholder="Доход в день">
<input id="company_sqm" placeholder="Площадь в км²">
<button onclick="addCompany()">Добавить бизнес</button>
<div id="admin_result" class="result"></div>
</div>
</div>
</div>

<script>
let currentId = null;
let currentUser = null;

async function api(url, data) {
  const response = await fetch(url, {
    method: data ? 'POST' : 'GET',
    headers: {'Content-Type': 'application/json'},
    body: data ? JSON.stringify(data) : undefined
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.detail || 'Ошибка');
  return result;
}

function show(section) {
  document.querySelectorAll('.card').forEach(card => card.classList.add('hidden'));
  document.getElementById(section).classList.remove('hidden');
  if (section === 'profile') loadProfile();
  if (section === 'leaderboard') loadLeaderboard();
  if (section === 'bank') loadBank();
  if (section === 'exchange') loadExchange();
  if (section === 'companies') loadCompanies();
  if (section === 'players') loadPlayers();
  if (section === 'chats') loadMessages();
  if (section === 'loans') loadLoan();
  if (section === 'friends') loadFriends();
}

async function login() {
  try {
    const data = await api('/api/login', {
      telegram_id: Number(document.getElementById('login_id').value),
      nickname: document.getElementById('login_nick').value,
      first_name: document.getElementById('login_name').value || 'Игрок'
    });
    currentId = data.telegram_id;
    currentUser = data;
    document.getElementById('auth').classList.add('hidden');
    document.getElementById('game').classList.remove('hidden');
    if (data.is_admin) document.getElementById('admin_button').classList.remove('hidden');
    show('profile');
  } catch (error) {
    document.getElementById('auth_result').textContent = error.message;
  }
}

async function loadProfile() {
  const user = await api('/api/profile?telegram_id=' + currentId);
  document.getElementById('profile_info').innerHTML =
    '<p><b>Ник:</b> ' + user.nickname + '</p>' +
    '<p><b>Telegram ID:</b> ' + user.telegram_id + '</p>' +
    '<p><b>Наличные:</b> ' + user.balance + ' BYN</p>' +
    '<p><b>Банк:</b> ' + user.bank + ' BYN</p>' +
    '<p><b>Кредит:</b> ' + user.credit + ' BYN</p>' +
    '<p><b>Земля:</b> ' + user.sqm + ' км²</p>' +
    '<p><span class="badge">' + (user.is_admin ? 'Администратор' : 'Игрок') + '</span></p>';
}

async function loadLeaderboard() {
  const players = await api('/api/leaderboard');
  let html = '<table><tr><th>Место</th><th>Ник</th><th>Баланс</th><th>Земля</th></tr>';
  players.forEach((player, index) => {
    html += '<tr><td>' + (index + 1) + '</td><td>' + player.nickname + '</td><td>' + player.balance + ' BYN</td><td>' + player.sqm + ' км²</td></tr>';
  });
  document.getElementById('leaderboard_info').innerHTML = html + '</table>';
}

async function loadBank() {
  const user = await api('/api/profile?telegram_id=' + currentId);
  document.getElementById('bank_info').innerHTML =
    '<p><b>Наличные:</b> ' + user.balance + ' BYN</p>' +
    '<p><b>На карте:</b> ' + user.bank + ' BYN</p>';
}

async function bank(action) {
  try {
    const data = await api('/api/bank', {
      telegram_id: currentId,
      amount: Number(document.getElementById('bank_amount').value),
      action
    });
    document.getElementById('bank_result').textContent = data.message;
    loadBank();
  } catch (error) {
    document.getElementById('bank_result').textContent = error.message;
  }
}

async function loadExchange() {
  const items = await api('/api/exchange');
  let html = '<table><tr><th>Актив</th><th>Цена</th><th>Минимум</th><th>Максимум</th></tr>';
  items.forEach(item => {
    html += '<tr><td>' + item.name + '</td><td>' + item.current_price + ' BYN</td><td>' + item.min_price + '</td><td>' + item.max_price + '</td></tr>';
  });
  document.getElementById('exchange_info').innerHTML = html + '</table>';
}

async function trade(action) {
  try {
    const items = await api('/api/exchange');
    const name = document.getElementById('exchange_item').value;
    const item = items.find(i => i.name.toLowerCase() === name.toLowerCase());
    if (!item) throw new Error('Актив не найден');
    const data = await api('/api/exchange/trade', {
      telegram_id: currentId,
      item_id: item.id,
      quantity: Number(document.getElementById('exchange_quantity').value),
      action
    });
    document.getElementById('exchange_result').textContent = data.message;
  } catch (error) {
    document.getElementById('exchange_result').textContent = error.message;
  }
}

async function loadCompanies() {
  const companies = await api('/api/companies?telegram_id=' + currentId);
  let html = '<table><tr><th>ID</th><th>Название</th><th>Категория</th><th>Цена</th><th>Доход</th><th>Статус</th></tr>';
  companies.forEach(company => {
    html += '<tr><td>' + company.id + '</td><td>' + company.name + '</td><td>' + company.category + '</td><td>' + company.price + ' BYN</td><td>' + company.daily_income + ' BYN</td><td>' + (company.owned ? 'Куплено' : 'Доступно') + '</td></tr>';
  });
  document.getElementById('companies_info').innerHTML = html + '</table>';
}

async function buyCompany() {
  try {
    const data = await api('/api/companies/buy', {
      telegram_id: currentId,
      company_id: Number(document.getElementById('company_id').value)
    });
    document.getElementById('companies_info').textContent = data.message;
    loadCompanies();
  } catch (error) {
    document.getElementById('companies_info').textContent = error.message;
  }
}

async function transfer() {
  try {
    const data = await api('/api/transfer', {
      sender_id: currentId,
      receiver: document.getElementById('receiver_nick').value,
      amount: Number(document.getElementById('transfer_amount').value)
    });
    document.getElementById('transfer_result').textContent = data.message;
  } catch (error) {
    document.getElementById('transfer_result').textContent = error.message;
  }
}

async function loadPlayers() {
  const players = await api('/api/players');
  let html = '<table><tr><th>Ник</th><th>Баланс</th><th>Статус</th></tr>';
  players.forEach(player => {
    html += '<tr><td>' + player.nickname + '</td><td>' + player.balance + ' BYN</td><td>' + (player.is_admin ? 'Админ' : 'Игрок') + '</td></tr>';
  });
  document.getElementById('players_info').innerHTML = html + '</table>';
}

async function sendMessage() {
  try {
    const data = await api('/api/messages', {
      sender_id: currentId,
      receiver_nickname: document.getElementById('message_nick').value,
      text: document.getElementById('message_text').value
    });
    document.getElementById('messages_info').textContent = data.message;
  } catch (error) {
    document.getElementById('messages_info').textContent = error.message;
  }
}

async function loadMessages() {
  const messages = await api('/api/messages?telegram_id=' + currentId);
  let html = '';
  messages.forEach(message => {
    html += '<p><b>' + message.sender_name + ':</b> ' + message.text + '</p>';
  });
  document.getElementById('messages_info').innerHTML = html || 'Сообщений нет';
}

async function loadLoan() {
  const user = await api('/api/profile?telegram_id=' + currentId);
  document.getElementById('loan_info').innerHTML = '<p><b>Текущий долг:</b> ' + user.credit + ' BYN</p>';
}

async function takeLoan() {
  try {
    const data = await api('/api/loan', {
      telegram_id: currentId,
      amount: Number(document.getElementById('loan_amount').value)
    });
    document.getElementById('loan_result').textContent = data.message;
    loadLoan();
  } catch (error) {
    document.getElementById('loan_result').textContent = error.message;
  }
}

async function addFriend() {
  try {
    const data = await api('/api/friends', {
      telegram_id: currentId,
      friend_nickname: document.getElementById('friend_nick').value
    });
    document.getElementById('friends_info').textContent = data.message;
  } catch (error) {
    document.getElementById('friends_info').textContent = error.message;
  }
}

async function loadFriends() {
  const friends = await api('/api/friends?telegram_id=' + currentId);
  let html = '';
  friends.forEach(friend => {
    html += '<p><b>' + friend.nickname + '</b></p>';
  });
  document.getElementById('friends_info').innerHTML = html || 'Друзей нет';
}

async function saveCard() {
  try {
    const data = await api('/api/card-settings', {
      telegram_id: currentId,
      card_color: document.getElementById('card_color').value,
      card_background: document.getElementById('card_background').value,
      card_image: document.getElementById('card_image').value
    });
    document.getElementById('card_result').textContent = data.message;
  } catch (error) {
    document.getElementById('card_result').textContent = error.message;
  }
}

async function makeAdmin() {
  await adminAction('/api/admin/add', 'Назначен администратором');
}

async function removeAdmin() {
  await adminAction('/api/admin/remove', 'Администратор снят');
}

async function adminAction(url, success) {
  try {
    const data = await api(url, {
      admin_id: currentId,
      target_nickname: document.getElementById('admin_nick').value
    });
    document.getElementById('admin_result').textContent = data.message || success;
  } catch (error) {
    document.getElementById('admin_result').textContent = error.message;
  }
}

async function giveMoney() {
  try {
    const data = await api('/api/admin/give-money', {
      admin_id: currentId,
      target_nickname: document.getElementById('admin_nick').value,
      amount: Number(document.getElementById('give_amount').value)
    });
    document.getElementById('admin_result').textContent = data.message;
  } catch (error) {
    document.getElementById('admin_result').textContent = error.message;
  }
}

async function addCompany() {
  try {
    const data = await api('/api/admin/company', {
      admin_id: currentId,
      category: document.getElementById('company_category').value,
      name: document.getElementById('company_name').value,
      price: Number(document.getElementById('company_price').value),
      daily_income: Number(document.getElementById('company_income').value),
      sqm: Number(document.getElementById('company_sqm').value)
    });
    document.getElementById('admin_result').textContent = data.message;
  } catch (error) {
    document.getElementById('admin_result').textContent = error.message;
  }
}
</script>
</body>
</html>"""


@app.get("/health")
def health():
    try:
        db_execute("SELECT 1", fetch=True)
        return {"status": "ok", "database": "connected"}
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error))


@app.post("/api/login")
def login(data: LoginRequest):
    return ensure_user(data.telegram_id, data.nickname, data.first_name)


@app.get("/api/profile")
def profile(telegram_id: int):
    user = get_user(telegram_id)
    if not user:
        raise HTTPException(status_code=404, detail="Игрок не найден")
    return user


@app.get("/api/leaderboard")
def leaderboard():
    return db_execute(
        """
        SELECT nickname, balance, sqm
        FROM users
        ORDER BY balance DESC, sqm DESC
        LIMIT 50
        """,
        fetch=True,
    )


@app.post("/api/bank")
def bank(data: BankRequest):
    if data.amount <= 0:
        raise HTTPException(status_code=400, detail="Сумма должна быть больше нуля")

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT balance, bank FROM users WHERE telegram_id = %s FOR UPDATE",
                (data.telegram_id,),
            )
            user = cur.fetchone()

            if not user:
                raise HTTPException(status_code=404, detail="Игрок не найден")

            if data.action == "deposit":
                if float(user["balance"]) < data.amount:
                    raise HTTPException(status_code=400, detail="Недостаточно наличных")

                cur.execute(
                    """
                    UPDATE users
                    SET balance = balance - %s, bank = bank + %s
                    WHERE telegram_id = %s
                    """,
                    (data.amount, data.amount, data.telegram_id),
                )
                message = f"Положено в банк: {money(data.amount)} BYN"

            elif data.action == "withdraw":
                if float(user["bank"]) < data.amount:
                    raise HTTPException(status_code=400, detail="Недостаточно денег на карте")

                cur.execute(
                    """
                    UPDATE users
                    SET bank = bank - %s, balance = balance + %s
                    WHERE telegram_id = %s
                    """,
                    (data.amount, data.amount, data.telegram_id),
                )
                message = f"Снято с карты: {money(data.amount)} BYN"

            else:
                raise HTTPException(status_code=400, detail="Неверное действие")

        conn.commit()

    return {"status": "ok", "message": message}


@app.post("/api/transfer")
def transfer(data: TransferRequest):
    receiver = get_user_by_nickname(data.receiver)

    if not receiver:
        raise HTTPException(status_code=404, detail="Игрок с таким ником не найден")

    if data.sender_id == receiver["telegram_id"]:
        raise HTTPException(status_code=400, detail="Нельзя перевести самому себе")

    if data.amount <= 0:
        raise HTTPException(status_code=400, detail="Сумма должна быть больше нуля")

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT balance FROM users WHERE telegram_id = %s FOR UPDATE",
                (data.sender_id,),
            )
            sender = cur.fetchone()

            if not sender or float(sender["balance"]) < data.amount:
                raise HTTPException(status_code=400, detail="Недостаточно денег")

            cur.execute(
                "UPDATE users SET balance = balance - %s WHERE telegram_id = %s",
                (data.amount, data.sender_id),
            )
            cur.execute(
                "UPDATE users SET balance = balance + %s WHERE telegram_id = %s",
                (data.amount, receiver["telegram_id"]),
            )
            cur.execute(
                """
                INSERT INTO transfers (sender_id, receiver_id, amount)
                VALUES (%s, %s, %s)
                """,
                (data.sender_id, receiver["telegram_id"], data.amount),
            )

        conn.commit()

    return {
        "status": "ok",
        "message": f"Переведено {money(data.amount)} BYN игроку {receiver['nickname']}",
    }


@app.post("/api/loan")
def loan(data: LoanRequest):
    if data.amount <= 0 or data.amount > LOAN_LIMIT:
        raise HTTPException(
            status_code=400,
            detail=f"Кредит от 1 до {money(LOAN_LIMIT)} BYN",
        )

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT credit FROM users WHERE telegram_id = %s FOR UPDATE",
                (data.telegram_id,),
            )
            user = cur.fetchone()

            if not user:
                raise HTTPException(status_code=404, detail="Игрок не найден")

            if float(user["credit"]) + data.amount > LOAN_LIMIT:
                raise HTTPException(status_code=400, detail="Превышен кредитный лимит")

            total = data.amount * (1 + LOAN_RATE)

            cur.execute(
                """
                UPDATE users
                SET balance = balance + %s, credit = credit + %s
                WHERE telegram_id = %s
                """,
                (data.amount, total, data.telegram_id),
            )
            cur.execute(
                """
                INSERT INTO loans (user_id, amount, status)
                VALUES (%s, %s, 'approved')
                """,
                (data.telegram_id, data.amount),
            )

        conn.commit()

    return {
        "status": "ok",
        "message": f"Кредит выдан: {money(data.amount)} BYN. К возврату: {money(total)} BYN",
    }


@app.post("/api/friends")
def add_friend(data: FriendRequest):
    friend = get_user_by_nickname(data.friend_nickname)

    if not friend:
        raise HTTPException(status_code=404, detail="Игрок не найден")

    if data.telegram_id == friend["telegram_id"]:
        raise HTTPException(status_code=400, detail="Нельзя добавить себя")

    db_execute(
        """
        INSERT INTO friends (owner_id, friend_id)
        VALUES (%s, %s)
        ON CONFLICT DO NOTHING
        """,
        (data.telegram_id, friend["telegram_id"]),
    )

    return {"status": "ok", "message": f"{friend['nickname']} добавлен в друзья"}


@app.get("/api/friends")
def friends(telegram_id: int):
    return db_execute(
        """
        SELECT u.nickname
        FROM friends f
        JOIN users u ON u.telegram_id = f.friend_id
        WHERE f.owner_id = %s
        ORDER BY u.nickname
        """,
        (telegram_id,),
        fetch=True,
    )


@app.post("/api/card-settings")
def card_settings(data: CardSettingsRequest):
    db_execute(
        """
        UPDATE users
        SET card_color = %s,
            card_background = %s,
            card_image = NULLIF(%s, '')
        WHERE telegram_id = %s
        """,
        (
            data.card_color,
            data.card_background,
            data.card_image,
            data.telegram_id,
        ),
    )
    return {"status": "ok", "message": "Настройки карты сохранены"}


@app.get("/api/companies")
def companies(telegram_id: int):
    return db_execute(
        """
        SELECT c.*,
               EXISTS (
                   SELECT 1 FROM user_companies uc
                   WHERE uc.user_id = %s AND uc.company_id = c.id
               ) AS owned
        FROM companies c
        ORDER BY c.price ASC
        """,
        (telegram_id,),
        fetch=True,
    )


@app.post("/api/companies/buy")
def buy_company(data: CompanyBuyRequest):
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM companies WHERE id = %s",
                (data.company_id,),
            )
            company = cur.fetchone()

            if not company:
                raise HTTPException(status_code=404, detail="Объект не найден")

            cur.execute(
                """
                SELECT 1 FROM user_companies
                WHERE user_id = %s AND company_id = %s
                """,
                (data.telegram_id, data.company_id),
            )
            if cur.fetchone():
                raise HTTPException(status_code=400, detail="Объект уже куплен")

            cur.execute(
                "SELECT balance FROM users WHERE telegram_id = %s FOR UPDATE",
                (data.telegram_id,),
            )
            user = cur.fetchone()

            if not user or float(user["balance"]) < float(company["price"]):
                raise HTTPException(status_code=400, detail="Недостаточно денег")

            cur.execute(
                """
                UPDATE users
                SET balance = balance - %s, sqm = sqm + %s
                WHERE telegram_id = %s
                """,
                (company["price"], company["sqm"], data.telegram_id),
            )
            cur.execute(
                """
                INSERT INTO user_companies (user_id, company_id)
                VALUES (%s, %s)
                ON CONFLICT DO NOTHING
                """,
                (data.telegram_id, data.company_id),
            )

        conn.commit()

    return {
        "status": "ok",
        "message": f"Куплено: {company['name']} за {money(company['price'])} BYN",
    }


@app.get("/api/exchange")
def exchange():
    return db_execute(
        "SELECT * FROM exchange_items ORDER BY base_price ASC",
        fetch=True,
    )


@app.post("/api/exchange/trade")
def exchange_trade(data: ExchangeTradeRequest):
    if data.quantity <= 0:
        raise HTTPException(status_code=400, detail="Количество должно быть больше нуля")

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM exchange_items WHERE id = %s",
                (data.item_id,),
            )
            item = cur.fetchone()

            if not item:
                raise HTTPException(status_code=404, detail="Актив не найден")

            price = float(item["current_price"]) * data.quantity

            cur.execute(
                "SELECT balance FROM users WHERE telegram_id = %s FOR UPDATE",
                (data.telegram_id,),
            )
            user = cur.fetchone()

            if not user:
                raise HTTPException(status_code=404, detail="Игрок не найден")

            if data.action == "buy":
                if float(user["balance"]) < price:
                    raise HTTPException(status_code=400, detail="Недостаточно денег")

                cur.execute(
                    "UPDATE users SET balance = balance - %s WHERE telegram_id = %s",
                    (price, data.telegram_id),
                )
                cur.execute(
                    """
                    INSERT INTO exchange_holdings (user_id, item_id, quantity)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (user_id, item_id)
                    DO UPDATE SET quantity = exchange_holdings.quantity + EXCLUDED.quantity
                    """,
                    (data.telegram_id, data.item_id, data.quantity),
                )
                message = f"Куплено: {item['name']} за {money(price)} BYN"

            elif data.action == "sell":
                cur.execute(
                    """
                    SELECT quantity FROM exchange_holdings
                    WHERE user_id = %s AND item_id = %s FOR UPDATE
                    """,
                    (data.telegram_id, data.item_id),
                )
                holding = cur.fetchone()

                if not holding or holding["quantity"] < data.quantity:
                    raise HTTPException(status_code=400, detail="Недостаточно актива")

                cur.execute(
                    """
                    UPDATE exchange_holdings
                    SET quantity = quantity - %s
                    WHERE user_id = %s AND item_id = %s
                    """,
                    (data.quantity, data.telegram_id, data.item_id),
                )
                cur.execute(
                    "UPDATE users SET balance = balance + %s WHERE telegram_id = %s",
                    (price, data.telegram_id),
                )
                message = f"Продано: {item['name']} за {money(price)} BYN"

            else:
                raise HTTPException(status_code=400, detail="Неверное действие")

        conn.commit()

    return {"status": "ok", "message": message}


@app.get("/api/players")
def players():
    return db_execute(
        """
        SELECT telegram_id, nickname, balance, is_admin
        FROM users
        ORDER BY balance DESC
        LIMIT 100
        """,
        fetch=True,
    )


@app.post("/api/messages")
def send_message(data: MessageRequest):
    receiver = get_user_by_nickname(data.receiver_nickname)

    if not receiver:
        raise HTTPException(status_code=404, detail="Игрок не найден")

    db_execute(
        """
        INSERT INTO messages (sender_id, receiver_id, text)
        VALUES (%s, %s, %s)
        """,
        (data.sender_id, receiver["telegram_id"], data.text),
    )

    return {"status": "ok", "message": f"Сообщение отправлено игроку {receiver['nickname']}"}


@app.get("/api/messages")
def messages(telegram_id: int):
    return db_execute(
        """
        SELECT m.*, u.nickname AS sender_name
        FROM messages m
        JOIN users u ON u.telegram_id = m.sender_id
        WHERE m.receiver_id = %s
        ORDER BY m.created_at DESC
        LIMIT 50
        """,
        (telegram_id,),
        fetch=True,
    )


@app.post("/api/admin/add")
def add_admin(data: AdminActionRequest):
    if not is_admin(data.admin_id):
        raise HTTPException(status_code=403, detail="Только администраторы")

    target = get_user_by_nickname(data.target_nickname)

    if not target:
        raise HTTPException(status_code=404, detail="Игрок не найден")

    db_execute(
        "UPDATE users SET is_admin = TRUE WHERE telegram_id = %s",
        (target["telegram_id"],),
    )

    return {"status": "ok", "message": f"{target['nickname']} назначен администратором"}


@app.post("/api/admin/remove")
def remove_admin(data: AdminActionRequest):
    if not is_admin(data.admin_id):
        raise HTTPException(status_code=403, detail="Только администраторы")

    target = get_user_by_nickname(data.target_nickname)

    if not target:
        raise HTTPException(status_code=404, detail="Игрок не найден")

    if target["telegram_id"] == MAIN_ADMIN_ID:
        raise HTTPException(status_code=400, detail="Главного администратора нельзя снять")

    db_execute(
        "UPDATE users SET is_admin = FALSE WHERE telegram_id = %s",
        (target["telegram_id"],),
    )

    return {"status": "ok", "message": f"{target['nickname']} снят с должности администратора"}


@app.post("/api/admin/give-money")
def give_money(data: GiveMoneyRequest):
    if not is_admin(data.admin_id):
        raise HTTPException(status_code=403, detail="Только администраторы")

    target = get_user_by_nickname(data.target_nickname)

    if not target:
        raise HTTPException(status_code=404, detail="Игрок не найден")

    if data.amount <= 0:
        raise HTTPException(status_code=400, detail="Сумма должна быть больше нуля")

    db_execute(
        "UPDATE users SET balance = balance + %s WHERE telegram_id = %s",
        (data.amount, target["telegram_id"]),
    )

    return {"status": "ok", "message": f"Выдано {money(data.amount)} BYN игроку {target['nickname']}"}


@app.post("/api/admin/company")
def add_company(data: AddCompanyRequest):
    if not is_admin(data.admin_id):
        raise HTTPException(status_code=403, detail="Только администраторы")

    db_execute(
        """
        INSERT INTO companies (category, name, price, daily_income, sqm)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (
            data.category,
            data.name,
            data.price,
            data.daily_income,
            data.sqm,
        ),
    )

    return {"status": "ok", "message": "Объект добавлен"}


def init_db():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(SCHEMA)

            cur.executemany(
                """
                INSERT INTO companies
                (category, name, price, daily_income, sqm)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
                """,
                DEFAULT_COMPANIES,
            )

            for name, base, minimum, maximum in DEFAULT_EXCHANGE:
                cur.execute(
                    """
                    INSERT INTO exchange_items
                    (name, base_price, min_price, max_price, current_price)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (name) DO NOTHING
                    """,
                    (name, base, minimum, maximum, base),
                )

        conn.commit()


@app.on_event("startup")
def startup():
    init_db()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.getenv("PORT", 8000)),
    )
