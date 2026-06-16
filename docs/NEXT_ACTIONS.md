# Next Actions

Last updated: 2026-06-16

## Current Priority

Review the published single-camera snapshot triage package and decide whether to
close this increment or create a new follow-up job.

## Approved Scope

- TASK-001 scope was approved by human review on 2026-06-15.
- TASK-002 design package was prepared as baseline contract in `docs/SNAPSHOT_TRIAGE_DESIGN.md`.
- TASK-003 implementation, TASK-004 validation, and TASK-005 documentation
  increments are complete and approved for publish.
- Development validation dependencies are in `requirements-dev.txt`.
- Latest local validation evidence: `.venv/bin/python -m unittest -v tests/test_snapshot_triage.py`,
  `.venv/bin/python -m unittest discover -s tests -v`, and `.venv/bin/python -m py_compile cams_grabber/snapshot_triage.py tests/test_snapshot_triage.py`.
- The existing RTSP/YOLO camera runtime remains separate from the local-folder
  snapshot triage pipeline.
- Preserve TASK-001 exclusions for any follow-up changes: no real-time stream, no object detection, no cloud/API/database, no source-image deletion, no multi-camera orchestration.
