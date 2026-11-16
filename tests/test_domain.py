from dataclasses import replace
from datetime import UTC, datetime, timedelta
from itertools import product
from zoneinfo import ZoneInfo

import pytest

from telegram_business_bot.domain import (
    CONSENT_VERSION,
    MAX_TELEGRAM_ID,
    RequestDraft,
    RequestStatus,
    RequestValidationError,
    parse_visit_window,
    validate_transition,
)

NOW = datetime(2026, 11, 16, tzinfo=UTC)
TIMEZONE = ZoneInfo("Asia/Vladivostok")


def draft(**changes):
    base = RequestDraft(
        customer_user_id=101,
        customer_chat_id=101,
        category="washer",
        problem_summary="  Не работает   слив\nводы  ",
        district="central",
        visit_window="2026-11-17 09:00-12:00",
        contact_preference="telegram",
        contact_details=None,
        consent=True,
    )
    return replace(base, **changes)


def test_valid_request_normalizes_summary_and_records_explicit_consent():
    result = draft().validate(now=NOW, timezone=TIMEZONE)
    assert result.problem_summary == "Не работает слив воды"
    assert result.visit_window.start_at == datetime(2026, 11, 16, 23, tzinfo=UTC)
    assert result.visit_window.end_at == datetime(2026, 11, 17, 2, tzinfo=UTC)
    assert result.consent_at == NOW
    assert result.consent_version == CONSENT_VERSION
    assert result.contact_details is None


@pytest.mark.parametrize(
    "change,field",
    [
        ({"consent": False}, "consent"),
        ({"consent": 1}, "consent"),
        ({"customer_user_id": True}, "customer_user_id"),
        ({"customer_user_id": 0}, "customer_user_id"),
        ({"customer_user_id": MAX_TELEGRAM_ID + 1}, "customer_user_id"),
        ({"customer_chat_id": -101}, "customer_chat_id"),
        ({"customer_chat_id": 102}, "customer_chat_id"),
        ({"category": "unknown"}, "category"),
        ({"district": "unknown"}, "district"),
        ({"problem_summary": "    "}, "problem_summary"),
        ({"problem_summary": "abcd"}, "problem_summary"),
        ({"problem_summary": "x" * 1001}, "problem_summary"),
        ({"problem_summary": "private\x00payload"}, "problem_summary"),
        ({"problem_summary": "private\u202epayload"}, "problem_summary"),
        ({"problem_summary": None}, "problem_summary"),
        ({"contact_preference": "email"}, "contact_preference"),
        ({"contact_preference": None}, "contact_preference"),
        ({"contact_preference": "phone", "contact_details": None}, "contact_details"),
        ({"contact_preference": "phone", "contact_details": ""}, "contact_details"),
        ({"contact_preference": "phone", "contact_details": "0000000000"}, "contact_details"),
        ({"contact_preference": "phone", "contact_details": "+0123456789"}, "contact_details"),
        (
            {"contact_preference": "phone", "contact_details": "+99900000001 ext 2"},
            "contact_details",
        ),
        ({"contact_preference": "phone", "contact_details": "+" + "9" * 16}, "contact_details"),
    ],
)
def test_invalid_data_has_actionable_field_without_echoing_input(change, field):
    with pytest.raises(RequestValidationError) as error:
        draft(**change).validate(now=NOW, timezone=TIMEZONE)
    assert error.value.field == field
    assert "private" not in str(error.value)


def test_phone_normalization_and_privacy_safe_representations():
    value = draft(contact_preference="phone", contact_details="+999 (000) 00-001")
    result = value.validate(now=NOW, timezone=TIMEZONE)
    assert result.contact_details == "+99900000001"
    for representation in (repr(value), repr(result)):
        assert "+999" not in representation
        assert "слив" not in representation


def test_telegram_contact_needs_no_username_and_discards_unneeded_phone():
    result = draft(contact_details="not-needed-private-value").validate(now=NOW, timezone=TIMEZONE)
    assert result.contact_details is None


def test_custom_catalog_is_supported_without_mutating_defaults():
    result = draft(category="custom", district="demo").validate(
        now=NOW,
        timezone=TIMEZONE,
        categories={"custom": "Тестовая техника"},
        districts={"demo": "Тестовый район"},
    )
    assert result.category == "custom"
    with pytest.raises(RequestValidationError):
        draft(category="custom").validate(now=NOW, timezone=TIMEZONE)


@pytest.mark.parametrize(
    "text",
    [
        "2026-02-30 10:00-12:00",
        "2026-11-17 25:00-26:00",
        "17.11.2026 09:00-12:00",
        "2026-11-17 12:00-09:00",
        "2026-11-17 09:00-09:00",
        "2026-11-17 22:00-01:00",
        "2026-11-15 09:00-12:00",
        "2026-11-16 10:00-12:00",
        "2026-12-17 09:00-12:00",
        "tomorrow morning",
    ],
)
def test_invalid_visit_windows(text):
    with pytest.raises(RequestValidationError) as error:
        parse_visit_window(text, now=NOW, timezone=TIMEZONE)
    assert error.value.field == "visit_window"


def test_visit_horizon_uses_local_calendar_and_includes_day_30():
    value = parse_visit_window("2026-12-16 09:00-12:00", now=NOW, timezone=TIMEZONE)
    assert value.start_at.astimezone(TIMEZONE).date() == NOW.astimezone(
        TIMEZONE
    ).date() + timedelta(days=30)


def test_future_window_later_today_is_allowed():
    assert parse_visit_window("2026-11-16 10:01-11:00", now=NOW, timezone=TIMEZONE).start_at > NOW


def test_naive_clock_is_rejected_instead_of_assuming_machine_timezone():
    with pytest.raises(ValueError, match="timezone-aware"):
        parse_visit_window(
            "2026-11-17 09:00-12:00", now=NOW.replace(tzinfo=None), timezone=TIMEZONE
        )


@pytest.mark.parametrize(
    "text,now",
    [
        ("2026-03-08 02:15-03:15", datetime(2026, 3, 7, tzinfo=UTC)),
        ("2026-11-01 01:15-02:15", datetime(2026, 10, 31, tzinfo=UTC)),
    ],
)
def test_nonexistent_or_ambiguous_local_times_are_rejected(text, now):
    with pytest.raises(RequestValidationError):
        parse_visit_window(text, now=now, timezone=ZoneInfo("America/New_York"))


ALLOWED_CHANGES = {
    (RequestStatus.NEW, RequestStatus.CONTACTED),
    (RequestStatus.NEW, RequestStatus.CLOSED),
    (RequestStatus.CONTACTED, RequestStatus.SCHEDULED),
    (RequestStatus.CONTACTED, RequestStatus.CLOSED),
    (RequestStatus.SCHEDULED, RequestStatus.CLOSED),
}


@pytest.mark.parametrize("current,target", list(product(RequestStatus, repeat=2)))
def test_all_lifecycle_transitions_and_idempotent_repeats(current, target):
    if current == target or (current, target) in ALLOWED_CHANGES:
        assert validate_transition(current.value, target.value) == target
    else:
        with pytest.raises(RequestValidationError):
            validate_transition(current.value, target.value)


@pytest.mark.parametrize("current,target", [("invalid", "new"), ("new", "invalid")])
def test_unknown_statuses_are_rejected(current, target):
    with pytest.raises(RequestValidationError):
        validate_transition(current, target)
