# Implementation plan — Telegram repair request bot

Prepared: 2026-11-14. Source of truth: requirements.md, DEMO-SRS-04 v1.0.
Repository: https://github.com/nexoradev1221/telegram_business_bot

## Current state and delivery window

Planning was completed on 2026-11-14. Implementation began on 2026-11-16; actual progress and evidence are recorded below.
Planned implementation: **14 days, 2026-11-15 through 2026-11-28**, daily at
**10:00 Asia/Vladivostok (UTC+10)**. The implementation window begins November 15; no implementation was performed during planning.
This is a delivery target, not a guarantee of unattended execution or completion.

**Scheduling status: ACTIVE**, created and verified in the app on 2026-11-14.
Automation ID: `implement-telegram-business-bot-14-days`; daily at 10:00 Asia/Vladivostok,
with the final occurrence on 2026-11-28. The task resumes this conversation.
The task instructions enforce the implementation window of November 15–28.
The schedule reference and reusable task prompt are in scheduled-task.md.
Future runs must have workspace write access, working GitHub credentials, and permission to fetch/push.
Today GitHub CLI worked with approved network access; unattended network access must be checked separately.

## Requirements analysis and scope decisions

The product turns Telegram repair inquiries into durable, traceable requests, then lets an
authorized dispatcher update them. The customer experience is Russian; developer documentation is English.
There are three actors: customer, dispatcher (explicit Telegram user-ID allowlist), and local simulator operator.

| Requirement | Planned behavior | Verification |
| --- | --- | --- |
| FR-01 | Russian /start, /help, appliance categories, guided conversation | Handler and simulator transcript checks |
| FR-02 | Category, summary, district, preferred window, contact preference/details, explicit consent | Field, consent, and normalization tests |
| FR-03 | Validate each step; edit/review/cancel; explicit final submission | Invalid input, cancel, review, and duplicate-submit tests |
| FR-04 | Transactional SQLite persistence and unique public reference | AT-01; restart, uniqueness, and concurrency tests |
| FR-05 | Dispatcher notification through a transport adapter; no credentials in output | Fake transport, token redaction, and failure tests |
| FR-06 | Allowlisted dispatcher commands for new/contacted/scheduled/closed | AT-02; unauthorized command and transition tests |
| FR-07 | Reference lookup restricted to the authenticated Telegram owner | AT-03; enumeration and cross-user tests |
| FR-08 | Recoverable validation and transport errors; bounded retries where appropriate | Missing-contact, blocked-chat, rate-limit, timeout tests |
| FR-09 | Local simulator exercises the same application services without token/network | AT-04; automated end-to-end demo |

Use dispatcher commands rather than a separate panel to keep the baseline small.
Production deployment, paid services, payments, CRM/spreadsheet integrations, web admin UI,
and ongoing maintenance are outside scope.

### Assumptions to make explicit in the implementation

- The background mentions names and addresses, but FR-02 requires district rather than a street address.
  Collect only the listed fields; dispatcher follow-up can arrange exact address details.
- Offer Telegram conversation or phone as contact preferences. Phone requires a validated value;
  Telegram contact requires an available customer chat identity. Do not require a public username.
- Consent precedes storing a final request. Keep incomplete drafts ephemeral for this demo;
  explain that restarting loses a draft. Cancellation stores no request.
- Preferred window is a stated preference, not a confirmed booking or availability promise.
  Define the service timezone and accepted future date/window format in configuration and README.
- Use a small configurable Russian category/district list plus a documented fallback where needed.
- Only an allowlisted dispatcher may list requests or change status; chat configuration alone
  does not authorize every member of a dispatcher group.
- Use an explicit transition policy: new -> contacted -> scheduled -> closed, with direct closure
  from new/contacted for cancelled or unserviceable requests; reject unsupported backwards transitions.
  Repeating the current status is idempotent.
- No live token is required for acceptance. Live smoke testing is optional when credentials are supplied;
  never invent or commit credentials or real customer records.

## Proposed technical design

Use a supported Python version, aiogram, SQLite, pytest, and a lightweight linter.
Day 1 verifies current official Python/aiogram/Telegram documentation and records tested versions;
pin dependencies reproducibly rather than guessing versions today.

Suggested layout (to be created during implementation):

```text
src/telegram_business_bot/
  config.py              # validated environment configuration; separate live/simulator modes
  domain.py              # request fields, validation, statuses and transition rules
  services.py            # submit, owner lookup, dispatcher updates
  storage/               # SQLite schema, migrations, repositories and outbox
  telegram/              # aiogram routers, Russian text and conversation state
  transports/            # live Telegram and deterministic fake notifications
  simulator.py           # runnable local demo over shared services
tests/                   # unit, persistence, handler and acceptance tests
examples/                # synthetic sample data and reproducible demo scenarios
docs/screenshots/        # genuine captures of the finished running simulator
```

Persist requests with internal ID, unique public reference, customer Telegram user/chat IDs,
category, problem summary, district, visit preference, contact preference/details, consent
timestamp/version, status, and created/updated timestamps. Store timestamps consistently in UTC.
Keep status history with dispatcher actor and timestamp. Use parameterized SQL and schema migrations.

Use a durable submission idempotency key tied to the authenticated user and reviewed draft.
The database must enforce unique submission keys/references; repeated or concurrent final callbacks
return the original request rather than inserting again. Telegram update de-duplication alone is insufficient.

Insert the request and notification outbox record in one transaction. A notification failure must
not roll back the customer request. Process pending notifications with bounded retries/backoff,
honor retry-after, retain failed deliveries for diagnosis, and keep the reference available to the customer.
Treat outbound delivery as at-least-once: timeouts may leave delivery uncertain, so notification
text includes the stable reference for recognizing duplicates. Do not promise exactly-once Telegram delivery.
Handle blocked chats without crashing or retrying forever. Escape user text in formatted messages;
redact tokens and personal fields from logs and exception output.

## Git and commit workflow

- `main` is the stable integration branch. Use short-lived `chore/`, `feat/`, `fix/`, `test/`,
  and `docs/` branches named for a small deliverable; no long-lived develop branch is needed.
- Bootstrap main with requirements and repository hygiene. Put this plan on `docs/implementation-plan`,
  review its diff, and integrate through a pull request. Each later milestone follows the same approach.
- Start each run by checking status and fetching origin. Never overwrite unrelated work, force-push,
  reset destructively, or commit another person's files. Resume existing automation branches/PRs before
  starting a duplicate. If changes cannot be safely attributed, report the conflict and leave them intact.
- Make several meaningful commits per day when work supports them: for example domain validation,
  its boundary tests, persistence wiring, and an independently identified fix. Aim for 2–5 coherent
  commits on substantive days; correctness and reviewability take priority over a numerical target.
  No empty commits, artificial fragmentation, backdating, or cosmetic churn to inflate activity.
- Use messages such as `feat: validate repair request fields`, `test: reject cross-user lookup`,
  and `fix: retain requests after notification failure`.
- Inspect each staged diff and run the checks relevant to that slice before committing. Push each
  meaningful completed slice to its branch, including safe partial daily progress; keep incomplete
  work in a draft PR. Never publish secrets, local databases, personal data, or logs.
- Open/update a PR with behavior and actual verification. Merge when the milestone acceptance checks
  and available CI pass and the diff has been reviewed; preserve the small commits with a merge commit.
  If branch rules require human review, leave the PR ready and continue independent authorized work.
- At final acceptance, tag `v0.1.0` on the tested main commit and push the tag. Do not deploy production.

## Daily milestones

Each row is a small deliverable with implementation and meaningful tests, not a requirement to wait
until its date to fix a dependency. Work on the earliest unfinished dependency first, respecting the
14-day window. Update the actual progress log after every run; never mark an unchecked row complete.

| Day/date (2026) | Branch suggestion | Deliverable and exit checks | State |
| --- | --- | --- | --- |
| 1 / Nov 15 | chore/project-foundation | Verify official dependency docs; package/CLI skeleton, pinned dependencies, config validation, sample env, lint/test CI; fresh setup and no-token startup checks | Complete on Nov 16; PR #3 |
| 2 / Nov 16 | feat/request-domain | Request fields, Russian categories, consent, contact/window validation, transition policy; valid/invalid boundary tests | Pending |
| 3 / Nov 17 | feat/sqlite-storage | Initial migration, transactions, unique references/idempotency keys, request/history persistence; restart, duplicate and concurrent submission tests | Pending |
| 4 / Nov 18 | feat/russian-guided-form | /start, /help, guided collection and consent; mocked update tests, invalid input recovery | Pending |
| 5 / Nov 19 | feat/review-submit-cancel | Review/edit/cancel/confirm and shared submit service; AT-01 including repeated callbacks, cancellation and durable confirmations | Pending |
| 6 / Nov 20 | feat/dispatcher-notifications | Configured dispatcher transport and transactional outbox; fake sends, crash/restart recovery, bounded retry and token-redaction checks | Pending |
| 7 / Nov 21 | feat/dispatcher-status | Allowlisted list/status commands and persisted history; AT-02 including restart, invalid transitions and unauthorized actors | Pending |
| 8 / Nov 22 | feat/customer-status | Owner-bound reference lookup and generic unavailable response; AT-03 for guessed references, other owners and forged input | Pending |
| 9 / Nov 23 | fix/telegram-failure-handling | Missing contacts, blocked chats, timeouts, rate limits, malformed updates and safe logging; deterministic failure tests | Pending |
| 10 / Nov 24 | feat/offline-simulator | Interactive/scripted simulator and synthetic dataset through shared services; AT-04 submission, dispatcher notification, closure without token/network | Pending |
| 11 / Nov 25 | test/acceptance-suite | Automated AT-01–04, persistence and concurrency regression suite; establish all acceptance checks passing | Pending |
| 12 / Nov 26 | docs/demo-and-screenshots | Concise English README, Russian usage examples, setup/test/sample config, genuine running demo screenshots; reproduce in clean environment | Pending |
| 13 / Nov 27 | fix/release-readiness | Resolve observed defects, check privacy/config defaults and dependency reproducibility; fresh-install full suite and offline demo | Pending |
| 14 / Nov 28 | chore/release-v0.1.0 | Verify FR/AT matrix and all deliverables, integrate passing PRs, tag tested release, record evidence and remaining limitations; end scheduled work | Pending |

## Verification and release gate

- AT-01: complete a form, confirm twice (including concurrent callbacks), verify one database record
  and the same reference; verify cancellation leaves zero final records.
- AT-02: dispatcher changes status, restart storage, and verify customer status/history reflects it;
  a non-dispatcher cannot perform the update.
- AT-03: customer B uses customer A's real reference and receives no record or sensitive fields;
  test missing/guessed references with the same outward unavailable response.
- AT-04: unset the token, deny live transport/network in the test, run the synthetic scenario,
  and show persisted creation, dispatcher notification, and closure/status lookup.
- CI runs relevant lint and automated tests on PRs and main. Capture actual commands/results in
  PRs and progress notes. No live API calls or secrets in CI; optional live smoke tests are labeled separately.
- Final clean installation must reproduce the documented demo and full suite. Deliver source,
  dependency lock/pins, sample config/data, README, genuine screenshots, and acceptance evidence.
  No screenshot placeholders or fabricated test results.

## Daily run protocol and stop conditions

1. Read requirements.md, plan.md, scheduled-task.md, applicable AGENTS.md, Git status, open PRs,
   and the progress log. Check local date in Asia/Vladivostok before editing.
2. Before Nov 15, make no implementation changes. After Nov 28, or after verified completion,
   make no new implementation changes; report final state and disable the task if a supported tool allows it.
3. Select today's milestone or the earliest unfinished prerequisite. Complete a bounded, reviewable
   slice, validate it, commit, and push. Do not rush unfinished features to satisfy the calendar.
4. Review CI/PR state, merge only passing reviewed work, and record branch, commit SHAs,
   tests, PR URL, blockers, next step, and whether each commit was successfully pushed.
5. If auth/network/permissions block a push, preserve local commits, report the exact failure, and
   continue only independent safe local work. Never count a failed push as publication.
6. If a run was missed, resume from durable progress rather than reimplementing completed work;
   record schedule risk. Do not extend beyond the end date without the user's instruction.

## Progress log

| Date | Work and verification | Blockers / next step |
| --- | --- | --- |
| 2026-11-14 | Read all requirements; created public GitHub repository; prepared analysis, 14-day plan and schedule prompt. No application code implemented. | Local app schedule cannot be created with this session's tools. Activate it manually with scheduled-task.md; implementation starts Nov 15. |
| 2026-11-14 | Subsequently created the daily app task using newly available app tools; verified ACTIVE status and saved recurrence through Nov 28, attached to this conversation. | Earlier scheduling blocker resolved. Implementation starts Nov 15 at 10:00 Asia/Vladivostok; unattended GitHub permissions remain subject to runtime policy. |

| 2026-11-16 | Foundation catch-up: Python 3.12.10 package, aiogram 3.32.0 and fully pinned dependencies, validated config/sample env, Russian CLI configuration check, Linux/Windows CI. Commits `81d9133`, `6c875e8` pushed to `chore/project-foundation`; PR https://github.com/nexoradev1221/telegram_business_bot/pull/3. Local lint passes, 20 tests pass, no-token smoke check passes; wheel/sdist build passes. Documented setup reproduced in a second clean environment with 20 passing tests. Fixed real cp950 Russian-output failure with subprocess regression. | No Nov 15 implementation was found in Git history; resumed earliest prerequisite. CI and PR integration are checked before merge. Next: Nov 16 request-domain milestone. AT-01–04 remain unimplemented. |
