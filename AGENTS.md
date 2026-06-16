# AGENTS.md

## Project Purpose

Build and maintain small camera/image-processing workflows. The current
reviewed increment is a deterministic local-folder snapshot triage pipeline for
one camera image directory.

## Codex Workflow

- Always read `docs/PROJECT_MANAGER.yaml` first.
- Read `docs/PROJECT_STATUS_MEMORY.md` and `docs/NEXT_ACTIONS.md` before editing.
- Keep changes scoped and preserve existing behavior unless the task requires otherwise.
- Run relevant tests before committing when possible.
- For the snapshot triage pipeline, use the local development environment:
  `python3 -m venv .venv`, `.venv/bin/python -m pip install -r requirements-dev.txt`,
  then `.venv/bin/python -m unittest -v tests/test_snapshot_triage.py`.
- Record completed work in `docs/DEVELOPMENT_LOG.md`.
- Update `docs/NEXT_ACTIONS.md` after changes.
- Keep `docs/PROJECT_MANAGER.yaml` synchronized with current project state.
- Commit completed, validated work with a clear message.

## Snapshot Triage Guardrails

- Preserve the approved scope: local folder input only, no real-time stream, no
  object detection, no cloud/API/database, no source-image deletion, and no
  multi-camera orchestration.
- Keep output deterministic: stable input ordering, stable CSV schema, and stable
  duplicate group assignment.
- Do not commit `.venv`, generated `output/` content, rejected image copies,
  bytecode, or local sample data.

This repository is registered as `videocam-ai` in AI Project Manager.
