"""Russian customer request conversation for aiogram 3."""

from datetime import UTC, datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup, ReplyKeyboardRemove

from telegram_business_bot.domain import CATEGORIES, DISTRICTS, RequestDraft, RequestValidationError
from telegram_business_bot.storage import SQLiteRepository, StorageError


class Form(StatesGroup):
    category = State()
    summary = State()
    district = State()
    visit_window = State()
    contact = State()
    phone = State()
    review = State()
    consent = State()


def _keyboard(*labels: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=label)] for label in labels],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def build_form_router(repository: SQLiteRepository, timezone: ZoneInfo) -> Router:
    """Build handlers around an initialized repository; drafts remain memory-only."""
    router = Router(name="customer-request-form")
    categories = {label: key for key, label in CATEGORIES.items()}
    districts = {label: key for key, label in DISTRICTS.items()}

    @router.message(Command("help"))
    async def help_handler(message: Message) -> None:
        await message.answer(
            "Я помогу оформить заявку на ремонт техники. Используйте /start, чтобы начать. "
            "Черновик хранится только до перезапуска бота."
        )

    @router.message(CommandStart())
    async def start_handler(message: Message, state: FSMContext) -> None:
        if message.chat.type != "private" or message.from_user is None:
            await message.answer("Заявку можно оформить только в личном чате с ботом.")
            return
        await state.clear()
        await state.update_data(submission_key=uuid4().hex)
        await state.set_state(Form.category)
        await message.answer(
            "Здравствуйте! Выберите технику. Для отмены отправьте /cancel.",
            reply_markup=_keyboard(*CATEGORIES.values()),
        )

    @router.message(Command("cancel"))
    async def cancel_handler(message: Message, state: FSMContext) -> None:
        await state.clear()
        await message.answer(
            "Черновик отменён. Заявка не сохранена.", reply_markup=ReplyKeyboardRemove()
        )

    @router.message(Form.category)
    async def category_handler(message: Message, state: FSMContext) -> None:
        category = categories.get(message.text or "")
        if category is None:
            await message.answer(
                "Выберите категорию кнопкой ниже.", reply_markup=_keyboard(*CATEGORIES.values())
            )
            return
        await state.update_data(category=category)
        await state.set_state(Form.summary)
        await message.answer(
            "Кратко опишите неисправность (от 5 до 1000 символов).",
            reply_markup=ReplyKeyboardRemove(),
        )

    @router.message(Form.summary)
    async def summary_handler(message: Message, state: FSMContext) -> None:
        summary = message.text or ""
        if not 5 <= len(" ".join(summary.split())) <= 1000:
            await message.answer(
                "Описание должно содержать от 5 до 1000 символов. Попробуйте ещё раз."
            )
            return
        await state.update_data(problem_summary=summary)
        await state.set_state(Form.district)
        await message.answer("Выберите район.", reply_markup=_keyboard(*DISTRICTS.values()))

    @router.message(Form.district)
    async def district_handler(message: Message, state: FSMContext) -> None:
        district = districts.get(message.text or "")
        if district is None:
            await message.answer(
                "Выберите район кнопкой ниже.", reply_markup=_keyboard(*DISTRICTS.values())
            )
            return
        await state.update_data(district=district)
        await state.set_state(Form.visit_window)
        await message.answer(
            "Предпочтительное окно визита (местное время): ГГГГ-ММ-ДД ЧЧ:ММ-ЧЧ:ММ. "
            "Например: 2026-11-26 09:00-12:00.",
            reply_markup=ReplyKeyboardRemove(),
        )

    @router.message(Form.visit_window)
    async def visit_handler(message: Message, state: FSMContext) -> None:
        await state.update_data(visit_window=message.text or "")
        await state.set_state(Form.contact)
        await message.answer("Как с вами связаться?", reply_markup=_keyboard("Telegram", "Телефон"))

    @router.message(Form.contact)
    async def contact_handler(message: Message, state: FSMContext) -> None:
        if message.text == "Telegram":
            await state.update_data(contact_preference="telegram", contact_details=None)
            await state.set_state(Form.review)
            await _show_review(message, state)
        elif message.text == "Телефон":
            await state.update_data(contact_preference="phone")
            await state.set_state(Form.phone)
            await message.answer(
                "Введите номер с кодом страны, например +71234567890.",
                reply_markup=ReplyKeyboardRemove(),
            )
        else:
            await message.answer(
                "Выберите Telegram или телефон.", reply_markup=_keyboard("Telegram", "Телефон")
            )

    @router.message(Form.phone)
    async def phone_handler(message: Message, state: FSMContext) -> None:
        await state.update_data(contact_details=message.text or "")
        await state.set_state(Form.review)
        await _show_review(message, state)

    async def _show_review(message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        category_label = CATEGORIES[data["category"]]
        district_label = DISTRICTS[data["district"]]
        contact = data.get("contact_details") or "через Telegram"
        await message.answer(
            "Проверьте заявку:\n"
            f"Техника: {category_label}\nОписание: {data['problem_summary']}\n"
            f"Район: {district_label}\nОкно: {data['visit_window']}\nСвязь: {contact}\n\n"
            "Отправьте /confirm для продолжения или /cancel для отмены.",
            reply_markup=ReplyKeyboardRemove(),
        )

    @router.message(Form.review, Command("confirm"))
    async def confirm_handler(message: Message, state: FSMContext) -> None:
        await state.set_state(Form.consent)
        await message.answer(
            "Согласны на обработку указанных данных для организации ремонта? "
            "Отправьте /consent_yes или /cancel."
        )

    @router.message(Form.consent, Command("consent_yes"))
    async def consent_handler(message: Message, state: FSMContext) -> None:
        if message.from_user is None or message.chat.type != "private":
            await message.answer("Не удалось определить личный чат Telegram.")
            return
        data = await state.get_data()
        draft = RequestDraft(
            customer_user_id=message.from_user.id,
            customer_chat_id=message.chat.id,
            category=data["category"],
            problem_summary=data["problem_summary"],
            district=data["district"],
            visit_window=data["visit_window"],
            contact_preference=data["contact_preference"],
            contact_details=data.get("contact_details"),
            consent=True,
        )
        now = datetime.now(UTC)
        try:
            validated = draft.validate(now=now, timezone=timezone)
            result = repository.submit(validated, data["submission_key"], now=now)
        except RequestValidationError as error:
            if error.field == "visit_window":
                await state.set_state(Form.visit_window)
                await message.answer(f"{error} Введите новое окно: ГГГГ-ММ-ДД ЧЧ:ММ-ЧЧ:ММ.")
            elif error.field == "contact_details":
                await state.set_state(Form.phone)
                await message.answer(f"{error} Введите телефон с кодом страны ещё раз.")
            else:
                await state.clear()
                await message.answer(f"{error} Черновик сброшен. Начните заново командой /start.")
            return
        except StorageError:
            await message.answer(
                "Не удалось сохранить заявку. Черновик сохранён; повторите /consent_yes."
            )
            return
        await state.clear()
        await message.answer(
            f"Заявка принята. Её номер: {result.record.reference}.",
            reply_markup=ReplyKeyboardRemove(),
        )

    return router
