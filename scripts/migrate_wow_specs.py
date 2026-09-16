"""
Одноразовый скрипт: раскладывает уже созданные плоские "классы" игры
World of Warcraft: Forever по базовым классам (Warlock, Mage, Warrior...)
и проставляет им роль (танк/лекарь/дамагер).

Запускать один раз с сервера, после alembic upgrade head:

    python scripts/migrate_wow_specs.py

Скрипт ищет игру по названию "World of Warcraft: Forever" внутри гильдии,
для каждого известного спека находит существующий класс по имени, создаёт
(если ещё нет) родительский класс и привязывает к нему спек. Уже
существующие спеки, которых нет в списке ниже, не трогает.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.database.models import Game, GameClass
from app.database.session import SessionLocal

GAME_NAME = "World of Warcraft: Forever"

CLASS_ICONS = {
    "Warlock": "😈",
    "Mage": "🔮",
    "Warrior": "⚔️",
    "Rogue": "🗡️",
    "Druid": "🐾",
    "Hunter": "🏹",
    "Priest": "✨",
    "Paladin": "🛡️",
    "Shaman": "🌩️",
}

SPEC_TO_CLASS = {
    "Afflic Warlock": ("Warlock", "dps"),
    "Arcane Mage": ("Mage", "dps"),
    "Arms Warrior": ("Warrior", "dps"),
    "Assa Rogue": ("Rogue", "dps"),
    "Balance Druid": ("Druid", "dps"),
    "BM Hunter": ("Hunter", "dps"),
    "Combat Rogue": ("Rogue", "dps"),
    "DC Priest": ("Priest", "healer"),
    "Demon Warlock": ("Warlock", "dps"),
    "Destr Warlock": ("Warlock", "dps"),
    "Elem Shaman": ("Shaman", "dps"),
    "Enh Shaman": ("Shaman", "dps"),
    "Feral Druid": ("Druid", "tank"),
    "Fire Mage": ("Mage", "dps"),
    "Frost Mage": ("Mage", "dps"),
    "Fury Warrior": ("Warrior", "dps"),
    "Holy Paladin": ("Paladin", "healer"),
    "Holy Priest": ("Priest", "healer"),
    "MM Hunter": ("Hunter", "dps"),
    "Proto Paladin": ("Paladin", "tank"),
    "Proto Warrior": ("Warrior", "tank"),
    "Resto Druid": ("Druid", "healer"),
    "Resto Shaman": ("Shaman", "healer"),
    "Retri Paladin": ("Paladin", "dps"),
    "Shadow Priest": ("Priest", "dps"),
    "Subtlety Rogue": ("Rogue", "dps"),
    "Survival Hunter": ("Hunter", "dps"),
}


async def main() -> None:
    async with SessionLocal() as session:
        result = await session.execute(select(Game).where(Game.name == GAME_NAME))
        games = list(result.scalars().all())
        if not games:
            print(f"Игра '{GAME_NAME}' не найдена ни в одной гильдии, нечего делать.")
            return

        for game in games:
            print(f"Гильдия {game.guild_id}, игра {game.name} ({game.id})")

            result = await session.execute(select(GameClass).where(GameClass.game_id == game.id))
            existing = {c.name: c for c in result.scalars().all()}

            parent_by_name: dict[str, GameClass] = {}
            moved = 0
            skipped = []

            for spec_name, (class_name, role) in SPEC_TO_CLASS.items():
                spec = existing.get(spec_name)
                if spec is None:
                    skipped.append(spec_name)
                    continue

                parent = parent_by_name.get(class_name) or existing.get(class_name)
                if parent is None:
                    parent = GameClass(
                        game_id=game.id,
                        name=class_name,
                        icon=CLASS_ICONS.get(class_name, "⚡"),
                        created_by=game.created_by,
                    )
                    session.add(parent)
                    await session.flush()
                    existing[class_name] = parent
                parent_by_name[class_name] = parent

                spec.parent_class_id = parent.id
                spec.role = role
                moved += 1

            await session.commit()
            print(f"  Перенесено спеков: {moved}")
            if skipped:
                print(f"  Не найдено в базе (пропущено): {', '.join(skipped)}")

    print("Готово.")


if __name__ == "__main__":
    asyncio.run(main())
