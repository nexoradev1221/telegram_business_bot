"""Configuration validation and live Telegram startup."""

import argparse
import asyncio
import sys
from collections.abc import Sequence

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from telegram_business_bot.config import ConfigurationError, Settings
from telegram_business_bot.storage import SQLiteRepository, StorageError
from telegram_business_bot.telegram_form import build_form_router


def main(argv: Sequence[str] | None = None) -> int:
    # Redirected Windows streams can inherit a legacy code page without Cyrillic.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Бот заявок на ремонт техники")
    parser.add_argument("--check-config", action="store_true", help="Проверить настройки без сети")
    args = parser.parse_args(argv)
    try:
        settings = Settings.from_env()
    except ConfigurationError as error:
        print(str(error), file=sys.stderr)
        return 2
    if not args.check_config and settings.mode == "simulator":
        print("Симулятор будет доступен в следующем этапе. Используйте --check-config.")
        return 2
    if not args.check_config:
        repository = SQLiteRepository(
            settings.database_path,
            dispatcher_user_ids=settings.dispatcher_user_ids,
        )
        try:
            repository.initialize()
        except StorageError as error:
            print(str(error), file=sys.stderr)
            return 2
        asyncio.run(_run_live(settings, repository))
        return 0
    print(
        f"Настройки корректны. Режим: {settings.mode}. "
        f"Часовой пояс: {settings.service_timezone.key}."
    )
    return 0


async def _run_live(settings: Settings, repository: SQLiteRepository) -> None:
    """Run only with explicitly configured live credentials."""
    bot = Bot(token=settings.bot_token)
    dispatcher = Dispatcher(storage=MemoryStorage())
    dispatcher.include_router(build_form_router(repository, settings.service_timezone))
    try:
        await dispatcher.start_polling(bot)
    finally:
        await bot.session.close()
