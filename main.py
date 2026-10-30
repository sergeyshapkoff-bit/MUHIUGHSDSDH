import json
import os

# Константы
CLAN_COST = 500000
SAVE_FILE = "game_data.json"

# --- КЛАССЫ ДАННЫХ ---

class Player:
    def __init__(self, name, balance=0, clan_name=None):
        self.name = name
        self.balance = balance
        self.clan_name = clan_name

    def to_dict(self):
        return {"name": self.name, "balance": self.balance, "clan_name": self.clan_name}

    @classmethod
    def from_dict(cls, data):
        return cls(data["name"], data["balance"], data["clan_name"])

class Clan:
    def __init__(self, name, leader, is_private, members=None, treasury=0):
        self.name = name
        self.leader = leader
        self.is_private = is_private
        self.members = members if members else [leader]
        self.treasury = treasury

    def to_dict(self):
        return {
            "name": self.name,
            "leader": self.leader,
            "is_private": self.is_private,
            "members": self.members,
            "treasury": self.treasury
        }

    @classmethod
    def from_dict(cls, data):
        return cls(data["name"], data["leader"], data["is_private"], data["members"], data["treasury"])

    def get_card(self):
        privacy = "🔒 Приватный (Private)" if self.is_private else "🌐 Открытый (Public)"
        members_str = ", ".join(self.members)
        return (
            f"\n========== КАРТА КЛАНА ==========\n"
            f"🏰 Название: {self.name}\n"
            f"👑 Лидер: {self.leader}\n"
            f"🔐 Статус: {privacy}\n"
            f"👥 Участники ({len(self.members)}): {members_str}\n"
            f"💰 Казна клана: {self.treasury} монет\n"
            f"================================="
        )

# --- ОСНОВНАЯ ЛОГИКА ИГРЫ ---

class Game:
    def __init__(self):
        self.players = {}
        self.clans = {}
        self.current_player = None
        self.load_data()

    # Загрузка и сохранение
    def load_data(self):
        if os.path.exists(SAVE_FILE):
            with open(SAVE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                for p_data in data.get("players", {}).values():
                    player = Player.from_dict(p_data)
                    self.players[player.name] = player
                for c_data in data.get("clans", {}).values():
                    clan = Clan.from_dict(c_data)
                    self.clans[clan.name] = clan
        else:
            # Создаем тестового игрока, если база пуста
            self.players["admin"] = Player("admin", balance=1000000) # 1 млн для тестов
            self.save_data()

    def save_data(self):
        data = {
            "players": {p.name: p.to_dict() for p in self.players.values()},
            "clans": {c.name: c.to_dict() for c in self.clans.values()}
        }
        with open(SAVE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

    # Авторизация (для простоты)
    def login(self):
        print("\n--- ВХОД В ИГРУ ---")
        name = input("Введите ваше имя (для теста: admin): ").strip()
        if name in self.players:
            self.current_player = self.players[name]
            print(f"✅ Добро пожаловать, {self.current_player.name}!")
        else:
            print("❌ Игрок не найден. Создаем нового игрока с 0 монет.")
            self.current_player = Player(name, balance=0)
            self.players[name] = self.current_player
            self.save_data()

    # Вкладка "Кланы"
    def show_clans_tab(self):
        print("\n--- 👥 ВКЛАДКА КЛАНЫ ---")
        if not self.clans:
            print("Пока не создано ни одного клана.")
            return

        print(f"{'Название':<15} | {'Лидер':<10} | {'Тип':<10} | {'Участники'}")
        print("-" * 55)
        for clan in self.clans.values():
            privacy = "🔒 Private" if clan.is_private else "🌐 Public"
            print(f"{clan.name:<15} | {clan.leader:<10} | {privacy:<10} | {len(clan.members)}")
        
        # Просмотр карты
        choice = input("\nВведите название клана для просмотра карты (или Enter, чтобы выйти): ").strip()
        if choice:
            if choice in self.clans:
                print(self.clans[choice].get_card())
            else:
                print("❌ Клан не найден.")

    # Создание клана
    def create_clan(self):
        print("\n--- 🏰 СОЗДАНИЕ КЛАНА ---")
        
        if self.current_player.clan_name:
            print(f"❌ Вы уже состоите в клане '{self.current_player.clan_name}'. Выйдите из него, чтобы создать новый.")
            return

        if self.current_player.balance < CLAN_COST:
            print(f"❌ Недостаточно средств! Нужно {CLAN_COST} монет. У вас: {self.current_player.balance}.")
            return

        clan_name = input("Введите название нового клана: ").strip()
        if not clan_name:
            print("❌ Название не может быть пустым.")
            return
        if clan_name in self.clans:
            print("❌ Клан с таким названием уже существует.")
            return

        print("Выберите приватность клана:")
        print("1. 🌐 Public (Открытый - любой может вступить)")
        print("2. 🔒 Private (Приватный - только по приглашению)")
        privacy_choice = input("Ваш выбор (1/2): ").strip()

        is_private = True if privacy_choice == "2" else False

        # Списание средств и создание
        self.current_player.balance -= CLAN_COST
        self.current_player.clan_name = clan_name
        
        new_clan = Clan(name=clan_name, leader=self.current_player.name, is_private=is_private)
        self.clans[clan_name] = new_clan
        
        self.save_data()
        print(f"\n✅ Клан '{clan_name}' успешно создан! Списано {CLAN_COST} монет.")
        print(f"Остаток на балансе: {self.current_player.balance}")

    # Главное меню
    def run(self):
        self.login()
        
        while True:
            print("\n================ ГЛАВНОЕ МЕНЮ ================")
            print(f"👤 Игрок: {self.current_player.name} | 💰 Баланс: {self.current_player.balance} | 🏰 Клан: {self.current_player.clan_name or 'Нет'}")
            print("1. 👥 Вкладка 'Кланы'")
            print("2. 🏰 Создать клан (500,000 монет)")
            print("3. 🚪 Выход")
            
            choice = input("Выберите действие: ").strip()
            
            if choice == "1":
                self.show_clans_tab()
            elif choice == "2":
                self.create_clan()
            elif choice == "3":
                print("Сохранение данных и выход...")
                self.save_data()
                break
            else:
                print("❌ Неверный ввод. Попробуйте снова.")

# Запуск игры
if __name__ == "__main__":
    game = Game()
    game.run()
