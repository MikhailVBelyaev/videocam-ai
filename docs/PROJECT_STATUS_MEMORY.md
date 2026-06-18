# Project Status Memory

Last updated: 2026-06-18

## Purpose

just scan it, and prepare for agent's work

## Latest Update

- TASK-001 scope was defined for the camera snapshot quality triage increment.
- Scope now includes a minimum deliverable, measurable acceptance criteria, and explicit exclusions.
- TASK-003 implementation of Phase A (object detection and statistics) is complete
  and in `review_required`. Added MobileNet-SSD object detection via OpenCV DNN,
  car/person counting in CSV and JSON, missing-expected-object flagging, and
  graceful fallback when model files are missing.
- TASK-004 QA validation and implementation is in `review_required`.
- TASK-005 documentation increment is in `review_required`.
- Object detection/object statistics are now implemented for the snapshot triage
  pipeline via optional `--detect-objects` CLI flag.
- Phase B (enhanced quality metrics: contrast score, overexposure score, updated
  quality rank formula) remains documented in the TASK-002 design doc and is
  pending a future implementation increment.
- Local validation environment is documented in `requirements-dev.txt` and uses
  `opencv-python-headless` plus `numpy<2.0`.
- Human approved publishing the reviewed snapshot triage package to GitHub.

## Start Here

Read `AGENTS.md`, `docs/PROJECT_MANAGER.yaml`, and `docs/NEXT_ACTIONS.md` before editing.
