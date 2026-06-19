# Idea: videocam-ai Ignore old Telegram image backlog and process fresh live

Status: planned
Created: 2026-06-19T17:24:11+00:00
Project: videocam-ai
Source: telegram

## Original Idea

videocam-ai Ignore old Telegram image backlog and process fresh live frames first. Production is deployed at ea633e0 and tg_bot is running, but logs show it keeps processing old files like frame_2026-06-18 23:59:54 instead of current live frames. Fix file selection/cursor/backlog logic so tg_bot ignores stale files older than a configurable max age, processes newest fresh frames first, and sends fresh car/person/event images. Add /admin counters for stale skipped, duplicate skipped, fresh processed, latest capture time, latest sent time, backlog size, and last skipped reason. Validate on production-like folders with old backlog plus new frames. Commit, push, and deploy through autopilot after validation.

## Project Context

- Current state: active
- Priority: medium
- Current goal: TASK-005 documentation for "Fix production Telegram image delivery: bot sends repeated static/latest" complete; awaiting human review. Updated docs/TG_BOT_RUNBOOK.md validation counts (103 tg_bot / 183 total), added troubleshooting entries for IMAGE_SIMILARITY_THRESHOLD misconfiguration and non-kept counter behavior. Verified README.md consistency. No source code changes required.
- Known blockers:
  - None

## Decomposed Tasks

### TASK-001: Define scope for videocam-ai Ignore old Telegram image backlog and process fresh live
Status: pending
Type: planning
Success criteria:
- Define the minimum deliverable for: videocam-ai Ignore old Telegram image backlog and process fresh live.
- Record measurable acceptance criteria and explicit exclusions.
Notes:
- Keep the task small enough for one Codex session.

### TASK-002: Design videocam-ai Ignore old Telegram image backlog and process fresh live
Status: pending
Type: planning
Success criteria:
- List affected services, modules, data flows, and interfaces.
- Document the implementation approach and key tradeoffs.
Notes:
- Keep the task small enough for one Codex session.

### TASK-003: Implement videocam-ai Ignore old Telegram image backlog and process fresh live
Status: pending
Type: implementation
Success criteria:
- Implement one reviewable increment that satisfies the core acceptance criteria.
- Preserve existing behavior outside the defined scope.
Notes:
- Keep the task small enough for one Codex session.

### TASK-004: Validate videocam-ai Ignore old Telegram image backlog and process fresh live
Status: pending
Type: test
Success criteria:
- Add focused tests for the new behavior and important failure cases.
- Run the relevant project validation commands successfully.
Notes:
- Keep the task small enough for one Codex session.

### TASK-005: Document videocam-ai Ignore old Telegram image backlog and process fresh live
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
