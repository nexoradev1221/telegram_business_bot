import asyncio
import sqlite3
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.methods import SendMessage

from telegram_business_bot.domain import RequestDraft
from telegram_business_bot.notifications import (
    AiogramNotificationTransport,
    DeliveryFailure,
    OutboxWorker,
)
from telegram_business_bot.storage import SQLiteRepository

NOW = datetime(2026, 11, 27, 1, tzinfo=UTC)
TIMEZONE = ZoneInfo("Asia/Vladivostok")


def create_repo(path):
    repository = SQLiteRepository(path)
    repository.initialize()
    request = RequestDraft(
        customer_user_id=101,
        customer_chat_id=101,
        category="washer",
        problem_summary="Не работает слив воды",
        district="central",
        visit_window="2026-11-28 09:00-12:00",
        contact_preference="phone",
        contact_details="+71234567890",
        consent=True,
    ).validate(now=NOW, timezone=TIMEZONE)
    repository.submit(request, "notification-test-key-0001", now=NOW)
    return repository


class FakeTransport:
    def __init__(self, result=None):
        self.result = result
        self.sent = []

    async def send(self, chat_id, text):
        self.sent.append((chat_id, text))
        if isinstance(self.result, BaseException):
            raise self.result


class FailingBot:
    def __init__(self, error):
        self.error = error

    async def send_message(self, **kwargs):
        raise self.error


def test_outbox_success_sends_localized_details_and_marks_sent(tmp_path):
    async def scenario():
        repository = create_repo(tmp_path / "requests.sqlite3")
        transport = FakeTransport()
        worker = OutboxWorker(repository, transport, -100123, TIMEZONE, clock=lambda: NOW)
        assert await worker.process_pending() == 1
        assert len(transport.sent) == 1
        chat_id, text = transport.sent[0]
        assert chat_id == -100123
        assert "Новая заявка TB-" in text
        assert "Не работает слив воды" in text
        assert "Окно (Asia/Vladivostok): 2026-11-28 09:00 — 12:00" in text
        assert "+71234567890" in text
        assert repository.pending_notifications(now=NOW) == ()
        with sqlite3.connect(repository.path) as connection:
            assert connection.execute(
                "SELECT state, attempts FROM notification_outbox"
            ).fetchone() == ("sent", 0)

    asyncio.run(scenario())


def test_retry_after_is_honored_and_job_survives_repository_restart(tmp_path):
    async def scenario():
        path = tmp_path / "requests.sqlite3"
        repository = create_repo(path)
        worker = OutboxWorker(
            repository,
            FakeTransport(DeliveryFailure("telegram_rate_limit", retry_after=3600)),
            -100123,
            TIMEZONE,
            clock=lambda: NOW,
        )
        await worker.process_pending()
        restarted = SQLiteRepository(path)
        assert restarted.pending_notifications(now=NOW + timedelta(seconds=3599)) == ()
        assert len(restarted.pending_notifications(now=NOW + timedelta(seconds=3600))) == 1
        with sqlite3.connect(path) as connection:
            assert connection.execute(
                "SELECT state, attempts, last_error_code FROM notification_outbox"
            ).fetchone() == ("pending", 1, "telegram_rate_limit")

    asyncio.run(scenario())


def test_unexpected_delivery_error_is_retryable_without_persisting_exception_text(tmp_path):
    async def scenario():
        path = tmp_path / "requests.sqlite3"
        repository = create_repo(path)
        worker = OutboxWorker(
            repository,
            FakeTransport(RuntimeError("token=secret; personal=private")),
            -100123,
            TIMEZONE,
            clock=lambda: NOW,
        )
        await worker.process_pending()
        with sqlite3.connect(path) as connection:
            state, attempts, code = connection.execute(
                "SELECT state, attempts, last_error_code FROM notification_outbox"
            ).fetchone()
        assert (state, attempts, code) == ("pending", 1, "transport_error")
        with sqlite3.connect(path) as connection:
            stored = str(
                connection.execute("SELECT last_error_code FROM notification_outbox").fetchone()
            )
        assert "secret" not in stored and "private" not in stored

    asyncio.run(scenario())


def test_blocked_dispatcher_chat_is_recorded_as_terminal(tmp_path):
    async def scenario():
        path = tmp_path / "requests.sqlite3"
        repository = create_repo(path)
        worker = OutboxWorker(
            repository,
            FakeTransport(DeliveryFailure("telegram_forbidden", permanent=True)),
            -100123,
            TIMEZONE,
            clock=lambda: NOW,
        )
        await worker.process_pending()
        assert repository.pending_notifications(now=NOW + timedelta(days=1)) == ()
        with sqlite3.connect(path) as connection:
            assert connection.execute(
                "SELECT state, attempts, last_error_code FROM notification_outbox"
            ).fetchone() == ("failed", 1, "telegram_forbidden")

    asyncio.run(scenario())


def test_five_failures_stop_retrying(tmp_path):
    repository = create_repo(tmp_path / "requests.sqlite3")
    due = NOW
    for _ in range(5):
        [job] = repository.pending_notifications(now=due)
        repository.mark_notification_failure(
            job.id,
            now=due,
            error_code="network_error",
        )
        due += timedelta(hours=2)
    assert repository.pending_notifications(now=due + timedelta(days=1)) == ()
    with sqlite3.connect(repository.path) as connection:
        assert connection.execute("SELECT state, attempts FROM notification_outbox").fetchone() == (
            "failed",
            5,
        )


def test_aiogram_rate_limit_preserves_retry_after_without_error_text():
    async def scenario():
        method = SendMessage(chat_id=1, text="safe")
        transport = AiogramNotificationTransport(
            FailingBot(TelegramRetryAfter(method, "secret response", retry_after=42))
        )
        with pytest.raises(DeliveryFailure) as captured:
            await transport.send(1, "message")
        assert captured.value.error_code == "telegram_rate_limit"
        assert captured.value.retry_after == 42
        assert "secret" not in str(captured.value)

    asyncio.run(scenario())


def test_aiogram_forbidden_is_terminal_and_redacted():
    async def scenario():
        method = SendMessage(chat_id=1, text="safe")
        transport = AiogramNotificationTransport(
            FailingBot(TelegramForbiddenError(method, "private error response"))
        )
        with pytest.raises(DeliveryFailure) as captured:
            await transport.send(1, "message")
        assert captured.value.error_code == "telegram_forbidden"
        assert captured.value.permanent is True
        assert "private" not in str(captured.value)

    asyncio.run(scenario())
