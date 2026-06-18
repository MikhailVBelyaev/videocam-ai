# Production Media Quality and Object Statistics Scope (TASK-001)

Job ID: 2026-06-17_173502_videocam-ai-build-production-media-quality-and-object-statis-task-001
Project: videocam-ai
Status: review_required
Last updated: 2026-06-17

## Problem Statement

Production review of camera snapshots requires automation for classification,
reporting, and review that the current triage pipeline does not fully provide:

1. Human review of kept frames is done image-by-image instead of as a continuous
   video clip, making it slow to spot missing events or long gaps.
2. Aggregate quality statistics are not exported, so trend analysis and threshold
   tuning rely on manual CSV parsing.
3. Kept frames are not copied to a separate directory, forcing reviewers to
   cross-reference the CSV report against the source folder.
4. The original request also asks for object detection, counting cars and people,
   and classifying images as "missing expected object"; those concerns are scoped
   out under current project guardrails.

## Current Baseline

- `cams_grabber/snapshot_triage.py` produces `output/triage_report.csv` and copies
  rejected images to `rejected/`.
- The pipeline already computes `blur_score`, `gradient_score`, and
  `brightness_score` for every image.
- Keep/reject decisions are deterministic, tested, and do not delete source images.
- TASK-003 gradient blur metric implementation is pending human review in the
  working tree.
- A related scope for video/statistics (`docs/PRODUCTION_VIDEO_STATISTICS_SCOPE.md`,
  Job ID 2026-06-17_172653) is also awaiting human review.

## Minimum Deliverable

One reviewable implementation increment, achievable in a single Codex session,
that adds three new local output artifacts without expanding into excluded domains.

Included:
1. **JSON statistics summary** (`output/triage_summary.json`) written after each
   triage run. Contains:
   - `total_images`, `kept_images`, `rejected_by_reason`
   - Score distributions: `min`, `max`, `mean`, `std` for `blur_score`,
     `gradient_score`, and `brightness_score`
   - A `kept_frames` list with `filename` and a composite `quality_rank` score
     so the best frames can be reviewed first.
2. **Optional timelapse video generation** from kept frames
   (`output/kept_timelapse.mp4`) using OpenCV `cv2.VideoWriter`.
   - Controlled by `--generate-video` boolean flag.
   - Frame rate controlled by `--video-fps` (default `5.0`).
   - Video dimensions match the first kept frame; subsequent frames are resized
     if necessary.
3. **Copy kept frames to a separate directory** (`kept/` by default, configurable
   via `--kept-dir`).
   - Only frames with `decision == "keep"` are copied.
   - Copies use `shutil.copy2` to preserve metadata, matching the existing
     rejected-copy behavior.
   - Directory is created if it does not exist.
4. **Focused unit tests** for JSON schema completeness, video generation
   behavior (file exists, correct frame count, only kept frames included), and
   kept-directory copy behavior.
5. **Runbook update** in `docs/SNAPSHOT_TRIAGE_RUNBOOK.md` documenting the new
   outputs, CLI flags, directory layout, and known codec limitations.

## Measurable Acceptance Criteria

- `triage_summary.json` is written to the output directory and contains all
  required top-level keys with valid numeric types.
- When `--generate-video` is passed and at least one image is kept,
  `kept_timelapse.mp4` exists in the output directory and has size > 0 bytes.
- Video frame count equals the number of kept images.
- Video frames follow the same stable filename-sorted order as the CSV report.
- The `kept/` directory contains exactly the frames with `decision == "keep"`
  after a run when `--kept-dir` is provided or defaulted.
- The existing test suite (`tests/test_snapshot_triage.py`) passes without
  modification.
- Repeated runs with identical input and config produce identical `decision`,
  `reason`, `duplicate_group`, `triage_summary.json`, and kept-directory contents.

## Explicit Exclusions

- No object detection or object-presence validation (cars, people, missing
  objects).
- No real-time camera stream processing.
- No cloud/API/database integration.
- No source-image deletion.
- No multi-camera orchestration.
- No production deployment or host-specific configuration.
- No removal of the existing Laplacian or gradient metrics.
- No audio track in generated video.
- No video generation when no frames are kept (graceful skip).

## Assumptions

- OpenCV VideoWriter is available with at least one working fourcc codec
  (`mp4v` as primary fallback, `avc1` as secondary).
- Kept frames may vary in size; the video uses the first kept frame's
  dimensions and resizes later frames if needed.
- JSON output uses the Python standard library `json` module; no new
  dependencies are required.
- Statistics are computed from the same scores already calculated during triage;
  no additional image-processing passes are needed.
- Disk space is sufficient for copies of kept frames.

## Risks

1. **Video codec availability varies by host.** OpenCV may fail to write MP4 on
   headless or minimal environments. Mitigation: document codec fallback strategy
   and test on the target host before relying on video output in production.
2. **Mixed image sizes could cause artifacts.** Resizing frames to the first
   kept frame's dimensions may distort non-matching aspect ratios.
   Mitigation: document the behavior; a future job can add letterboxing or
   fixed-output-size options.
3. **JSON schema change may affect downstream consumers.** Adding a new output
   file is additive and does not break existing CSV consumers, but any tool
   parsing `triage_summary.json` will need to know the schema.
   Mitigation: document the schema explicitly in the runbook.
4. **Scope overlap with pending TASK-003 review.** The new increment touches the
   same source file (`cams_grabber/snapshot_triage.py`). Mitigation: ensure
   TASK-003 is accepted and committed before the video/statistics increment is
   implemented, or rebase the new work on top of the accepted TASK-003 state.
5. **Scope overlap with pending video/statistics scope (Job ID 2026-06-17_172653).**
   That scope defines JSON statistics and video generation but does not include
   the kept-frames directory. If both scopes are approved, the implementation
   should be consolidated into a single increment to avoid redundant work.
