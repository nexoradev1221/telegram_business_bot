import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from threading import Barrier
from zoneinfo import ZoneInfo

import pytest

import telegram_business_bot.storage.repository as repository_module
from telegram_business_bot.domain import RequestDraft, RequestStatus, RequestValidationError
from telegram_business_bot.storage import (
    DispatcherAccessDenied,
    RequestUnavailable,
    SchemaVersionError,
    SQLiteRepository,
    StorageError,
    SubmissionConflict,
)
from telegram_business_bot.storage.schema import APPLICATION_ID

NOW = datetime(2026, 11, 17, 10, tzinfo=UTC)
KEY = "synthetic-draft-key-0001"
DISPATCHER = 9001


def request(user_id=101, **changes):
    value = RequestDraft(
        customer_user_id=user_id,
        customer_chat_id=user_id,
        category="washer",
        problem_summary="Не работает слив воды",
        district="central",
        visit_window="2026-11-18 09:00-12:00",
        contact_preference="telegram",
        contact_details=None,
        consent=True,
    )
    return replace(value, **changes).validate(now=NOW, timezone=ZoneInfo("Asia/Vladivostok"))


@pytest.fixture
def repo(tmp_path):
    result = SQLiteRepository(
        tmp_path / "данные #1" / "requests.sqlite3", dispatcher_user_ids={DISPATCHER}
    )
    result.initialize()
    return result


def counts(path):
    with closing(sqlite3.connect(path)) as connection:
        return tuple(
            connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in ("requests", "status_history", "notification_outbox")
        )


def test_constructor_and_reads_do_not_silently_create_database(tmp_path):
    path = tmp_path / "missing.sqlite3"
    value = SQLiteRepository(path)
    assert not path.exists()
    with pytest.raises(StorageError):
        value.get_for_customer("missing", 101)
    assert not path.exists()


def test_initialize_is_repeatable_and_identifies_its_schema(repo):
    repo.initialize()
    SQLiteRepository(repo.path).initialize()
    with closing(sqlite3.connect(repo.path)) as connection:
        assert connection.execute("PRAGMA application_id").fetchone()[0] == APPLICATION_ID
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
    assert counts(repo.path) == (0, 0, 0)


def test_migration_failure_rolls_back_all_ddl_and_metadata(tmp_path, monkeypatch):
    value = SQLiteRepository(tmp_path / "atomic.sqlite3")
    with monkeypatch.context() as patch:
        patch.setattr(
            repository_module,
            "MIGRATIONS",
            (
                (
                    "CREATE TABLE partial_migration(id INTEGER)",
                    "INVALID SQL",
                ),
            ),
        )
        with pytest.raises(StorageError):
            value.initialize()
    with closing(sqlite3.connect(value.path)) as connection:
        assert (
            connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == []
        )
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 0
        assert connection.execute("PRAGMA application_id").fetchone()[0] == 0
    value.initialize()
    assert counts(value.path) == (0, 0, 0)


def test_unrelated_database_is_never_adopted(tmp_path):
    path = tmp_path / "foreign.sqlite3"
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("CREATE TABLE unrelated(id INTEGER)")
        connection.commit()
    with pytest.raises(SchemaVersionError):
        SQLiteRepository(path).initialize()
    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall() == [("unrelated",)]
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 0


def test_future_schema_is_rejected_without_downgrade(repo):
    with closing(sqlite3.connect(repo.path)) as connection:
        connection.execute("PRAGMA user_version=999")
    with pytest.raises(SchemaVersionError):
        repo.initialize()
    with pytest.raises(SchemaVersionError):
        repo.get_for_customer("unknown", 101)
    with closing(sqlite3.connect(repo.path)) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 999


def test_request_round_trip_survives_new_repository_and_real_process(repo):
    data = request(contact_preference="phone", contact_details="+99900000001")
    result = repo.submit(data, KEY, now=NOW)
    assert result.created
    assert result.record.request == data
    assert result.record.status == RequestStatus.NEW
    assert result.record.created_at == result.record.updated_at == NOW
    assert len(result.record.reference) == 19
    reopened = SQLiteRepository(repo.path)
    assert reopened.get_for_customer(result.record.reference, 101) == result.record
    code = (
        "import sys; from telegram_business_bot.storage import SQLiteRepository; "
        "record=SQLiteRepository(sys.argv[1]).get_for_customer(sys.argv[2],101); "
        "assert record is not None; print(record.status.value)"
    )
    child = subprocess.run(
        [sys.executable, "-c", code, str(repo.path), result.record.reference],
        capture_output=True,
        check=True,
        text=True,
    )
    assert child.stdout.strip() == "new"
    for representation in (repr(result), repr(result.record), repr(result.record.request)):
        assert "+999" not in representation
        assert "слив" not in representation
        assert KEY not in representation
    assert counts(repo.path) == (1, 1, 1)


def test_duplicate_after_restart_returns_original_even_after_visit_window(repo):
    original = repo.submit(request(), KEY, now=NOW)
    replay = SQLiteRepository(repo.path).submit(
        replace(request(), consent_at=NOW + timedelta(seconds=1)),
        KEY,
        now=NOW + timedelta(days=10),
    )
    assert not replay.created
    assert replay.record == original.record
    assert counts(repo.path) == (1, 1, 1)


def test_changed_payload_with_same_user_and_key_is_rejected(repo):
    original = repo.submit(request(), KEY, now=NOW)
    with pytest.raises(SubmissionConflict):
        repo.submit(request(problem_summary="Другая неисправность"), KEY, now=NOW)
    assert repo.get_for_customer(original.record.reference, 101) == original.record
    assert counts(repo.path) == (1, 1, 1)


def test_key_is_scoped_to_authenticated_customer(repo):
    first = repo.submit(request(101), KEY, now=NOW)
    second = repo.submit(request(102), KEY, now=NOW)
    assert first.record.reference != second.record.reference
    assert second.created
    assert repo.get_for_customer(first.record.reference, 102) is None
    assert repo.history_for_customer(first.record.reference, 102) == ()
    assert counts(repo.path) == (2, 2, 2)


@pytest.mark.parametrize("bad_identity", ["101", True, 0, -101, None])
def test_owner_identity_must_be_a_positive_integer(repo, bad_identity):
    saved = repo.submit(request(), KEY, now=NOW)
    assert repo.get_for_customer(saved.record.reference, bad_identity) is None
    assert repo.history_for_customer(saved.record.reference, bad_identity) == ()


def test_sql_parameters_cannot_change_query_or_schema(repo):
    text = "сломалась'); DROP TABLE requests; --"
    saved = repo.submit(request(problem_summary=text), KEY, now=NOW)
    assert repo.get_for_customer(saved.record.reference, 101).request.problem_summary == text
    assert repo.get_for_customer("x' OR 1=1 --", 101) is None
    assert repo.history_for_customer("x' OR 1=1 --", 101) == ()
    assert counts(repo.path) == (1, 1, 1)


@pytest.mark.parametrize("key", ["", "a" * 15, "a" * 129, "проба" * 4, "x' OR 1=1 --" * 2])
def test_invalid_submission_keys_make_no_records(repo, key):
    with pytest.raises(ValueError):
        repo.submit(request(), key, now=NOW)
    assert counts(repo.path) == (0, 0, 0)


def test_reference_collision_retries_without_duplicate_side_effects(repo):
    references = iter(["TB-" + "A" * 16, "TB-" + "A" * 16, "TB-" + "B" * 16])
    value = SQLiteRepository(repo.path, reference_factory=lambda: next(references))
    first = value.submit(request(), KEY, now=NOW)
    second = value.submit(request(), "different-draft-key", now=NOW)
    assert first.record.reference == "TB-" + "A" * 16
    assert second.record.reference == "TB-" + "B" * 16
    assert counts(repo.path) == (2, 2, 2)


def test_exhausted_reference_collisions_roll_back(repo):
    value = SQLiteRepository(repo.path, reference_factory=lambda: "TB-" + "A" * 16)
    value.submit(request(), KEY, now=NOW)
    with pytest.raises(StorageError):
        value.submit(request(), "different-draft-key", now=NOW)
    assert counts(repo.path) == (1, 1, 1)


def test_outbox_failure_rolls_back_request_and_initial_history(repo):
    with closing(sqlite3.connect(repo.path)) as connection:
        connection.execute("""CREATE TRIGGER deny_outbox BEFORE INSERT ON notification_outbox
            BEGIN SELECT RAISE(ABORT, 'synthetic private payload'); END""")
        connection.commit()
    with pytest.raises(StorageError) as error:
        repo.submit(request(), KEY, now=NOW)
    assert "private payload" not in str(error.value)
    assert counts(repo.path) == (0, 0, 0)


def test_initial_history_and_pending_notification_are_durable(repo):
    saved = repo.submit(request(), KEY, now=NOW)
    history = SQLiteRepository(repo.path).history_for_customer(saved.record.reference, 101)
    assert len(history) == 1
    assert history[0].from_status is None
    assert history[0].to_status == RequestStatus.NEW
    assert history[0].actor_user_id == 101
    assert history[0].changed_at == NOW
    with closing(sqlite3.connect(repo.path)) as connection:
        assert connection.execute(
            "SELECT request_id,state,attempts FROM notification_outbox"
        ).fetchall() == [(saved.record.id, "pending", 0)]


def test_status_update_and_history_survive_restart_with_idempotent_repeat(repo):
    saved = repo.submit(request(), KEY, now=NOW)
    changed = repo.update_status(
        saved.record.reference,
        "contacted",
        actor_user_id=DISPATCHER,
        now=NOW + timedelta(seconds=1),
    )
    assert changed.status == RequestStatus.CONTACTED
    again = repo.update_status(
        saved.record.reference,
        "contacted",
        actor_user_id=DISPATCHER,
        now=NOW + timedelta(seconds=2),
    )
    assert again == changed
    reopened = SQLiteRepository(repo.path)
    assert reopened.get_for_customer(saved.record.reference, 101) == changed
    history = reopened.history_for_customer(saved.record.reference, 101)
    assert [item.to_status for item in history] == [RequestStatus.NEW, RequestStatus.CONTACTED]
    assert history[-1].actor_user_id == DISPATCHER
    assert history[-1].changed_at == NOW + timedelta(seconds=1)
    assert counts(repo.path) == (1, 2, 1)


def test_status_update_denies_unconfigured_dispatchers_before_record_lookup(repo):
    saved = repo.submit(request(), KEY, now=NOW)
    for reference in (saved.record.reference, "unknown"):
        with pytest.raises(DispatcherAccessDenied):
            repo.update_status(reference, "closed", actor_user_id=101, now=NOW)
    with pytest.raises(DispatcherAccessDenied):
        SQLiteRepository(repo.path).update_status(
            saved.record.reference, "closed", actor_user_id=DISPATCHER, now=NOW
        )
    assert repo.get_for_customer(saved.record.reference, 101).status == RequestStatus.NEW
    assert counts(repo.path) == (1, 1, 1)


def test_authorized_unknown_reference_is_unavailable(repo):
    with pytest.raises(RequestUnavailable):
        repo.update_status("unknown", "closed", actor_user_id=DISPATCHER, now=NOW)


def test_invalid_transition_and_backdated_change_leave_history_unchanged(repo):
    saved = repo.submit(request(), KEY, now=NOW)
    with pytest.raises(RequestValidationError):
        repo.update_status(saved.record.reference, "scheduled", actor_user_id=DISPATCHER, now=NOW)
    with pytest.raises(ValueError):
        repo.update_status(
            saved.record.reference,
            "contacted",
            actor_user_id=DISPATCHER,
            now=NOW - timedelta(seconds=1),
        )
    assert counts(repo.path) == (1, 1, 1)


def test_failed_history_append_rolls_back_status_change(repo):
    saved = repo.submit(request(), KEY, now=NOW)
    with closing(sqlite3.connect(repo.path)) as connection:
        connection.execute("""CREATE TRIGGER deny_change BEFORE INSERT ON status_history
            WHEN NEW.from_status IS NOT NULL BEGIN SELECT RAISE(ABORT, 'synthetic failure'); END""")
        connection.commit()
    with pytest.raises(StorageError):
        repo.update_status(saved.record.reference, "contacted", actor_user_id=DISPATCHER, now=NOW)
    assert repo.get_for_customer(saved.record.reference, 101).status == RequestStatus.NEW
    assert counts(repo.path) == (1, 1, 1)


def test_concurrent_duplicate_submission_creates_exactly_one_durable_request(repo):
    barrier = Barrier(8)
    data = request()

    def submit(_):
        barrier.wait(timeout=10)
        return SQLiteRepository(repo.path).submit(data, KEY, now=NOW)

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(submit, range(8)))
    assert sum(item.created for item in results) == 1
    assert len({item.record.reference for item in results}) == 1
    assert counts(repo.path) == (1, 1, 1)


def test_concurrent_distinct_submissions_have_unique_references(repo):
    barrier = Barrier(8)
    data = request()

    def submit(index):
        barrier.wait(timeout=10)
        return SQLiteRepository(repo.path).submit(data, f"synthetic-key-{index:04}", now=NOW)

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(submit, range(8)))
    assert all(item.created for item in results)
    assert len({item.record.reference for item in results}) == 8
    assert counts(repo.path) == (8, 8, 8)


def test_concurrent_initialization_is_safe(tmp_path):
    path = tmp_path / "concurrent.sqlite3"
    barrier = Barrier(4)

    def initialize(_):
        barrier.wait(timeout=10)
        SQLiteRepository(path).initialize()

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(initialize, range(4)))
    assert counts(path) == (0, 0, 0)
