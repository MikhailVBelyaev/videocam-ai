# Idea: videocam-ai Fix tg_bot still stuck on old LAST_SENT_FOLDER after fresh-first

Status: planned
Created: 2026-06-19T19:03:32+00:00
Project: videocam-ai
Source: telegram

## Original Idea

videocam-ai Fix tg_bot still stuck on old LAST_SENT_FOLDER after fresh-first deploy. Product server has fresh files in output/2026-06-19, but output/.last_sent_file points to 2026-06-18 and bot.py still selects LAST_SENT_FOLDER when it exists. Change logic so if last-sent folder is stale or not the newest folder, tg_bot moves to newest fresh folder and processes newest fresh frames first. Add tests for .last_sent_file pointing to old date while new folder has fresh images. /admin must show current watched folder, last_sent_file, newest output folder, and whether bot is stuck or fresh. Commit, push, deploy.

## Project Context

- Current state: active
- Priority: medium
- Current goal: TASK-005 documentation for "Ignore old Telegram image backlog and process fresh live" complete; in review_required. Updated docs/TG_BOT_RUNBOOK.md validation counts to 124 tg_bot tests / 204 total tests. Added troubleshooting entry for os.path.getmtime OSError fail-open behavior. Verified README.md Telegram bot section consistency with tg_bot/bot.py implementation. Updated docs/PROJECT_STATUS_MEMORY.md, docs/NEXT_ACTIONS.md, docs/DEVELOPMENT_LOG.md, and docs/PROJECT_MANAGER.yaml. No source code changes. All 204 tests pass (124 tg_bot + 52 snapshot_triage + 28 web_viewer); py_compile clean.
- Known blockers:
  - None

## Decomposed Tasks

### TASK-001: Define scope for videocam-ai Fix tg_bot still stuck on old LAST_SENT_FOLDER after fresh-first
Status: pending
Type: planning
Success criteria:
- Define the minimum deliverable for: videocam-ai Fix tg_bot still stuck on old LAST_SENT_FOLDER after fresh-first.
- Record measurable acceptance criteria and explicit exclusions.
Notes:
- Keep the task small enough for one Codex session.

### TASK-002: Design videocam-ai Fix tg_bot still stuck on old LAST_SENT_FOLDER after fresh-first
Status: pending
Type: planning
Success criteria:
- List affected services, modules, data flows, and interfaces.
- Document the implementation approach and key tradeoffs.
Notes:
- Keep the task small enough for one Codex session.

### TASK-003: Implement videocam-ai Fix tg_bot still stuck on old LAST_SENT_FOLDER after fresh-first
Status: pending
Type: implementation
Success criteria:
- Implement one reviewable increment that satisfies the core acceptance criteria.
- Preserve existing behavior outside the defined scope.
Notes:
- Keep the task small enough for one Codex session.

### TASK-004: Validate videocam-ai Fix tg_bot still stuck on old LAST_SENT_FOLDER after fresh-first
Status: pending
Type: test
Success criteria:
- Add focused tests for the new behavior and important failure cases.
- Run the relevant project validation commands successfully.
Notes:
- Keep the task small enough for one Codex session.

### TASK-005: Document videocam-ai Fix tg_bot still stuck on old LAST_SENT_FOLDER after fresh-first
Status: pending
Type: documentation
Success criteria:
- Document the implemented behavior, configuration, and operating steps.
- Update project status and next actions after verification.
Notes:
- Keep the task small enough for one Codex session.

## Risks

- Scope may expand beyond one reviewable implementation increment.
- Existing project blockers or hardware dependencies may delay validation.

## Dependencies

- Access to the affected project files and required runtime environment.
- Agreement on acceptance criteria before implementation begins.

## Suggested Next Action

Complete TASK-001 by confirming the minimum scope and measurable acceptance criteria.
