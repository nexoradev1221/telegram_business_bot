# Telegram Business Bot

Russian-language Telegram request flow for a home-appliance repair team, backed by SQLite.
The local demo uses synthetic data and needs no bot token or network access.

## Setup

Use 64-bit Python 3.12 (tested with 3.12.10). From Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pip install --no-build-isolation --no-deps -e .
```

`.env.example` lists configuration names but is not loaded automatically. Set values in the shell
or your private process environment. Never commit a real token, customer record, or database.

## Run the offline demonstration

```powershell
.\.venv\Scripts\python.exe -m telegram_business_bot --demo
```

The demo loads `sample_request.json`, creates a synthetic request in a temporary SQLite database,
processes the real notification outbox through a console transport, closes the request as a
synthetic dispatcher, and checks the customer-owned status history. It does not use BOT_TOKEN or
DISPATCHER_CHAT_ID, make network calls, or leave a database behind.

## Run the live bot

Set `BOT_MODE=live`, `BOT_TOKEN`, `DISPATCHER_CHAT_ID`, and `DISPATCHER_USER_IDS` in the process
environment, then run:

```powershell
.\.venv\Scripts\python.exe -m telegram_business_bot
```

The bot collects requests in private chats, asks explicit consent, lets customers review/edit or
cancel, saves each confirmed request transactionally, and notifies the configured dispatcher. The
dispatcher must first start the bot or otherwise make its chat reachable. Configure the service
timezone with `SERVICE_TIMEZONE` (default `Asia/Vladivostok`) and database file with `DATABASE_PATH`
(default `data/requests.sqlite3`). `--check-config` validates settings without connecting to Telegram;
it does not prove that the token or dispatcher chat works.

## Tests and build

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\python.exe -m ruff format --check src tests
.\.venv\Scripts\python.exe -m build --no-isolation
```

CI tests Python 3.12 on Ubuntu and Windows. Tests use synthetic records and fake notification
transports; they do not call Telegram. The simulator demonstrates persistence, notification
formatting, status changes and owner-bound history.

## Scope and limitations

- Customer messages are in Russian; developer documentation is in English.
- Customer drafts use aiogram in-memory FSM storage and are lost if the live bot restarts mid-form.
- Dispatcher notifications use bounded retries. Delivery is at-least-once: if a send succeeds but
  the process stops before recording success, the same reference can be notified again.
- Dispatcher list/status commands and customer reference lookup are not implemented yet.
- The offline simulator demonstrates shared services; it is not a Telegram UI recording.
- This is a demonstration, not a production deployment. No real customer data, hosting or live
  Telegram credentials are included.

## Design references

The implementation pins aiogram 3.32.0. API choices were checked against the official
[aiogram 3.32 documentation](https://docs.aiogram.dev/en/v3.32.0/) and
[Telegram Bot API](https://core.telegram.org/bots/api). See [requirements.md](requirements.md) for
the baseline scope and [plan.md](plan.md) for dated implementation evidence.
