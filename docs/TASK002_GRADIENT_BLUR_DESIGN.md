# TASK-002 Design: Secondary Gradient-Based Blur Metric

Last updated: 2026-06-17
Status: review_required
Job ID: 2026-06-17_111901_videocam-ai-production-image-quality-problem-many-images-are-task-002
Project: videocam-ai
Parent scope: `docs/PRODUCTION_IMAGE_QUALITY_SCOPE.md` (TASK-001)

## Purpose

Design the increment that adds a second blur signal to the snapshot triage
pipeline so that blurry production images currently passing the Laplacian gate
are caught by an independent metric.

## Affected Services, Modules, and Interfaces

### 1. `cams_grabber/snapshot_triage.py` (single affected file)

Three areas of change within this file:

**a) New function: `_compute_gradient_score(image_bgr: np.ndarray) -> float`**
- Input: BGR image as loaded by `cv2.imread`.
- Output: scalar gradient magnitude variance (same scale convention as
  `_compute_blur_score`).
- Implementation: Sobel X + Sobel Y on the grayscale image, compute per-pixel
  gradient magnitude `sqrt(Gx^2 + Gy^2)`, return variance of that magnitude.
- Dependency: OpenCV `cv2.Sobel` (already available), NumPy `sqrt` (already
  available).

**b) Decision logic in `run_triage()`**
- Current: single blur gate `if blur_score < config.blur_threshold`.
- New: composite gate — reject if **either** metric is below its threshold.
  ```
  if blur_score < config.blur_threshold or gradient_score < config.gradient_threshold:
      decision = "reject"
      reason = "blur"
  ```
- The existing Laplacian remains the primary signal; the gradient metric is a
  second independent gate. Both share the `reason = "blur"` label to keep
  downstream consumer logic stable.

**c) CSV schema extension**
- Add `gradient_score` column after `blur_score`.
- New column order:
  `filename, decision, reason, blur_score, gradient_score, brightness_score, duplicate_group`
- Append-at-end preserves backward compatibility for consumers that use
  positional index 0-4.

**d) `TriageConfig` dataclass**
- Add field: `gradient_threshold: float = 300.0` (default TBD from fixture
  calibration).

**e) CLI argument**
- Add `--gradient-threshold` with default matching the config default.

### 2. `tests/test_snapshot_triage.py`

- Existing test `test_triage_outputs_expected_decisions_and_is_deterministic`
  will need its CSV schema assertion updated to include `gradient_score`.
- New focused test: synthetic Gaussian-blurred image is rejected by at least
  one metric (blur or gradient) at default thresholds.
- New focused test: sharp checkerboard passes both metrics.
- The gradient score values for the four existing fixtures will be recorded
  once computed, so tests can assert deterministic values.

### 3. `docs/SNAPSHOT_TRIAGE_RUNBOOK.md`

- Add `gradient_score` to CSV columns section.
- Add `--gradient-threshold` to CLI arguments and tuning guidance.
- Update validation status after tests pass.

### 4. No other modules affected

- `cams_grabber/main_ssh.py` — untouched (separate RTSP/YOLO pipeline).
- `docs/PROJECT_MANAGER.yaml`, `docs/NEXT_ACTIONS.md`, `docs/DEVELOPMENT_LOG.md`
  — updated for project tracking, not functional changes.

## Data Flow

```
input_dir
  │
  ▼
_sorted_image_paths()  ← sorted list of .jpg/.jpeg/.png
  │
  ▼
for each image:
  cv2.imread()
  │
  ├── _compute_blur_score()       → laplacian_variance
  ├── _compute_gradient_score()   → sobel_magnitude_variance   [NEW]
  ├── _compute_brightness_score() → mean_grayscale
  │
  ▼
composite blur decision:
  reject if laplacian < blur_threshold OR sobel < gradient_threshold
  else if brightness < brightness_threshold → reject low_light
  else → check duplicate → keep or reject duplicate
  │
  ▼
copy to rejected/ if rejected
append row to CSV (now 7 columns)
  │
  ▼
write triage_report.csv
print summary
```

## Implementation Approach

### Step 1: Add `_compute_gradient_score()`

```python
def _compute_gradient_score(image_bgr: np.ndarray) -> float:
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    gx = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)
    magnitude = np.sqrt(gx**2 + gy**2)
    return float(magnitude.var())
```

### Step 2: Update `TriageConfig` and CLI

Add `gradient_threshold: float` field and `--gradient-threshold` argument.

### Step 3: Update composite blur decision

Replace the single Laplacian check with OR logic on both scores.

### Step 4: Update CSV writer

Add `gradient_score` to DictWriter fieldnames and to each row dict.

### Step 5: Update existing test

Update CSV schema assertion from 6 to 7 columns.

### Step 6: Add new tests

Gradient metric behavior and composite decision tests.

### Step 7: Update runbook

Document new column, threshold, and tuning guidance.

## Key Tradeoffs

### Sobel Variance vs Tenengrad vs Alternative Metrics

| Metric               | Pros                                 | Cons                                       |
|----------------------|--------------------------------------|--------------------------------------------|
| Sobel variance (chosen) | Simple, fast, well-understood, OpenCV-native | May correlate with Laplacian on simple scenes |
| Tenengrad            | Standardized blur metric in literature | Nearly equivalent to Sobel in practice    |
| Wavelet-based        | More robust to certain blur types    | Requires scipy; adds dependency            |
| DCT-based            | Good for compression artifacts       | More complex, slower                       |

**Decision:** Sobel variance. It is the smallest change, uses existing deps,
and provides an independent (though correlated) signal. If it proves
insufficient on real production samples, a follow-up job can swap in a more
sophisticated metric.

### Composite Logic: OR vs AND vs Weighted

| Strategy           | Behavior                              | Risk                                         |
|--------------------|---------------------------------------|----------------------------------------------|
| OR (chosen)        | Reject if either metric fails         | May reject borderline images the Laplacian kept |
| AND                | Reject only if both fail              | Too lenient; defeats the purpose of a 2nd gate |
| Weighted composite | Single combined score                 | Harder to tune; obscures which signal fired  |

**Decision:** OR logic. The goal is to catch *more* blurry images, not fewer.
Both metrics share `reason = "blur"` so downstream consumers see the same
rejection category.

### Default Threshold Calibration

The gradient threshold default cannot be calibrated against real production
data (not available in the repo). Instead:
1. Run `_compute_gradient_score()` on the four existing test fixtures.
2. Choose a default between the blurred image's score and the sharp image's
   score.
3. Document that production tuning will likely be needed once real samples
   are available.

**Risk:** The synthetic fixtures (checkerboard, Gaussian blur) may not
represent the blur characteristics of real camera snapshots (motion blur,
defocus, compression artifacts). Mitigation: document this explicitly and
recommend a follow-up tuning job.

### CSV Schema Change

Adding a column changes the output schema. Potential impact on downstream
consumers:
- Consumers using column names (DictReader) — no breakage.
- Consumers using positional indices — column 4 changes from
  `brightness_score` to `gradient_score`.
- Mitigation: document the change clearly; the new column is appended in a
  logical position after `blur_score`.

## Risks and Blockers

1. **Metric correlation**: Sobel and Laplacian are both edge-based; on the
   current synthetic fixtures they may produce highly correlated scores. If
   the gradient score does not catch additional blurry images beyond Laplacian,
   the increment provides no production value. Acceptance criterion only
   requires that *at least one* metric rejects the blurred fixture, so the
   increment still passes tests even in this case.

2. **Threshold tuning**: Default threshold derived from synthetic fixtures may
   not transfer to real camera images. A follow-up job with production samples
   will be needed for calibration.

3. **No real production samples available**: All validation is against
   synthetic images. Real-world blur patterns (motion blur, defocus, JPEG
   compression) may behave differently.

## Validation Plan

- Run existing test suite (updated for 7-column schema).
- New test: Gaussian-blurred image rejected by at least one metric.
- New test: Sharp checkerboard passes both metrics.
- Determinism: repeated runs produce identical CSV.
- Compile check: `py_compile` on modified files.

## Files to Change (Implementation Phase)

| File | Change Type |
|------|-------------|
| `cams_grabber/snapshot_triage.py` | Add function, update config, decision, CSV, CLI |
| `tests/test_snapshot_triage.py` | Update schema assertion, add gradient tests |
| `docs/SNAPSHOT_TRIAGE_RUNBOOK.md` | Document new column and threshold |
