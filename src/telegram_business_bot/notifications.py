"""Retryable dispatcher delivery for transactional request outbox records."""

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
)

from telegram_business_bot.domain import CATEGORIES, DISTRICTS
from telegram_business_bot.storage import NotificationJob, SQLiteRepository, StorageError

logger = logging.getLogger(__name__)


class DeliveryFailure(RuntimeError):
    """Safe delivery classification without exception text or request data."""

    def __init__(
        self,
        error_code: str,
        *,
        retry_after: int | None = None,
        permanent: bool = False,
    ) -> None:
        self.error_code = error_code
        self.retry_after = retry_after
        self.permanent = permanent
        super().__init__(error_code)


class NotificationTransport(Protocol):
    async def send(self, chat_id: int, text: str) -> None: ...


def dispatcher_message(job: NotificationJob, timezone: ZoneInfo) -> str:
    request = job.record.request
    contact = request.contact_details or f"Через Telegram (ID {request.customer_user_id})"
    start = request.visit_window.start_at.astimezone(timezone)
    end = request.visit_window.end_at.astimezone(timezone)
    return (
        f"Новая заявка {job.record.reference}\n"
        f"Техника: {CATEGORIES[request.category]}\n"
        f"Проблема: {request.problem_summary}\n"
        f"Район: {DISTRICTS[request.district]}\n"
        f"Окно ({timezone.key}): {start:%Y-%m-%d %H:%M} — {end:%H:%M}\n"
        f"Контакт: {contact}"
    )


class OutboxWorker:
    def __init__(
        self,
        repository: SQLiteRepository,
        transport: NotificationTransport,
        dispatcher_chat_id: int,
        timezone: ZoneInfo,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.repository = repository
        self.transport = transport
        self.dispatcher_chat_id = dispatcher_chat_id
        self.timezone = timezone
        self.clock = clock

    async def process_pending(self, *, limit: int = 20) -> int:
        jobs = self.repository.pending_notifications(now=self.clock(), limit=limit)
        for job in jobs:
            try:
                await self.transport.send(
                    self.dispatcher_chat_id, dispatcher_message(job, self.timezone)
                )
            except DeliveryFailure as error:
                self.repository.mark_notification_failure(
                    job.id,
                    now=self.clock(),
                    error_code=error.error_code,
                    retry_after=error.retry_after,
                    permanent=error.permanent,
                )
            except Exception:
                # Do not persist or log exception strings: they can contain payloads or secrets.
                self.repository.mark_notification_failure(
                    job.id, now=self.clock(), error_code="transport_error"
                )
            else:
                self.repository.mark_notification_sent(job.id, now=self.clock())
        return len(jobs)

    async def run(self, *, poll_interval: float = 5.0) -> None:
        while True:
            try:
                await self.process_pending()
            except StorageError as error:
                logger.warning(
                    "Outbox storage pass failed (%s); retrying on the next poll.",
                    type(error).__name__,
                )
            await asyncio.sleep(poll_interval)


class AiogramNotificationTransport:
    def __init__(self, bot: Bot) -> None:
        self.bot = bot

    async def send(self, chat_id: int, text: str) -> None:
        try:
            await self.bot.send_message(chat_id=chat_id, text=text)
        except TelegramRetryAfter as error:
            raise DeliveryFailure("telegram_rate_limit", retry_after=error.retry_after) from None
        except TelegramForbiddenError:
            raise DeliveryFailure("telegram_forbidden", permanent=True) from None
        except TelegramBadRequest:
            raise DeliveryFailure("telegram_bad_request", permanent=True) from None
