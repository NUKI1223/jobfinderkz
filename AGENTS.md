# JobFinderKZ: durable context

At the beginning of every new session or after context compaction, read:
1. `docs/WORKLOG.md` — authoritative current state, actions, decisions, test results and next steps.
2. `docs/IMPLEMENTATION_PLAN.md` — user requirements.
3. `docs/PROGRESS.md` — milestone status and startup conditions.

The user explicitly requires all code changes and actions to be recorded for future sessions.
- After each meaningful implementation/checkpoint, update `docs/WORKLOG.md` with actions, outcomes, limitations and next steps.
- Run `node scripts/snapshot.mjs` after changes. It writes full current source to `docs/CODE_SNAPSHOT.md` and appends complete changed-file versions to `docs/CODE_CHANGES.md`.
- Do not put `.env`, API keys, user uploads, account passwords, private data or raw personal logs into these documents.
- Source files remain authoritative for editing. The snapshots are for context recovery, not substitutes for tests.
- Never claim that mocked tests verify live provider behavior. Track real and fixed-response integration checks separately.
- Use PostgreSQL database `jobfinder_test` for destructive test fixtures. Never run them against `jobfinder`.
- Development is local only. Do not publish, email, send applications, or spend beyond configured budgets.
- No subagents unless the user explicitly requests them.
