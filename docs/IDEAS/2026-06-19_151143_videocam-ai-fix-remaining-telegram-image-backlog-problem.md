# Idea: videocam-ai Fix remaining Telegram image backlog problem

Status: planned
Created: 2026-06-19T15:11:43+00:00
Project: videocam-ai
Source: telegram

## Original Idea

videocam-ai Fix remaining Telegram image backlog problem. Production is on 068948f but tg_bot still loops over old 2026-06-18 images and skips them as too similar. Make sender start from latest date/current fresh images after restart, avoid old backlog draining, keep overlap protection, and verify Telegram receives fresh images after deploy.

## Project Context

- Current state: active
- Priority: medium
- Current goal: TASK-005 documentation for "Fix production Telegram image delivery and admin statistics" complete; awaiting human review. Updated docs/TG_BOT_RUNBOOK.md with sender safeguards, /admin photo behavior, new env vars, and troubleshooting. Verified README.md consistency. Updated project status docs. All 146 tests pass. py_compile clean.
- Known blockers:
  - None

## Decomposed Tasks

### TASK-001: Define scope for videocam-ai Fix remaining Telegram image backlog problem
Status: pending
Type: planning
Success criteria:
- Define the minimum deliverable for: videocam-ai Fix remaining Telegram image backlog problem.
- Record measurable acceptance criteria and explicit exclusions.
Notes:
- Keep the task small enough for one Codex session.

### TASK-002: Design videocam-ai Fix remaining Telegram image backlog problem
Status: pending
Type: planning
Success criteria:
- List affected services, modules, data flows, and interfaces.
- Document the implementation approach and key tradeoffs.
Notes:
- Keep the task small enough for one Codex session.

### TASK-003: Implement videocam-ai Fix remaining Telegram image backlog problem
Status: pending
Type: implementation
Success criteria:
- Implement one reviewable increment that satisfies the core acceptance criteria.
- Preserve existing behavior outside the defined scope.
Notes:
- Keep the task small enough for one Codex session.

### TASK-004: Validate videocam-ai Fix remaining Telegram image backlog problem
Status: pending
Type: test
Success criteria:
- Add focused tests for the new behavior and important failure cases.
- Run the relevant project validation commands successfully.
Notes:
- Keep the task small enough for one Codex session.

### TASK-005: Document videocam-ai Fix remaining Telegram image backlog problem
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
