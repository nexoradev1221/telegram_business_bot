"""Token-free end-to-end sample using the same domain, storage, and outbox worker."""

import asyncio
import json
import tempfile
from datetime import UTC, datetime, timedelta
from importlib.resources import files
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from telegram_business_bot.domain import STATUS_LABELS, RequestDraft, RequestStatus
from telegram_business_bot.notifications import OutboxWorker
from telegram_business_bot.storage import SQLiteRepository

_SAMPLE_USER_ID = 900_101
_SAMPLE_DISPATCHER_ID = 900_201


class _ConsoleTransport:
    async def send(self, chat_id: int, text: str) -> None:
        print(f"\nУведомление диспетчеру (чат {chat_id}):\n{text}")


def _sample_fields() -> dict[str, str]:
    sample = files("telegram_business_bot").joinpath("sample_request.json")
    return json.loads(sample.read_text(encoding="utf-8"))


def run_demo(timezone: ZoneInfo) -> None:
    """Create and process one synthetic request in a temporary local database."""
    now = datetime.now(UTC)
    tomorrow = now.astimezone(timezone).date() + timedelta(days=1)
    fields = _sample_fields()
    draft = RequestDraft(
        customer_user_id=_SAMPLE_USER_ID,
        customer_chat_id=_SAMPLE_USER_ID,
        category=fields["category"],
        problem_summary=fields["problem_summary"],
        district=fields["district"],
        visit_window=f"{tomorrow:%Y-%m-%d} 09:00-12:00",
        contact_preference=fields["contact_preference"],
        contact_details=fields.get("contact_details"),
        consent=True,
    )

    with tempfile.TemporaryDirectory(prefix="telegram-business-bot-demo-") as directory:
        repository = SQLiteRepository(
            Path(directory) / "demo.sqlite3",
            dispatcher_user_ids={_SAMPLE_DISPATCHER_ID},
        )
        repository.initialize()
        result = repository.submit(
            draft.validate(now=now, timezone=timezone),
            f"demo-{uuid4().hex}",
            now=now,
        )
        if not result.created:
            raise RuntimeError("Fresh demo database unexpectedly contained a request")
        print(f"Синтетическая заявка создана: {result.record.reference}")

        async def send_notification() -> None:
            worker = OutboxWorker(
                repository,
                _ConsoleTransport(),
                _SAMPLE_DISPATCHER_ID,
                timezone,
                clock=lambda: now,
            )
            processed = await worker.process_pending()
            if processed != 1:
                raise RuntimeError("Demo notification was not processed")

        asyncio.run(send_notification())
        repository.update_status(
            result.record.reference,
            RequestStatus.CONTACTED,
            actor_user_id=_SAMPLE_DISPATCHER_ID,
            now=now + timedelta(seconds=1),
        )
        closed = repository.update_status(
            result.record.reference,
            RequestStatus.CLOSED,
            actor_user_id=_SAMPLE_DISPATCHER_ID,
            now=now + timedelta(seconds=2),
        )
        saved = repository.get_for_customer(result.record.reference, _SAMPLE_USER_ID)
        history = repository.history_for_customer(result.record.reference, _SAMPLE_USER_ID)
        if saved is None or saved.status is not RequestStatus.CLOSED:
            raise RuntimeError("Demo customer lookup did not return the closed request")
        print(
            f"Диспетчер закрыл заявку: {STATUS_LABELS[closed.status]}. "
            f"Проверка клиента: {STATUS_LABELS[saved.status]}; записей истории: {len(history)}."
        )
