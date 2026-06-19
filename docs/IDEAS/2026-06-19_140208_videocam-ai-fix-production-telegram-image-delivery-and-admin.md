# Idea: videocam-ai Fix production Telegram image delivery and admin statistics

Status: planned
Created: 2026-06-19T14:02:08+00:00
Project: videocam-ai
Source: telegram

## Original Idea

videocam-ai Fix production Telegram image delivery and admin statistics. Current production captures images, but Telegram bot mostly skips frames as too similar and sometimes image_sender_job overlaps with maximum running instances reached. Make Hermes investigate and fix safely: ensure fresh images are sent to Telegram, prevent old backlog loops, avoid overlapping sender jobs, keep duplicate filtering reasonable, make /admin show real latest image/statistics from production output, validate on oldgamepc, deploy only after QA, and report concise result.

## Project Context

- Current state: active
- Priority: medium
- Current goal: TASK-005 documentation for "Change /admin: add web server page with cars and" (Job ID 2026-06-19_060847) complete; awaiting human review. Created docs/WEB_VIEWER_RUNBOOK.md; updated README.md and project status docs. All 28 web_viewer tests pass; all 127 tests pass. TASK-004 QA, TASK-003 implementation, TASK-002 design, and TASK-001 scope for web admin page remain in review_required.
- Known blockers:
  - None

## Decomposed Tasks

### TASK-001: Define scope for videocam-ai Fix production Telegram image delivery and admin statistics
Status: pending
Type: planning
Success criteria:
- Define the minimum deliverable for: videocam-ai Fix production Telegram image delivery and admin statistics.
- Record measurable acceptance criteria and explicit exclusions.
Notes:
- Keep the task small enough for one Codex session.

### TASK-002: Design videocam-ai Fix production Telegram image delivery and admin statistics
Status: pending
Type: planning
Success criteria:
- List affected services, modules, data flows, and interfaces.
- Document the implementation approach and key tradeoffs.
Notes:
- Keep the task small enough for one Codex session.

### TASK-003: Implement videocam-ai Fix production Telegram image delivery and admin statistics
Status: pending
Type: implementation
Success criteria:
- Implement one reviewable increment that satisfies the core acceptance criteria.
- Preserve existing behavior outside the defined scope.
Notes:
- Keep the task small enough for one Codex session.

### TASK-004: Validate videocam-ai Fix production Telegram image delivery and admin statistics
Status: pending
Type: test
Success criteria:
- Add focused tests for the new behavior and important failure cases.
- Run the relevant project validation commands successfully.
Notes:
- Keep the task small enough for one Codex session.

### TASK-005: Document videocam-ai Fix production Telegram image delivery and admin statistics
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
