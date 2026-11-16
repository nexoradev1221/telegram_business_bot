"""Configuration check only; live polling and simulator arrive in later milestones."""

import argparse
import sys
from collections.abc import Sequence

from telegram_business_bot.config import ConfigurationError, Settings


def main(argv: Sequence[str] | None = None) -> int:
    # Redirected Windows streams can inherit a legacy code page without Cyrillic.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Бот заявок на ремонт техники")
    parser.add_argument("--check-config", action="store_true", help="Проверить настройки без сети")
    args = parser.parse_args(argv)
    if not args.check_config:
        parser.print_help()
        print("Обработка заявок ещё не реализована. Используйте --check-config.")
        return 2
    try:
        settings = Settings.from_env()
    except ConfigurationError as error:
        print(str(error), file=sys.stderr)
        return 2
    print(
        f"Настройки корректны. Режим: {settings.mode}. "
        f"Часовой пояс: {settings.service_timezone.key}."
    )
    return 0
