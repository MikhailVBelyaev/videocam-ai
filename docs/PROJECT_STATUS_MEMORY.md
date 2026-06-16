# Project Status Memory

Last updated: 2026-06-16

## Purpose

just scan it, and prepare for agent's work

## Latest Update

- TASK-001 scope was defined for the camera snapshot quality triage increment.
- Scope now includes a minimum deliverable, measurable acceptance criteria, and explicit exclusions.
- TASK-003 implementation increment was completed and moved to `review_required`.
- Added deterministic local-folder triage CLI, focused tests, and runbook documentation.
- TASK-004 validation increment was completed and moved to `review_required`.
- Validation now explicitly covers blur rejection, low-light rejection, duplicate grouping determinism, keep/reject decisions, CSV schema, rejected-copy behavior, and deterministic reruns.
- TASK-005 documentation closeout package was prepared and moved to `review_required`.
- Documentation now includes end-to-end run steps, default/custom thresholds, output contract, tuning guidance, validation status, and limitations.
- Local validation environment is documented in `requirements-dev.txt` and uses
  `opencv-python-headless` plus `numpy<2.0`.
- Human approved publishing the reviewed snapshot triage package to GitHub.

## Start Here

Read `AGENTS.md`, `docs/PROJECT_MANAGER.yaml`, and `docs/NEXT_ACTIONS.md` before editing.
