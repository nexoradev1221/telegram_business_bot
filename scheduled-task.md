# Daily implementation task — ready to configure

**Status: NOT SCHEDULED.** This file documents configuration; it does not register a task.

In the desktop app's **Scheduled** view, create one project-scoped task with these settings:

- Title: Implement Telegram business bot — 14-day plan
- Project: `D:\Portfolio\telegram_business_bot`
- Execution: local project, one run at a time; do not start concurrent runs for this repository
- Timezone: `Asia/Vladivostok`
- Start: `2026-11-15 10:00` (UTC+10)
- Repeat: daily at 10:00, last run `2026-11-28 10:00`
- Recurrence, if the advanced control supports it:
  `RRULE:FREQ=DAILY;BYHOUR=10;BYMINUTE=0;BYSECOND=0;UNTIL=20261128T000000Z`
- Set the first run explicitly; the recurrence alone does not establish the start date.
- If no end-date control is available, keep the prompt's date guard and disable the task after Nov 28.
- Keep the computer on, the desktop app running, and this project available.
- Check the task's actual saved timezone/next run, project, prompt, and active status after saving.
  Verify that its unattended permissions allow the required GitHub network operations. Do not
  broaden permissions beyond the project and necessary Git/GitHub operations.

Official guidance: https://learn.chatgpt.com/docs/automations?surface=app

## Task prompt

```text
Work in D:\Portfolio\telegram_business_bot on the repository
https://github.com/nexoradev1221/telegram_business_bot.

First read requirements.md, plan.md, scheduled-task.md, all applicable AGENTS.md instructions,
the progress log, git status, and relevant remote branches/PRs. Use Asia/Vladivostok for dates.
Do not implement before 2026-11-15 or after 2026-11-28. If all deliverables are verified complete,
report completion and disable this scheduled task if a supported scheduling tool is available;
otherwise request that the user disable it. Do not add work just to generate commits.

Implement the scheduled milestone in plan.md, starting with its earliest unfinished prerequisite.
The user has authorized daily implementation during this window, meaningful commits and pushes,
and integration of completed passing work. Today’s planning-only instruction does not prohibit
these future scheduled implementation runs. Stay within the baseline requirements.

Use main plus short-lived chore/feat/fix/test/docs branches and pull requests. Inspect status and
fetch first. Resume existing automation work rather than duplicating it. Preserve unrelated changes;
do not force-push, reset destructively, or commit other people's work. Make frequent meaningful
commits for coherent features, small tasks, and test fixes, and push each completed slice. Aim for
2–5 useful commits on substantive days where appropriate, without quotas, empty commits or churn.

Run the checks appropriate to each change. Review staged diffs, exclude secrets/private data and
local runtime files, and keep the Russian customer wording and English documentation required
by the brief. Keep the token-free simulator and acceptance tests AT-01 through AT-04 central.
Verify current official dependency/API documentation when implementing the integration.

Open/update a PR with actual test evidence. Merge only reviewed passing work when repository
rules allow it, preserving meaningful commits. Leave incomplete work on its branch/draft PR.
If mandatory human review blocks merging, report it and continue safe independent work.

After each run, update plan.md with actual progress, checks/results, commit SHAs, push status,
PR URL, blockers and next steps; commit and push that update. Do not claim success for failed
checks or pushes. Preserve local commits if network/authentication fails and report the exact blocker.
If another run or user edit conflicts, stop dependent edits and report the conflict.

On the final day verify all final deliverables, run clean-install acceptance checks and the offline
demo, and tag/push v0.1.0 only when the release gate passes. Do not deploy production or extend
the schedule without user instructions. Finish each run with a concise, accurate progress report.
```
