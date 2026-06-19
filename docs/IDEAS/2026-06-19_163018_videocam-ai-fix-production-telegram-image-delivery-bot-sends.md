# Idea: videocam-ai Fix production Telegram image delivery: bot sends repeated static/latest

Status: planned
Created: 2026-06-19T16:30:18+00:00
Project: videocam-ai
Source: telegram

## Original Idea

videocam-ai Fix production Telegram image delivery: bot sends repeated static/latest frames and misses real street events. Analyze live capture, output folders, Telegram sender, backlog processing, freshness checks, and triage/statistics integration. Required result: Telegram should send only fresh important images when cars/people/motion/object changes happen, avoid repeated near-identical parked-car frames, detect stale camera/output, create/use triage_report and summary JSON, show clear /admin status with latest event time, queue length, sent/skipped counts, duplicate/static-frame counts, and exact reason when no image is sent. Do not delete source images. Commit, push, and deploy through autopilot when validation passes.

## Project Context

- Current state: active
- Priority: medium
- Current goal: TASK-005 documentation for "Fix remaining Telegram image backlog problem" complete; awaiting human review. Updated docs/TG_BOT_RUNBOOK.md validation counts to 76 tg_bot tests / 156 total tests. Verified README.md consistency. Updated docs/PROJECT_STATUS_MEMORY.md, docs/NEXT_ACTIONS.md, docs/DEVELOPMENT_LOG.md, and docs/PROJECT_MANAGER.yaml. All 156 tests pass. py_compile clean.
- Known blockers:
  - None

## Decomposed Tasks

### TASK-001: Define scope for videocam-ai Fix production Telegram image delivery: bot sends repeated static/latest
Status: pending
Type: planning
Success criteria:
- Define the minimum deliverable for: videocam-ai Fix production Telegram image delivery: bot sends repeated static/latest.
- Record measurable acceptance criteria and explicit exclusions.
Notes:
- Keep the task small enough for one Codex session.

### TASK-002: Design videocam-ai Fix production Telegram image delivery: bot sends repeated static/latest
Status: pending
Type: planning
Success criteria:
- List affected services, modules, data flows, and interfaces.
- Document the implementation approach and key tradeoffs.
Notes:
- Keep the task small enough for one Codex session.

### TASK-003: Implement videocam-ai Fix production Telegram image delivery: bot sends repeated static/latest
Status: pending
Type: implementation
Success criteria:
- Implement one reviewable increment that satisfies the core acceptance criteria.
- Preserve existing behavior outside the defined scope.
Notes:
- Keep the task small enough for one Codex session.

### TASK-004: Validate videocam-ai Fix production Telegram image delivery: bot sends repeated static/latest
Status: pending
Type: test
Success criteria:
- Add focused tests for the new behavior and important failure cases.
- Run the relevant project validation commands successfully.
Notes:
- Keep the task small enough for one Codex session.

### TASK-005: Document videocam-ai Fix production Telegram image delivery: bot sends repeated static/latest
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
