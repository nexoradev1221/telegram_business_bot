import asyncio
import sqlite3
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from telegram_business_bot.storage import SQLiteRepository
from telegram_business_bot.telegram_form import Form, build_form_router


class FakeState:
    def __init__(self, data=None):
        self.data = data or {}
        self.current = None

    async def clear(self):
        self.data.clear()
        self.current = None

    async def update_data(self, **values):
        self.data.update(values)

    async def get_data(self):
        return self.data.copy()

    async def set_state(self, state):
        self.current = state


class FakeMessage:
    def __init__(self, text="", *, user_id=101, chat_type="private"):
        self.text = text
        self.from_user = type("User", (), {"id": user_id})()
        self.chat = type("Chat", (), {"id": user_id, "type": chat_type})()
        self.answers = []

    async def answer(self, text, **kwargs):
        self.answers.append(text)


def handlers_for(repository, timezone):
    router = build_form_router(repository, timezone)
    return {handler.callback.__name__: handler.callback for handler in router.message.handlers}


def test_summary_rejects_short_input_and_keeps_form_state():
    async def scenario():
        handlers = handlers_for(SQLiteRepository("unused.sqlite3"), ZoneInfo("Asia/Vladivostok"))
        state = FakeState({"category": "washer"})
        state.current = Form.summary
        message = FakeMessage("bad")
        await handlers["summary_handler"](message, state)
        assert state.current == Form.summary
        assert "от 5 до 1000" in message.answers[0]

    asyncio.run(scenario())


def test_consent_saves_valid_request_and_returns_reference(tmp_path):
    async def scenario():
        timezone = ZoneInfo("Asia/Vladivostok")
        repository = SQLiteRepository(tmp_path / "requests.sqlite3")
        repository.initialize()
        handlers = handlers_for(repository, timezone)
        day = (datetime.now(UTC).astimezone(timezone) + timedelta(days=1)).date()
        state = FakeState(
            {
                "category": "washer",
                "problem_summary": "Не работает слив воды",
                "district": "central",
                "visit_window": f"{day:%Y-%m-%d} 09:00-12:00",
                "contact_preference": "telegram",
                "contact_details": None,
                "submission_key": "form-test-submission-0001",
            }
        )
        message = FakeMessage("/consent_yes")
        await handlers["consent_handler"](message, state)
        assert len(message.answers) == 1
        assert "TB-" in message.answers[0]
        reference = message.answers[0].split()[-1].rstrip(".")
        assert repository.get_for_customer(reference, 101) is not None

    asyncio.run(scenario())


def test_cancel_clears_draft_without_storage(tmp_path):
    async def scenario():
        repository = SQLiteRepository(tmp_path / "requests.sqlite3")
        repository.initialize()
        handlers = handlers_for(repository, ZoneInfo("Asia/Vladivostok"))
        state = FakeState({"category": "washer", "submission_key": "draft-key-not-used"})
        message = FakeMessage("/cancel")
        await handlers["cancel_handler"](message, state)
        assert state.data == {}
        assert message.answers == ["Черновик отменён. Заявка не сохранена."]
        with sqlite3.connect(tmp_path / "requests.sqlite3") as connection:
            assert connection.execute("SELECT count(*) FROM requests").fetchone()[0] == 0

    asyncio.run(scenario())
