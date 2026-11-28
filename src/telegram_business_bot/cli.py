"""Configuration validation and live Telegram startup."""

import argparse
import asyncio
import os
import sys
from collections.abc import Sequence
from contextlib import suppress

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from telegram_business_bot.config import ConfigurationError, Settings
from telegram_business_bot.notifications import AiogramNotificationTransport, OutboxWorker
from telegram_business_bot.simulator import run_demo
from telegram_business_bot.storage import SQLiteRepository, StorageError
from telegram_business_bot.telegram_form import build_form_router


def main(argv: Sequence[str] | None = None) -> int:
    # Redirected Windows streams can inherit a legacy code page without Cyrillic.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Бот заявок на ремонт техники")
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--check-config", action="store_true", help="Проверить настройки без сети")
    actions.add_argument("--demo", action="store_true", help="Запустить офлайн-сценарий без токена")
    args = parser.parse_args(argv)
    if args.demo:
        try:
            settings = Settings.from_env(
                {
                    "BOT_MODE": "simulator",
                    "SERVICE_TIMEZONE": os.environ.get("SERVICE_TIMEZONE", "Asia/Vladivostok"),
                }
            )
            run_demo(settings.service_timezone)
        except ConfigurationError as error:
            print(str(error), file=sys.stderr)
            return 2
        return 0
    try:
        settings = Settings.from_env()
    except ConfigurationError as error:
        print(str(error), file=sys.stderr)
        return 2
    if not args.check_config and settings.mode == "simulator":
        print("Для офлайн-демонстрации используйте --demo; настройки: --check-config.")
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
    if settings.dispatcher_chat_id is None:
        raise ConfigurationError("Для live нужен DISPATCHER_CHAT_ID.")
    notification_task = asyncio.create_task(
        OutboxWorker(
            repository,
            AiogramNotificationTransport(bot),
            settings.dispatcher_chat_id,
            settings.service_timezone,
        ).run(),
        name="dispatcher-outbox-worker",
    )
    try:
        await dispatcher.start_polling(bot)
    finally:
        notification_task.cancel()
        try:
            with suppress(asyncio.CancelledError):
                await notification_task
        finally:
            await bot.session.close()
