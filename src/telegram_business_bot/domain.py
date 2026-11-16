"""Pure request validation and lifecycle rules shared by Telegram and the simulator."""

import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from types import MappingProxyType
from zoneinfo import ZoneInfo

CATEGORIES: Mapping[str, str] = MappingProxyType(
    {
        "fridge": "Холодильник",
        "washer": "Стиральная машина",
        "dishwasher": "Посудомоечная машина",
        "stove": "Плита или духовка",
        "other": "Другая техника",
    }
)
DISTRICTS: Mapping[str, str] = MappingProxyType(
    {
        "central": "Центральный район",
        "north": "Северный район",
        "south": "Южный район",
        "other": "Другой район (уточнит диспетчер)",
    }
)
CONSENT_VERSION = "repair-request-v1"
MAX_VISIT_DAYS = 30
MAX_TELEGRAM_ID = (1 << 52) - 1


class RequestValidationError(ValueError):
    """Russian field error containing no submitted personal data."""

    def __init__(self, field: str, message: str):
        self.field = field
        super().__init__(message)


class RequestStatus(StrEnum):
    NEW = "new"
    CONTACTED = "contacted"
    SCHEDULED = "scheduled"
    CLOSED = "closed"


STATUS_LABELS: Mapping[RequestStatus, str] = MappingProxyType(
    {
        RequestStatus.NEW: "Новая",
        RequestStatus.CONTACTED: "Связались с клиентом",
        RequestStatus.SCHEDULED: "Визит согласован",
        RequestStatus.CLOSED: "Закрыта",
    }
)
_TRANSITIONS = {
    RequestStatus.NEW: frozenset({RequestStatus.CONTACTED, RequestStatus.CLOSED}),
    RequestStatus.CONTACTED: frozenset({RequestStatus.SCHEDULED, RequestStatus.CLOSED}),
    RequestStatus.SCHEDULED: frozenset({RequestStatus.CLOSED}),
    RequestStatus.CLOSED: frozenset(),
}


def validate_transition(current: str, target: str) -> RequestStatus:
    try:
        before, after = RequestStatus(current), RequestStatus(target)
    except (ValueError, TypeError):
        raise RequestValidationError("status", "Неизвестный статус заявки.") from None
    if before != after and after not in _TRANSITIONS[before]:
        raise RequestValidationError("status", "Такое изменение статуса недопустимо.")
    return after


def _text(value: str, field: str, label: str, minimum: int, maximum: int) -> str:
    if not isinstance(value, str) or len(value) > 4000:
        raise RequestValidationError(field, f"{label}: недопустимое значение.")
    if any(unicodedata.category(char).startswith("C") and char not in "\n\r\t" for char in value):
        raise RequestValidationError(field, f"{label}: недопустимые символы.")
    normalized = " ".join(value.split())
    if not minimum <= len(normalized) <= maximum:
        raise RequestValidationError(field, f"{label}: нужно от {minimum} до {maximum} символов.")
    return normalized


def _identity(value: int, field: str) -> int:
    if type(value) is not int or not 0 < value <= MAX_TELEGRAM_ID:
        raise RequestValidationError(field, "Не удалось определить пользователя Telegram.")
    return value


def _localize(value: datetime, timezone: ZoneInfo) -> datetime:
    candidates = [value.replace(tzinfo=timezone, fold=fold) for fold in (0, 1)]
    valid = [
        item
        for item in candidates
        if item.astimezone(UTC).astimezone(timezone).replace(tzinfo=None) == value
    ]
    if not valid or len({item.utcoffset() for item in valid}) > 1:
        raise RequestValidationError("visit_window", "Выберите время без перехода часового пояса.")
    return valid[0].astimezone(UTC)


@dataclass(frozen=True)
class VisitWindow:
    start_at: datetime
    end_at: datetime


def parse_visit_window(value: str, *, now: datetime, timezone: ZoneInfo) -> VisitWindow:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    text = _text(value, "visit_window", "Время визита", 22, 22)
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}-[0-9]{2}:[0-9]{2}", text):
        raise RequestValidationError("visit_window", "Формат: ГГГГ-ММ-ДД ЧЧ:ММ-ЧЧ:ММ.")
    try:
        day, hours = text.split(" ")
        start_text, end_text = hours.split("-")
        start = datetime.fromisoformat(f"{day}T{start_text}")
        end = datetime.fromisoformat(f"{day}T{end_text}")
    except ValueError:
        raise RequestValidationError("visit_window", "Укажите существующие дату и время.") from None
    start_utc, end_utc = _localize(start, timezone), _localize(end, timezone)
    if end_utc <= start_utc:
        raise RequestValidationError(
            "visit_window", "Конец окна должен быть позже начала в тот же день."
        )
    local_today = now.astimezone(timezone).date()
    if start_utc <= now or start.date() > local_today + timedelta(days=MAX_VISIT_DAYS):
        raise RequestValidationError("visit_window", "Выберите будущее время в ближайшие 30 дней.")
    return VisitWindow(start_utc, end_utc)


@dataclass(frozen=True, repr=False)
class ValidatedRequest:
    customer_user_id: int
    customer_chat_id: int
    category: str
    problem_summary: str
    district: str
    visit_window: VisitWindow
    contact_preference: str
    contact_details: str | None
    consent_at: datetime
    consent_version: str = CONSENT_VERSION


@dataclass(frozen=True, repr=False)
class RequestDraft:
    customer_user_id: int
    customer_chat_id: int
    category: str
    problem_summary: str
    district: str
    visit_window: str
    contact_preference: str
    contact_details: str | None
    consent: bool

    def validate(
        self,
        *,
        now: datetime,
        timezone: ZoneInfo,
        categories: Mapping[str, str] = CATEGORIES,
        districts: Mapping[str, str] = DISTRICTS,
    ) -> ValidatedRequest:
        if self.consent is not True:
            raise RequestValidationError(
                "consent", "Для отправки нужно согласие на обработку данных."
            )
        user_id = _identity(self.customer_user_id, "customer_user_id")
        chat_id = _identity(self.customer_chat_id, "customer_chat_id")
        # Customer collection is private-chat-only; handlers must supply authenticated sender IDs.
        if user_id != chat_id:
            raise RequestValidationError(
                "customer_chat_id", "Отправьте заявку в личном чате с ботом."
            )
        category = _text(self.category, "category", "Категория", 1, 64)
        district = _text(self.district, "district", "Район", 1, 64)
        if category not in categories:
            raise RequestValidationError("category", "Выберите категорию из списка.")
        if district not in districts:
            raise RequestValidationError("district", "Выберите район из списка.")
        summary = _text(self.problem_summary, "problem_summary", "Описание проблемы", 5, 1000)
        window = parse_visit_window(self.visit_window, now=now, timezone=timezone)
        preference = _text(self.contact_preference, "contact_preference", "Способ связи", 1, 16)
        if preference not in {"telegram", "phone"}:
            raise RequestValidationError("contact_preference", "Выберите Telegram или телефон.")
        contact = None
        if preference == "phone":
            raw = _text(self.contact_details, "contact_details", "Телефон", 8, 40)
            contact = re.sub(r"[ ()-]", "", raw)
            if not re.fullmatch(r"\+[1-9][0-9]{7,14}", contact):
                raise RequestValidationError("contact_details", "Нужен телефон с + и кодом страны.")
        return ValidatedRequest(
            user_id,
            chat_id,
            category,
            summary,
            district,
            window,
            preference,
            contact,
            now.astimezone(UTC),
        )
