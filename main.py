import os
from contextlib import asynccontextmanager

import psycopg2
from psycopg2.extras import RealDictCursor
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

DATABASE_URL = os.getenv("DATABASE_URL")
BOT_TOKEN = os.getenv("BOT_TOKEN")
MAIN_ADMIN_ID = int(os.getenv("MAIN_ADMIN_ID", "5634302903"))
WEBAPP_URL = os.getenv("WEBAPP_URL", "")

LOAN_LIMIT = 1_000_000
LOAN_RATE = 0.10

if not DATABASE_URL or not BOT_TOKEN:
    raise RuntimeError("Заполни DATABASE_URL и BOT_TOKEN в переменных окружения.")

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

CREATE INDEX IF NOT EXISTS idx_users_bank
ON users(bank DESC);

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
    nickname = (nickname or "").strip()

    if not nickname:
        nickname = f"player{telegram_id}"

    existing = get_user_by_nickname(nickname)

    if existing and existing["telegram_id"] != telegram_id:
        nickname = f"player{telegram_id}"

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
            "UPDATE users SET is_admin = TRUE WHERE telegram_id = %s",
            (telegram_id,),
        )

    return get_user(telegram_id)


def is_admin(telegram_id):
    user = get_user(telegram_id)
    return bool(user and user["is_admin"])


def money(value):
    return f"{float(value):,.2f}".replace(",", " ")


PAGE = """<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NEON CITY</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
*{box-sizing:border-box}

body{
margin:0;
min-height:100vh;
font-family:Arial,sans-serif;
color:#e5e7eb;
background:
radial-gradient(circle at 15% 15%,#1e1b4b,transparent 55%),
radial-gradient(circle at 85% 10%,#312e81,transparent 50%),
#05060f;
padding-bottom:calc(20px + env(safe-area-inset-bottom));
}

.wrap{
max-width:1200px;
margin:0 auto;
padding:12px 8px 20px;
}

.title{
font-size:24px;
font-weight:900;
text-align:center;
color:#fff;
text-shadow:0 0 14px #7c3aed,0 0 28px #06b6d4;
margin-bottom:2px;
}

.subtitle{
text-align:center;
color:#94a3b8;
font-size:12px;
margin-bottom:12px;
}

.layout{
display:grid;
grid-template-columns:86px 1fr;
gap:8px;
align-items:start;
}

.sidebar{
background:rgba(15,23,42,.9);
border:1px solid rgba(124,58,237,.45);
border-radius:14px;
padding:8px 6px;
box-shadow:0 0 18px rgba(124,58,237,.18);
}

.menu{
display:flex;
flex-direction:column;
gap:6px;
}

.menu button{
margin:0;
padding:8px 3px;
font-size:9px;
border-radius:9px;
white-space:normal;
text-align:center;
line-height:1.15;
}

.content{
background:rgba(15,23,42,.9);
border:1px solid rgba(124,58,237,.45);
border-radius:14px;
padding:12px 10px;
box-shadow:0 0 18px rgba(124,58,237,.18);
min-height:70vh;
}

.card{
background:rgba(15,23,42,.85);
border:1px solid rgba(124,58,237,.45);
border-radius:14px;
padding:14px 10px;
margin-bottom:12px;
box-shadow:0 0 18px rgba(124,58,237,.18);
}

h2{
margin:0 0 10px;
color:#c4b5fd;
font-size:17px;
}

h3{
margin:14px 0 8px;
color:#67e8f9;
font-size:14px;
}

p{
margin:5px 0;
font-size:13px;
line-height:1.4;
}

input,textarea,button{
width:100%;
padding:10px;
border-radius:10px;
border:1px solid #334155;
background:#0f172a;
color:#fff;
font-size:14px;
margin-bottom:8px;
}

textarea{
min-height:70px;
resize:vertical;
}

button{
background:linear-gradient(90deg,#7c3aed,#06b6d4);
border:none;
font-weight:700;
cursor:pointer;
}

button:active{
opacity:.85;
}

.grid{
display:grid;
grid-template-columns:1fr;
gap:8px;
}

.result{
white-space:pre-wrap;
margin-top:10px;
color:#a5f3fc;
font-size:13px;
}

.hidden{display:none}

table{
width:100%;
border-collapse:collapse;
font-size:12px;
display:block;
overflow-x:auto;
}

th,td{
padding:7px;
border-bottom:1px solid #1e293b;
text-align:left;
white-space:nowrap;
}

th{color:#a78bfa}

.badge{
display:inline-block;
padding:3px 8px;
border-radius:999px;
background:#7c3aed;
color:#fff;
font-size:11px;
}

.company{
background:#0f172a;
border:1px solid #334155;
border-radius:12px;
padding:12px;
margin-bottom:10px;
}

label{
display:block;
font-size:12px;
color:#94a3b8;
margin-bottom:4px;
}

input[type="color"]{
height:44px;
padding:4px;
}

@media (min-width:700px){
.wrap{
padding:24px 20px 40px;
}

.title{
font-size:44px;
}

.subtitle{
font-size:15px;
margin-bottom:22px;
}

.layout{
grid-template-columns:230px 1fr;
gap:18px;
}

.sidebar{
padding:14px;
border-radius:18px;
}

.menu{
gap:8px;
}

.menu button{
padding:10px;
font-size:13px;
border-radius:11px;
text-align:left;
}

.content{
padding:22px;
border-radius:18px;
min-height:520px;
}

.card{
padding:20px;
border-radius:16px;
}

h2{
font-size:22px;
}

p{
font-size:15px;
}

input,textarea,button{
padding:13px;
font-size:15px;
border-radius:12px;
}

.grid{
grid-template-columns:repeat(auto-fit,minmax(220px,1fr));
}

table{
font-size:14px;
}
}
</style>
</head>
<body>
<div class="wrap">
<div class="title">NEON CITY</div>
<div class="subtitle">Игровая экономика, бизнес и биржа</div>

<div id="auth" class="card">
<h2>Вход</h2>
<button onclick="login()">Войти через Telegram</button>
<div id="auth_result" class="result"></div>
</div>

<div id="game" class="hidden">
<div class="layout">

<div class="sidebar">
<div class="menu">
<button onclick="show('profile')">👤 Профиль</button>
<button onclick="show('bank')">🏦 Банк</button>
<button onclick="show('exchange')">📈 Биржа</button>
<button onclick="show('companies')">🏢 Бизнес</button>
<button onclick="show('properties')">🏠 Моя недвижимость</button>
<button onclick="show('transfer')">💸 Перевод</button>
<button onclick="show('players')">👥 Игроки</button>
<button onclick="show('all_chats')">💬 Все чаты</button>
<button onclick="show('friends')">🤝 Друзья</button>
<button onclick="show('settings')">⚙️ Карта</button>
<button id="admin_button" class="hidden" onclick="show('admin')">🛡 Админка</button>
</div>
</div>

<div class="content">

<div id="profile" class="card">
<h2>Профиль</h2>
<div id="profile_info"></div>
</div>

<div id="bank" class="card hidden">
<h2>NEON BANK</h2>

<div id="bank_info"></div>

<h3>Пополнить карту</h3>
<input id="bank_amount" placeholder="Сумма пополнения">
<button onclick="bank('deposit')">📥 Пополнить карту</button>
<div id="bank_result" class="result"></div>

<h3>Кредит</h3>
<div id="bank_loan_info"></div>
<input id="bank_loan_amount" placeholder="Сумма кредита">
<button onclick="takeLoanFromBank()">💳 Оформить кредит</button>
<div id="bank_loan_result" class="result"></div>
</div>

<div id="exchange" class="card hidden">
<h2>Биржа</h2>
<button onclick="loadExchange()">Обновить цены</button>
<div id="exchange_info"></div>
<input id="exchange_item" placeholder="Название актива">
<input id="exchange_quantity" placeholder="Количество" value="1">
<div class="grid">
<button onclick="trade('buy')">🛒 Купить</button>
<button onclick="trade('sell')">📤 Продать</button>
</div>
<div id="exchange_result" class="result"></div>
</div>

<div id="companies" class="card hidden">
<h2>Бизнес и недвижимость</h2>
<button onclick="loadCompanies()">Показать объекты</button>
<div id="companies_info" class="result"></div>
</div>

<div id="properties" class="card hidden">
<h2>🏠 Моя недвижимость</h2>
<button onclick="loadProperties()">Обновить</button>
<div id="properties_info" class="result"></div>
</div>

<div id="transfer" class="card hidden">
<h2>Перевод игроку</h2>
<input id="receiver_nick" placeholder="Никнейм получателя">
<input id="transfer_amount" placeholder="Сумма">
<button onclick="transfer()">💸 Перевести</button>
<div id="transfer_result" class="result"></div>
</div>

<div id="players" class="card hidden">
<h2>Игроки</h2>
<button onclick="loadPlayers()">Обновить список</button>
<div id="players_info"></div>
</div>

<div id="all_chats" class="card hidden">
<h2>💬 Все чаты</h2>
<button onclick="loadAllChats()">Обновить</button>
<div id="all_chats_info" class="result"></div>

<h3>Написать сообщение</h3>
<input id="message_nick" placeholder="Никнейм получателя">
<textarea id="message_text" placeholder="Текст сообщения"></textarea>
<button onclick="sendMessage()">📩 Отправить</button>
<div id="messages_info" class="result"></div>
</div>

<div id="friends" class="card hidden">
<h2>Друзья</h2>
<input id="friend_nick" placeholder="Никнейм друга">
<button onclick="addFriend()">➕ Добавить друга</button>
<button onclick="loadFriends()">👥 Показать друзей</button>
<div id="friends_info" class="result"></div>
</div>

<div id="settings" class="card hidden">
<h2>Настройки карты</h2>

<label for="card_color">Цвет карты</label>
<input id="card_color" type="color" value="#7c3aed">

<label for="card_background">Фон карты</label>
<input id="card_background" type="color" value="#111827">

<input id="card_image" placeholder="Ссылка на изображение карты">
<button onclick="saveCard()">💾 Сохранить</button>
<div id="card_result" class="result"></div>
</div>

<div id="admin" class="card hidden">
<h2>Админ-панель</h2>
<input id="admin_nick" placeholder="Никнейм игрока">
<div class="grid">
<button onclick="makeAdmin()">🛡 Назначить админом</button>
<button onclick="removeAdmin()">❌ Снять админа</button>
</div>
<input id="give_amount" placeholder="Сумма для выдачи">
<button onclick="giveMoney()">💰 Выдать деньги</button>
<input id="company_category" placeholder="Категория бизнеса">
<input id="company_name" placeholder="Название бизнеса">
<input id="company_price" placeholder="Цена">
<input id="company_income" placeholder="Доход в день">
<input id="company_sqm" placeholder="Площадь в км²">
<button onclick="addCompany()">🏢 Добавить бизнес</button>
<div id="admin_result" class="result"></div>
</div>

</div>

</div>
</div>
</div>

<script>
let currentId = null;

async function api(url, data) {
  const response = await fetch(url, {
    method: data ? 'POST' : 'GET',
    headers: {'Content-Type': 'application/json'},
    body: data ? JSON.stringify(data) : undefined
  });

  const text = await response.text();
  let result;

  try {
    result = JSON.parse(text);
  } catch (error) {
    throw new Error('Сервер вернул HTML вместо JSON');
  }

  if (!response.ok) {
    throw new Error(result.detail || 'Ошибка');
  }

  return result;
}

function show(section) {
  document.querySelectorAll('.content .card').forEach(card => card.classList.add('hidden'));
  document.getElementById(section).classList.remove('hidden');

  if (section === 'profile') loadProfile();
  if (section === 'bank') loadBank();
  if (section === 'exchange') loadExchange();
  if (section === 'companies') loadCompanies();
  if (section === 'properties') loadProperties();
  if (section === 'players') loadPlayers();
  if (section === 'all_chats') loadAllChats();
  if (section === 'friends') loadFriends();
}

async function login() {
  const tg = window.Telegram && window.Telegram.WebApp;

  if (!tg || !tg.initDataUnsafe || !tg.initDataUnsafe.user) {
    document.getElementById('auth_result').textContent =
      'Открой сайт через кнопку в Telegram-боте.';
    return;
  }

  const user = tg.initDataUnsafe.user;
  const telegram_id = user.id;
  const first_name = user.first_name || 'Игрок';
  const nickname = user.username || ('player' + telegram_id);

  try {
    const data = await api('/api/login', {
      telegram_id,
      nickname,
      first_name
    });

    currentId = data.telegram_id;
    document.getElementById('auth').classList.add('hidden');
    document.getElementById('game').classList.remove('hidden');

    if (data.is_admin) {
      document.getElementById('admin_button').classList.remove('hidden');
    }

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
    '<p><b>Баланс на карте:</b> ' + user.bank + ' BYN</p>' +
    '<p><b>Кредит:</b> ' + user.credit + ' BYN</p>' +
    '<p><b>Земля:</b> ' + user.sqm + ' км²</p>' +
    '<p><span class="badge">' + (user.is_admin ? 'Администратор' : 'Игрок') + '</span></p>';
}

async function loadBank() {
  const user = await api('/api/profile?telegram_id=' + currentId);

  document.getElementById('bank_info').innerHTML =
    '<p><b>Баланс на карте:</b> ' + user.bank + ' BYN</p>' +
    '<p><b>Кредитный долг:</b> ' + user.credit + ' BYN</p>';

  document.getElementById('bank_loan_info').innerHTML =
    '<p><b>Лимит кредита:</b> 1 000 000 BYN</p>' +
    '<p><b>Ставка:</b> 10%</p>' +
    '<p><b>Текущий долг:</b> ' + user.credit + ' BYN</p>';
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

async function takeLoanFromBank() {
  try {
    const data = await api('/api/loan', {
      telegram_id: currentId,
      amount: Number(document.getElementById('bank_loan_amount').value)
    });

    document.getElementById('bank_loan_result').textContent = data.message;
    loadBank();
  } catch (error) {
    document.getElementById('bank_loan_result').textContent = error.message;
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
  let html = '';

  companies.forEach(company => {
    html += '<div class="company">';
    html += '<p><b>' + company.name + '</b></p>';
    html += '<p>Категория: ' + company.category + '</p>';
    html += '<p>Цена: ' + company.price + ' BYN</p>';
    html += '<p>Доход: ' + company.daily_income + ' BYN/день</p>';
    html += '<p>Площадь: ' + company.sqm + ' км²</p>';
    html += '<p><span class="badge">' + (company.owned ? 'Куплено' : 'Доступно') + '</span></p>';

    if (!company.owned) {
      html += '<button onclick="buyCompany(' + company.id + ')">🛒 Купить</button>';
    }

    html += '</div>';
  });

  document.getElementById('companies_info').innerHTML = html || 'Объектов пока нет';
}

async function buyCompany(companyId) {
  try {
    const data = await api('/api/companies/buy', {
      telegram_id: currentId,
      company_id: companyId
    });

    alert(data.message);
    loadCompanies();
  } catch (error) {
    alert(error.message);
  }
}

async function loadProperties() {
  const properties = await api('/api/properties?telegram_id=' + currentId);
  let html = '';

  properties.forEach(property => {
    html += '<div class="company">';
    html += '<p><b>' + property.name + '</b></p>';
    html += '<p>Категория: ' + property.category + '</p>';
    html += '<p>Доход: ' + property.daily_income + ' BYN/день</p>';
    html += '<p>Площадь: ' + property.sqm + ' км²</p>';
    html += '<p>Куплено: ' + property.purchased_at + '</p>';
    html += '</div>';
  });

  document.getElementById('properties_info').innerHTML =
    html || 'У тебя пока нет недвижимости. Купи её в разделе «Бизнес».';
}

async function transfer() {
  try {
    const data = await api('/api/transfer', {
      sender_id: currentId,
      receiver_nickname: document.getElementById('receiver_nick').value,
      amount: Number(document.getElementById('transfer_amount').value)
    });

    document.getElementById('transfer_result').textContent = data.message;
  } catch (error) {
    document.getElementById('transfer_result').textContent = error.message;
  }
}

async function loadPlayers() {
  const players = await api('/api/players');
  let html = '<table><tr><th>Ник</th><th>Карта</th><th>Статус</th></tr>';

  players.forEach(player => {
    html += '<tr><td>' + player.nickname + '</td><td>' + player.bank + ' BYN</td><td>' + (player.is_admin ? 'Админ' : 'Игрок') + '</td></tr>';
  });

  document.getElementById('players_info').innerHTML = html + '</table>';
}

async function loadAllChats() {
  const messages = await api('/api/all-chats?telegram_id=' + currentId);
  let html = '';

  messages.forEach(message => {
    const isMine = message.sender_id === currentId;

    html += '<div class="company">';
    html += '<p><b>' + (isMine ? 'Ты' : message.sender_name) + ' → ' + message.receiver_name + '</b></p>';
    html += '<p>' + message.text + '</p>';
    html += '<p><span class="badge">' + message.created_at + '</span></p>';
    html += '</div>';
  });

  document.getElementById('all_chats_info').innerHTML =
    html || 'Сообщений пока нет';
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
  await adminAction('/api/admin/add');
}

async function removeAdmin() {
  await adminAction('/api/admin/remove');
}

async function adminAction(url) {
  try {
    const data = await api(url, {
      admin_id: currentId,
      target_nickname: document.getElementById('admin_nick').value
    });

    document.getElementById('admin_result').textContent = data.message;
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

if (window.Telegram && window.Telegram.WebApp) {
  window.Telegram.WebApp.ready();
  window.Telegram.WebApp.expand();
}
</script>
</body>
</html>"""


def main_keyboard(telegram_id):
    if WEBAPP_URL:
        site_button = [
            InlineKeyboardButton(
                "🌐 Открыть NEON CITY",
                web_app=WebAppInfo(url=WEBAPP_URL),
            )
        ]
    else:
        site_button = [
            InlineKeyboardButton(
                "🌐 Сайт недоступен",
                callback_data="no_site",
            )
        ]

    buttons = [
        site_button,
        [InlineKeyboardButton("👤 Профиль", callback_data="profile")],
        [InlineKeyboardButton("🏦 Банк", callback_data="bank")],
        [InlineKeyboardButton("📈 Биржа", callback_data="exchange")],
        [InlineKeyboardButton("🏢 Бизнес", callback_data="companies")],
        [InlineKeyboardButton("🏠 Недвижимость", callback_data="properties")],
        [InlineKeyboardButton("💸 Перевод", callback_data="transfer")],
        [InlineKeyboardButton("👥 Игроки", callback_data="players")],
        [InlineKeyboardButton("💬 Все чаты", callback_data="all_chats")],
        [InlineKeyboardButton("🤝 Друзья", callback_data="friends")],
    ]

    if is_admin(telegram_id):
        buttons.append(
            [InlineKeyboardButton("🛡 Админ-панель", callback_data="admin")]
        )

    return InlineKeyboardMarkup(buttons)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    nickname = update.effective_user.username or f"player{telegram_id}"
    first_name = update.effective_user.first_name or "Игрок"

    user = ensure_user(telegram_id, nickname, first_name)

    text = (
        f"🌆 <b>NEON CITY</b>\n\n"
        f"Привет, <b>{user['nickname']}</b>!\n\n"
        f"💳 Баланс на карте: <b>{money(user['bank'])} BYN</b>\n"
        f"🌍 Земля: <b>{user['sqm']} км²</b>"
    )

    await update.message.reply_text(
        text,
        reply_markup=main_keyboard(telegram_id),
        parse_mode="HTML",
    )


async def profile_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = get_user(query.from_user.id)

    if not user:
        await query.edit_message_text("Сначала нажми /start.")
        return

    text = (
        f"👤 <b>Профиль</b>\n\n"
        f"Ник: <b>{user['nickname']}</b>\n"
        f"Telegram ID: <code>{user['telegram_id']}</code>\n\n"
        f"💳 Баланс на карте: <b>{money(user['bank'])} BYN</b>\n"
        f"💳 Кредит: <b>{money(user['credit'])} BYN</b>\n"
        f"🌍 Земля: <b>{user['sqm']} км²</b>"
    )

    await query.edit_message_text(
        text,
        reply_markup=main_keyboard(user["telegram_id"]),
        parse_mode="HTML",
    )


async def bank_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = get_user(query.from_user.id)

    if not user:
        await query.edit_message_text("Сначала нажми /start.")
        return

    await query.edit_message_text(
        f"🏦 <b>NEON BANK</b>\n\n"
        f"💳 Баланс на карте: <b>{money(user['bank'])} BYN</b>\n"
        f"💳 Кредитный долг: <b>{money(user['credit'])} BYN</b>\n\n"
        f"Команды:\n"
        f"<code>/deposit СУММА</code> — пополнить карту\n"
        f"<code>/loan СУММА</code> — оформить кредит",
        reply_markup=main_keyboard(user["telegram_id"]),
        parse_mode="HTML",
    )


async def deposit_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Формат: <code>/deposit СУММА</code>",
            parse_mode="HTML",
        )
        return

    try:
        amount = float(context.args[0].replace(",", "."))
    except ValueError:
        await update.message.reply_text("Сумма должна быть числом.")
        return

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT bank FROM users WHERE telegram_id = %s FOR UPDATE",
                (update.effective_user.id,),
            )
            user = cur.fetchone()

            if not user:
                await update.message.reply_text("Сначала нажми /start.")
                return

            cur.execute(
                """
                UPDATE users
                SET bank = bank + %s
                WHERE telegram_id = %s
                """,
                (amount, update.effective_user.id),
            )

        conn.commit()

    await update.message.reply_text(f"✅ Карта пополнена: {money(amount)} BYN")


async def exchange_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    items = db_execute(
        "SELECT * FROM exchange_items ORDER BY base_price ASC",
        fetch=True,
    )

    text = "📈 <b>NEON EXCHANGE</b>\n\n"

    for item in items:
        text += (
            f"<b>{item['name']}</b>\n"
            f"Цена: {money(item['current_price'])} BYN\n\n"
        )

    await query.edit_message_text(
        text,
        reply_markup=main_keyboard(query.from_user.id),
        parse_mode="HTML",
    )


async def companies_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    companies = db_execute(
        """
        SELECT c.*,
               EXISTS (
                   SELECT 1 FROM user_companies uc
                   WHERE uc.user_id = %s AND uc.company_id = c.id
               ) AS owned
        FROM companies c
        ORDER BY c.price ASC
        """,
        (query.from_user.id,),
        fetch=True,
    )

    text = "🏢 <b>Бизнес и недвижимость</b>\n\n"

    for company in companies:
        status = "✅ Куплено" if company["owned"] else "🛒 Доступно"
        text += (
            f"{status} <b>{company['name']}</b>\n"
            f"Цена: {money(company['price'])} BYN\n"
            f"Доход: {money(company['daily_income'])} BYN/день\n\n"
        )

    await query.edit_message_text(
        text,
        reply_markup=main_keyboard(query.from_user.id),
        parse_mode="HTML",
    )


async def transfer_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    await query.edit_message_text(
        "💸 <b>Перевод игроку</b>\n\n"
        "Команда:\n"
        "<code>/transfer НИК СУММА</code>\n\n"
        "Пример:\n"
        "<code>/transfer Owner 1000</code>",
        reply_markup=main_keyboard(query.from_user.id),
        parse_mode="HTML",
    )


async def transfer_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 2:
        await update.message.reply_text(
            "Формат: <code>/transfer НИК СУММА</code>",
            parse_mode="HTML",
        )
        return

    receiver = get_user_by_nickname(context.args[0])

    if not receiver:
        await update.message.reply_text("Игрок с таким ником не найден.")
        return

    try:
        amount = float(context.args[1].replace(",", "."))
    except ValueError:
        await update.message.reply_text("Сумма должна быть числом.")
        return

    sender_id = update.effective_user.id

    if sender_id == receiver["telegram_id"]:
        await update.message.reply_text("Нельзя перевести самому себе.")
        return

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT bank FROM users WHERE telegram_id = %s FOR UPDATE",
                (sender_id,),
            )
            sender = cur.fetchone()

            if not sender or float(sender["bank"]) < amount:
                await update.message.reply_text("Недостаточно денег на карте.")
                return

            cur.execute(
                "UPDATE users SET bank = bank - %s WHERE telegram_id = %s",
                (amount, sender_id),
            )
            cur.execute(
                "UPDATE users SET bank = bank + %s WHERE telegram_id = %s",
                (amount, receiver["telegram_id"]),
            )
            cur.execute(
                """
                INSERT INTO transfers (sender_id, receiver_id, amount)
                VALUES (%s, %s, %s)
                """,
                (sender_id, receiver["telegram_id"], amount),
            )

        conn.commit()

    await update.message.reply_text(
        f"✅ Переведено {money(amount)} BYN игроку {receiver['nickname']}."
    )


async def players_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    players = db_execute(
        """
        SELECT nickname, bank, is_admin
        FROM users
        ORDER BY bank DESC
        LIMIT 20
        """,
        fetch=True,
    )

    text = "👥 <b>Игроки NEON CITY</b>\n\n"

    for player in players:
        status = "🛡 Админ" if player["is_admin"] else "Игрок"
        text += (
            f"<b>{player['nickname']}</b> — "
            f"{money(player['bank'])} BYN — {status}\n"
        )

    await query.edit_message_text(
        text,
        reply_markup=main_keyboard(query.from_user.id),
        parse_mode="HTML",
    )


async def all_chats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    messages = db_execute(
        """
        SELECT
            m.*,
            s.nickname AS sender_name,
            r.nickname AS receiver_name
        FROM messages m
        JOIN users s ON s.telegram_id = m.sender_id
        JOIN users r ON r.telegram_id = m.receiver_id
        WHERE m.sender_id = %s OR m.receiver_id = %s
        ORDER BY m.created_at DESC
        LIMIT 20
        """,
        (query.from_user.id, query.from_user.id),
        fetch=True,
    )

    text = "💬 <b>Все чаты</b>\n\n"

    if not messages:
        text += "Сообщений нет."
    else:
        for message in messages:
            is_mine = message["sender_id"] == query.from_user.id
            sender = "Ты" if is_mine else message["sender_name"]

            text += (
                f"<b>{sender} → {message['receiver_name']}</b>\n"
                f"{message['text']}\n\n"
            )

    await query.edit_message_text(
        text,
        reply_markup=main_keyboard(query.from_user.id),
        parse_mode="HTML",
    )


async def message_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text(
            "Формат: <code>/message НИК ТЕКСТ</code>",
            parse_mode="HTML",
        )
        return

    receiver = get_user_by_nickname(context.args[0])

    if not receiver:
        await update.message.reply_text("Игрок с таким ником не найден.")
        return

    text = " ".join(context.args[1:])

    db_execute(
        """
        INSERT INTO messages (sender_id, receiver_id, text)
        VALUES (%s, %s, %s)
        """,
        (update.effective_user.id, receiver["telegram_id"], text),
    )

    await update.message.reply_text(
        f"✅ Сообщение отправлено игроку {receiver['nickname']}."
    )


async def loan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Формат: <code>/loan СУММА</code>",
            parse_mode="HTML",
        )
        return

    try:
        amount = float(context.args[0].replace(",", "."))
    except ValueError:
        await update.message.reply_text("Сумма должна быть числом.")
        return

    if amount <= 0 or amount > LOAN_LIMIT:
        await update.message.reply_text(
            f"Кредит должен быть от 1 до {money(LOAN_LIMIT)} BYN."
        )
        return

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT credit FROM users WHERE telegram_id = %s FOR UPDATE",
                (update.effective_user.id,),
            )
            user = cur.fetchone()

            if not user:
                await update.message.reply_text("Сначала нажми /start.")
                return

            if float(user["credit"]) + amount > LOAN_LIMIT:
                await update.message.reply_text("Превышен кредитный лимит.")
                return

            total = amount * (1 + LOAN_RATE)

            cur.execute(
                """
                UPDATE users
                SET bank = bank + %s, credit = credit + %s
                WHERE telegram_id = %s
                """,
                (amount, total, update.effective_user.id),
            )
            cur.execute(
                """
                INSERT INTO loans (user_id, amount, status)
                VALUES (%s, %s, 'approved')
                """,
                (update.effective_user.id, amount),
            )

        conn.commit()

    await update.message.reply_text(
        f"✅ Кредит выдан: {money(amount)} BYN.\nК возврату: {money(total)} BYN."
    )


async def friends_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    friends = db_execute(
        """
        SELECT u.nickname
        FROM friends f
        JOIN users u ON u.telegram_id = f.friend_id
        WHERE f.owner_id = %s
        ORDER BY u.nickname
        """,
        (query.from_user.id,),
        fetch=True,
    )

    text = "🤝 <b>Друзья</b>\n\n"

    if not friends:
        text += "Друзей нет.\n\nДобавить: <code>/friend НИК</code>"
    else:
        for friend in friends:
            text += f"<b>{friend['nickname']}</b>\n"

    await query.edit_message_text(
        text,
        reply_markup=main_keyboard(query.from_user.id),
        parse_mode="HTML",
    )


async def friend_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Формат: <code>/friend НИК</code>",
            parse_mode="HTML",
        )
        return

    friend = get_user_by_nickname(context.args[0])

    if not friend:
        await update.message.reply_text("Игрок с таким ником не найден.")
        return

    if update.effective_user.id == friend["telegram_id"]:
        await update.message.reply_text("Нельзя добавить себя.")
        return

    db_execute(
        """
        INSERT INTO friends (owner_id, friend_id)
        VALUES (%s, %s)
        ON CONFLICT DO NOTHING
        """,
        (update.effective_user.id, friend["telegram_id"]),
    )

    await update.message.reply_text(
        f"✅ {friend['nickname']} добавлен в друзья."
    )


async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not is_admin(query.from_user.id):
        await query.edit_message_text("Доступ только у администраторов.")
        return

    await query.edit_message_text(
        "🛡 <b>Админ-панель</b>\n\n"
        "<code>/admin НИК</code> — назначить админа\n"
        "<code>/unadmin НИК</code> — снять админа\n"
        "<code>/give НИК СУММА</code> — выдать деньги\n"
        "<code>/addcompany Категория|Название|Цена|Доход|Площадь</code>",
        reply_markup=main_keyboard(query.from_user.id),
        parse_mode="HTML",
    )


async def add_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    if not context.args:
        await update.message.reply_text(
            "Формат: <code>/admin НИК</code>",
            parse_mode="HTML",
        )
        return

    target = get_user_by_nickname(context.args[0])

    if not target:
        await update.message.reply_text("Игрок не найден.")
        return

    db_execute(
        "UPDATE users SET is_admin = TRUE WHERE telegram_id = %s",
        (target["telegram_id"],),
    )

    await update.message.reply_text(
        f"✅ {target['nickname']} назначен администратором."
    )


async def remove_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    if not context.args:
        await update.message.reply_text(
            "Формат: <code>/unadmin НИК</code>",
            parse_mode="HTML",
        )
        return

    target = get_user_by_nickname(context.args[0])

    if not target:
        await update.message.reply_text("Игрок не найден.")
        return

    if target["telegram_id"] == MAIN_ADMIN_ID:
        await update.message.reply_text("Главного администратора нельзя снять.")
        return

    db_execute(
        "UPDATE users SET is_admin = FALSE WHERE telegram_id = %s",
        (target["telegram_id"],),
    )

    await update.message.reply_text(
        f"✅ {target['nickname']} снят с должности."
    )


async def give_money_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    if len(context.args) != 2:
        await update.message.reply_text(
            "Формат: <code>/give НИК СУММА</code>",
            parse_mode="HTML",
        )
        return

    target = get_user_by_nickname(context.args[0])

    if not target:
        await update.message.reply_text("Игрок не найден.")
        return

    try:
        amount = float(context.args[1].replace(",", "."))
    except ValueError:
        await update.message.reply_text("Сумма должна быть числом.")
        return

    db_execute(
        "UPDATE users SET bank = bank + %s WHERE telegram_id = %s",
        (amount, target["telegram_id"]),
    )

    await update.message.reply_text(
        f"✅ Выдано {money(amount)} BYN игроку {target['nickname']}."
    )


async def add_company_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    if len(context.args) != 1:
        await update.message.reply_text(
            "Формат:\n"
            "<code>/addcompany Категория|Название|Цена|Доход|Площадь</code>",
            parse_mode="HTML",
        )
        return

    try:
        category, name, price, income, sqm = context.args[0].split("|")

        db_execute(
            """
            INSERT INTO companies (category, name, price, daily_income, sqm)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                category.strip(),
                name.strip(),
                float(price.replace(",", ".")),
                float(income.replace(",", ".")),
                int(sqm),
            ),
        )
    except Exception:
        await update.message.reply_text("Проверь формат команды.")
        return

    await update.message.reply_text("✅ Объект добавлен.")


async def no_site_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer(
        "Добавь WEBAPP_URL в секреты Netrun.",
        show_alert=True,
    )


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
    receiver_nickname: str
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
    return PAGE


@app.get("/health")
def health():
    try:
        db_execute("SELECT 1", fetch=True)
        return {"status": "ok", "database": "connected"}
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error))


@app.post("/api/login")
def login(data: LoginRequest):
    return ensure_user(
        data.telegram_id,
        data.nickname,
        data.first_name,
    )


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
        SELECT nickname, bank, sqm
        FROM users
        ORDER BY bank DESC, sqm DESC
        LIMIT 50
        """,
        fetch=True,
    )


@app.post("/api/bank")
def bank(data: BankRequest):
    if data.amount <= 0:
        raise HTTPException(status_code=400, detail="Сумма должна быть больше нуля")

    if data.action != "deposit":
        raise HTTPException(status_code=400, detail="Снятие денег отключено")

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT bank FROM users WHERE telegram_id = %s FOR UPDATE",
                (data.telegram_id,),
            )
            user = cur.fetchone()

            if not user:
                raise HTTPException(status_code=404, detail="Игрок не найден")

            cur.execute(
                """
                UPDATE users
                SET bank = bank + %s
                WHERE telegram_id = %s
                """,
                (data.amount, data.telegram_id),
            )

        conn.commit()

    return {
        "status": "ok",
        "message": f"Карта пополнена: {money(data.amount)} BYN",
    }


@app.post("/api/transfer")
def transfer(data: TransferRequest):
    receiver = get_user_by_nickname(data.receiver_nickname)

    if not receiver:
        raise HTTPException(status_code=404, detail="Игрок с таким ником не найден")

    if data.sender_id == receiver["telegram_id"]:
        raise HTTPException(status_code=400, detail="Нельзя перевести самому себе")

    if data.amount <= 0:
        raise HTTPException(status_code=400, detail="Сумма должна быть больше нуля")

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT bank FROM users WHERE telegram_id = %s FOR UPDATE",
                (data.sender_id,),
            )
            sender = cur.fetchone()

            if not sender or float(sender["bank"]) < data.amount:
                raise HTTPException(status_code=400, detail="Недостаточно денег на карте")

            cur.execute(
                "UPDATE users SET bank = bank - %s WHERE telegram_id = %s",
                (data.amount, data.sender_id),
            )
            cur.execute(
                "UPDATE users SET bank = bank + %s WHERE telegram_id = %s",
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
                SET bank = bank + %s, credit = credit + %s
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
                "SELECT bank FROM users WHERE telegram_id = %s FOR UPDATE",
                (data.telegram_id,),
            )
            user = cur.fetchone()

            if not user or float(user["bank"]) < float(company["price"]):
                raise HTTPException(status_code=400, detail="Недостаточно денег на карте")

            cur.execute(
                """
                UPDATE users
                SET bank = bank - %s, sqm = sqm + %s
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


@app.get("/api/properties")
def properties(telegram_id: int):
    return db_execute(
        """
        SELECT c.name, c.category, c.daily_income, c.sqm, uc.purchased_at
        FROM user_companies uc
        JOIN companies c ON c.id = uc.company_id
        WHERE uc.user_id = %s
        ORDER BY uc.purchased_at DESC
        """,
        (telegram_id,),
        fetch=True,
    )


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
                "SELECT bank FROM users WHERE telegram_id = %s FOR UPDATE",
                (data.telegram_id,),
            )
            user = cur.fetchone()

            if not user:
                raise HTTPException(status_code=404, detail="Игрок не найден")

            if data.action == "buy":
                if float(user["bank"]) < price:
                    raise HTTPException(status_code=400, detail="Недостаточно денег на карте")

                cur.execute(
                    "UPDATE users SET bank = bank - %s WHERE telegram_id = %s",
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
                    "UPDATE users SET bank = bank + %s WHERE telegram_id = %s",
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
        SELECT telegram_id, nickname, bank, is_admin
        FROM users
        ORDER BY bank DESC
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

    return {
        "status": "ok",
        "message": f"Сообщение отправлено игроку {receiver['nickname']}",
    }


@app.get("/api/all-chats")
def all_chats(telegram_id: int):
    return db_execute(
        """
        SELECT
            m.*,
            s.nickname AS sender_name,
            r.nickname AS receiver_name
        FROM messages m
        JOIN users s ON s.telegram_id = m.sender_id
        JOIN users r ON r.telegram_id = m.receiver_id
        WHERE m.sender_id = %s OR m.receiver_id = %s
        ORDER BY m.created_at DESC
        LIMIT 100
        """,
        (telegram_id, telegram_id),
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

    if data.amount
