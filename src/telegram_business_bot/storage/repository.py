"""Short-lived connections and explicit transactions; no network or personal-data logging."""

import re
import secrets
import sqlite3
from collections.abc import Callable, Collection, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from telegram_business_bot.domain import (
    MAX_TELEGRAM_ID,
    RequestStatus,
    ValidatedRequest,
    VisitWindow,
    validate_transition,
)
from telegram_business_bot.storage.schema import APPLICATION_ID, MIGRATIONS


class StorageError(RuntimeError):
    """Safe storage error; never contains SQL parameters, contact details or paths."""


class SchemaVersionError(StorageError):
    pass


class SubmissionConflict(StorageError):
    pass


class DispatcherAccessDenied(StorageError):
    pass


class RequestUnavailable(StorageError):
    pass


@dataclass(frozen=True, repr=False)
class RequestRecord:
    id: int
    reference: str
    request: ValidatedRequest
    status: RequestStatus
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, repr=False)
class SubmissionResult:
    record: RequestRecord
    created: bool


@dataclass(frozen=True, repr=False)
class StatusChange:
    from_status: RequestStatus | None
    to_status: RequestStatus
    actor_user_id: int
    changed_at: datetime


@dataclass(frozen=True, repr=False)
class NotificationJob:
    id: int
    record: RequestRecord


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("A timezone-aware timestamp is required")
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def _reference() -> str:
    return "TB-" + secrets.token_hex(8).upper()


def _record(row: sqlite3.Row) -> RequestRecord:
    request = ValidatedRequest(
        customer_user_id=row["customer_user_id"],
        customer_chat_id=row["customer_chat_id"],
        category=row["category"],
        problem_summary=row["problem_summary"],
        district=row["district"],
        visit_window=VisitWindow(
            datetime.fromisoformat(row["visit_start_at"]),
            datetime.fromisoformat(row["visit_end_at"]),
        ),
        contact_preference=row["contact_preference"],
        contact_details=row["contact_details"],
        consent_at=datetime.fromisoformat(row["consent_at"]),
        consent_version=row["consent_version"],
    )
    return RequestRecord(
        row["id"],
        row["reference"],
        request,
        RequestStatus(row["status"]),
        datetime.fromisoformat(row["created_at"]),
        datetime.fromisoformat(row["updated_at"]),
    )


class SQLiteRepository:
    def __init__(
        self,
        path: str | Path,
        *,
        dispatcher_user_ids: Collection[int] = (),
        reference_factory: Callable[[], str] = _reference,
    ):
        if str(path) == ":memory:":
            raise ValueError("Use a file database for durable requests")
        self.path = Path(path).resolve()
        self.dispatcher_user_ids = frozenset(dispatcher_user_ids)
        if any(
            type(user) is not int or not 0 < user <= MAX_TELEGRAM_ID
            for user in self.dispatcher_user_ids
        ):
            raise ValueError("Dispatcher IDs must be positive Telegram user IDs")
        self._reference_factory = reference_factory

    @contextmanager
    def _connection(self, *, create: bool = False) -> Iterator[sqlite3.Connection]:
        connection = None
        try:
            # mode=rw prevents a typo or premature read from silently creating an empty database.
            connection = sqlite3.connect(
                self.path if create else self.path.as_uri() + "?mode=rw",
                uri=not create,
                isolation_level=None,
                timeout=5.0,
            )
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            yield connection
        except sqlite3.Error:
            raise StorageError("Не удалось выполнить операцию с хранилищем заявок.") from None
        finally:
            if connection is not None:
                try:
                    if connection.in_transaction:
                        connection.rollback()
                finally:
                    connection.close()

    @contextmanager
    def _transaction(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            if connection.execute("PRAGMA application_id").fetchone()[
                0
            ] != APPLICATION_ID or connection.execute("PRAGMA user_version").fetchone()[0] != len(
                MIGRATIONS
            ):
                raise SchemaVersionError("Хранилище требует поддерживаемую версию схемы.")
            yield connection
            connection.commit()

    def initialize(self) -> None:
        """Explicitly create/migrate this product's database; reject unrelated/newer databases."""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            raise StorageError("Не удалось создать каталог хранилища заявок.") from None
        with self._connection(create=True) as connection:
            connection.execute("BEGIN IMMEDIATE")
            app_id = connection.execute("PRAGMA application_id").fetchone()[0]
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if app_id == 0 and version == 0:
                existing = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                ).fetchone()
                if existing is not None:
                    raise SchemaVersionError("Выбранная база данных не принадлежит этому продукту.")
            elif app_id != APPLICATION_ID or not 0 <= version <= len(MIGRATIONS):
                raise SchemaVersionError("Версия или тип базы данных не поддерживается.")
            for number in range(version, len(MIGRATIONS)):
                for statement in MIGRATIONS[number]:
                    connection.execute(statement)
                # These integers are code-defined migration metadata, never user input.
                connection.execute(f"PRAGMA user_version = {number + 1}")
            connection.execute(f"PRAGMA application_id = {APPLICATION_ID}")
            connection.commit()

    def submit(
        self,
        request: ValidatedRequest,
        submission_key: str,
        *,
        now: datetime,
    ) -> SubmissionResult:
        """Persist one reviewed draft per user/key, including initial history and pending outbox."""
        if not isinstance(submission_key, str) or not re.fullmatch(
            r"[A-Za-z0-9_-]{16,128}", submission_key
        ):
            raise ValueError("submission_key must contain 16-128 ASCII letters, digits, '_' or '-'")
        timestamp = _timestamp(now)
        with self._transaction(write=True) as connection:
            existing = connection.execute(
                "SELECT * FROM requests WHERE customer_user_id=? AND submission_key=?",
                (request.customer_user_id, submission_key),
            ).fetchone()
            if existing is not None:
                result = _record(existing)
                # Replayed consent timestamps can differ; changing reviewed content needs a new key.
                if replace(request, consent_at=result.request.consent_at) != result.request:
                    raise SubmissionConflict(
                        "Данные повторной отправки изменились. Проверьте заявку снова."
                    )
                return SubmissionResult(result, False)
            if request.consent_at > now or request.visit_window.start_at <= now:
                raise ValueError("Consent must be recorded and the visit preference must be future")
            values = (
                submission_key,
                request.customer_user_id,
                request.customer_chat_id,
                request.category,
                request.problem_summary,
                request.district,
                _timestamp(request.visit_window.start_at),
                _timestamp(request.visit_window.end_at),
                request.contact_preference,
                request.contact_details,
                _timestamp(request.consent_at),
                request.consent_version,
                timestamp,
                timestamp,
            )
            for _ in range(5):
                reference = self._reference_factory()
                if not isinstance(reference, str) or not re.fullmatch(
                    r"TB-[A-F0-9]{16}", reference
                ):
                    raise ValueError("Reference factory must produce TB- followed by 16 hex digits")
                cursor = connection.execute(
                    """INSERT INTO requests (
                        reference, submission_key, customer_user_id, customer_chat_id,
                        category, problem_summary, district, visit_start_at, visit_end_at,
                        contact_preference, contact_details, consent_at, consent_version,
                        status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'new', ?, ?)
                    ON CONFLICT(reference) DO NOTHING""",
                    (reference, *values),
                )
                if cursor.rowcount == 1:
                    break
            else:
                raise StorageError("Не удалось назначить номер заявки. Повторите отправку.")
            request_id = cursor.lastrowid
            connection.execute(
                """INSERT INTO status_history (request_id, from_status, to_status,
                    actor_user_id, changed_at) VALUES (?, NULL, 'new', ?, ?)""",
                (request_id, request.customer_user_id, timestamp),
            )
            connection.execute(
                """INSERT INTO notification_outbox (request_id, kind, created_at, next_attempt_at)
                   VALUES (?, 'new_request', ?, ?)""",
                (request_id, timestamp, timestamp),
            )
            row = connection.execute("SELECT * FROM requests WHERE id=?", (request_id,)).fetchone()
            return SubmissionResult(_record(row), True)

    def pending_notifications(
        self, *, now: datetime, limit: int = 20
    ) -> tuple[NotificationJob, ...]:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        timestamp = _timestamp(now)
        with self._transaction() as connection:
            rows = connection.execute(
                """SELECT n.id AS outbox_id, r.* FROM notification_outbox n
                   JOIN requests r ON r.id=n.request_id
                   WHERE n.state='pending' AND n.next_attempt_at<=?
                   ORDER BY n.id LIMIT ?""",
                (timestamp, limit),
            ).fetchall()
            return tuple(NotificationJob(row["outbox_id"], _record(row)) for row in rows)

    def mark_notification_sent(self, outbox_id: int, *, now: datetime) -> bool:
        timestamp = _timestamp(now)
        with self._transaction(write=True) as connection:
            cursor = connection.execute(
                """UPDATE notification_outbox SET state='sent', delivered_at=?, last_error_code=NULL
                   WHERE id=? AND state='pending'""",
                (timestamp, outbox_id),
            )
            return cursor.rowcount == 1

    def mark_notification_failure(
        self,
        outbox_id: int,
        *,
        now: datetime,
        error_code: str,
        retry_after: int | None = None,
        permanent: bool = False,
    ) -> bool:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", error_code):
            raise ValueError("error_code must be a short safe identifier")
        if retry_after is not None and (type(retry_after) is not int or retry_after < 0):
            raise ValueError("retry_after must be a non-negative number of seconds")
        delays = (30, 120, 600, 1800, 3600)
        with self._transaction(write=True) as connection:
            row = connection.execute(
                "SELECT attempts FROM notification_outbox WHERE id=? AND state='pending'",
                (outbox_id,),
            ).fetchone()
            if row is None:
                return False
            attempts = row["attempts"] + 1
            terminal = permanent or attempts >= len(delays)
            delay = max(delays[min(attempts - 1, len(delays) - 1)], retry_after or 0)
            next_attempt = _timestamp(now + timedelta(seconds=delay))
            cursor = connection.execute(
                """UPDATE notification_outbox SET state=?, attempts=?, next_attempt_at=?,
                   last_error_code=? WHERE id=? AND state='pending'""",
                (
                    "failed" if terminal else "pending",
                    attempts,
                    next_attempt,
                    error_code,
                    outbox_id,
                ),
            )
            return cursor.rowcount == 1

    def get_for_customer(self, reference: str, customer_user_id: int) -> RequestRecord | None:
        """Enforce reference and owner in SQL; unavailable references return None."""
        if type(customer_user_id) is not int or not 0 < customer_user_id <= MAX_TELEGRAM_ID:
            return None
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM requests WHERE reference=? AND customer_user_id=?",
                (reference, customer_user_id),
            ).fetchone()
            return _record(row) if row is not None else None

    def history_for_customer(
        self, reference: str, customer_user_id: int
    ) -> tuple[StatusChange, ...]:
        if type(customer_user_id) is not int or not 0 < customer_user_id <= MAX_TELEGRAM_ID:
            return ()
        with self._transaction() as connection:
            rows = connection.execute(
                """SELECT h.* FROM status_history h JOIN requests r ON r.id=h.request_id
                   WHERE r.reference=? AND r.customer_user_id=? ORDER BY h.id""",
                (reference, customer_user_id),
            ).fetchall()
            return tuple(
                StatusChange(
                    RequestStatus(row["from_status"]) if row["from_status"] else None,
                    RequestStatus(row["to_status"]),
                    row["actor_user_id"],
                    datetime.fromisoformat(row["changed_at"]),
                )
                for row in rows
            )

    def update_status(
        self,
        reference: str,
        target: str,
        *,
        actor_user_id: int,
        now: datetime,
    ) -> RequestRecord:
        """Only configured dispatcher IDs may atomically change status and append its history."""
        if type(actor_user_id) is not int or actor_user_id not in self.dispatcher_user_ids:
            raise DispatcherAccessDenied("Действие доступно только диспетчеру.")
        timestamp = _timestamp(now)
        with self._transaction(write=True) as connection:
            row = connection.execute(
                "SELECT * FROM requests WHERE reference=?", (reference,)
            ).fetchone()
            if row is None:
                raise RequestUnavailable("Заявка недоступна.")
            record = _record(row)
            status = validate_transition(record.status, target)
            if status == record.status:
                return record
            if now < record.updated_at:
                raise ValueError("Status history timestamps must not move backwards")
            connection.execute(
                "UPDATE requests SET status=?, updated_at=? WHERE id=?",
                (status, timestamp, record.id),
            )
            connection.execute(
                """INSERT INTO status_history (request_id, from_status, to_status, actor_user_id,
                    changed_at) VALUES (?, ?, ?, ?, ?)""",
                (record.id, record.status, status, actor_user_id, timestamp),
            )
            return replace(record, status=status, updated_at=now.astimezone(UTC))
