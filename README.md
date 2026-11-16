# Telegram Business Bot

Standalone Russian-language appliance repair request bot. **Under construction:** configuration
validation, request-domain rules and package foundation are available. Guided requests, storage, live polling and the
end-to-end simulator are scheduled in [plan.md](plan.md); they do not work yet.

## Setup (Windows PowerShell)

Use 64-bit Python 3.12 (tested with 3.12.10). Dependencies are pinned in requirements-dev.txt.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pip install --no-build-isolation --no-deps -e .
.\.venv\Scripts\python.exe -m telegram_business_bot --check-config
```

The default simulator configuration needs no token and makes no network calls or database writes.
This command checks configuration only; it is not the final simulator. See .env.example for
available variables: the file is a reference, not automatically loaded. Set variables with
`$env:BOT_MODE = 'simulator'`. Live configuration requires a private BOT_TOKEN, one nonzero
DISPATCHER_CHAT_ID, and comma-separated positive DISPATCHER_USER_IDS. Configuration checks do
not validate credentials with Telegram. Never commit credentials, customer records or local databases.

## Checks

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m build --no-isolation
```

CI runs on Python 3.12 on Ubuntu and Windows. No bot token or paid service is required.
All real customer-facing messages are Russian; developer documentation is English.
Production hosting and integrations beyond the baseline are outside scope.

## Design references

Reviewed November 16, 2026: [aiogram 3.32 documentation](https://docs.aiogram.dev/en/latest/),
[Python virtual environments](https://docs.python.org/3.12/library/venv.html), and
[Telegram Bot API](https://core.telegram.org/bots/api). The pinned aiogram version is verified
by installation; baseline handlers will use only the required supported API methods.

## Request rules (domain layer implemented; conversation integration pending)

Categories and districts have Russian demo labels and an `other` fallback. They are fictional
service-area defaults; adapters can supply an alternate catalog to request validation. Do not
promise service availability from these labels. Collect requests in a private Telegram chat
using authenticated sender IDs, never a customer-supplied owner ID.

A request needs explicit consent, a 5–1000 character problem summary, and either Telegram chat
contact (no public username required) or an international phone number beginning with `+` and
8–15 digits. Phone validation checks format only, not ownership, carrier or country-code validity.
The Telegram option discards unneeded phone details. Domain representations omit personal fields.

Visit preference format: `YYYY-MM-DD HH:MM-HH:MM`, in SERVICE_TIMEZONE (default
Asia/Vladivostok), with the end later than the start on the same day. The start must be in the
future and within the next 30 local calendar days, inclusive. Ambiguous/nonexistent DST times
are rejected. A preference is not a confirmed appointment. Consent timestamp and version are
prepared only on explicit validation of the final draft; database persistence comes next.

Lifecycle: new -> contacted -> scheduled -> closed, with direct closure also allowed from new
or contacted. Repeating the current status is harmless; backwards transitions/reopening are
rejected. Dispatcher authentication and persistence will be added in later milestones.
