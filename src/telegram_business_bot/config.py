"""Side-effect-free configuration; never print environment values or credentials."""

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aiogram.utils.token import TokenValidationError, validate_token


class ConfigurationError(ValueError):
    """A configuration error safe to display to an operator."""


def _integer(value: str, name: str, *, positive: bool = False) -> int:
    try:
        result = int(value)
    except ValueError:
        raise ConfigurationError(f"{name}: ожидается целое число.") from None
    if result == 0 or (positive and result < 0):
        raise ConfigurationError(f"{name}: недопустимый идентификатор.")
    return result


@dataclass(frozen=True)
class Settings:
    mode: str
    database_path: Path
    service_timezone: ZoneInfo
    dispatcher_chat_id: int | None
    dispatcher_user_ids: frozenset[int]
    bot_token: str | None = field(default=None, repr=False)

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "Settings":
        env = os.environ if environ is None else environ
        mode = env.get("BOT_MODE", "simulator").strip()
        if mode not in {"simulator", "live"}:
            raise ConfigurationError("BOT_MODE: допустимы simulator или live.")
        try:
            timezone = ZoneInfo(env.get("SERVICE_TIMEZONE", "Asia/Vladivostok").strip())
        except (ZoneInfoNotFoundError, ValueError):
            raise ConfigurationError("SERVICE_TIMEZONE: неизвестный часовой пояс.") from None
        database = env.get("DATABASE_PATH", "data/requests.sqlite3").strip()
        if not database or "\x00" in database or database == ":memory:":
            raise ConfigurationError("DATABASE_PATH: нужен путь к файлу базы данных.")
        raw_chat = env.get("DISPATCHER_CHAT_ID", "").strip()
        chat_id = _integer(raw_chat, "DISPATCHER_CHAT_ID") if raw_chat else None
        raw_users = env.get("DISPATCHER_USER_IDS", "").strip()
        users = (
            frozenset(
                _integer(part.strip(), "DISPATCHER_USER_IDS", positive=True)
                for part in raw_users.split(",")
            )
            if raw_users
            else frozenset()
        )
        # Offline mode intentionally ignores credentials, including expired or malformed tokens.
        token = env.get("BOT_TOKEN", "").strip() if mode == "live" else None
        if mode == "live":
            try:
                validate_token(token)
            except TokenValidationError:
                raise ConfigurationError("BOT_TOKEN: задайте корректный токен для live.") from None
            if chat_id is None or not users:
                raise ConfigurationError("Для live нужны DISPATCHER_CHAT_ID и DISPATCHER_USER_IDS.")
        return cls(mode, Path(database), timezone, chat_id, users, token)
