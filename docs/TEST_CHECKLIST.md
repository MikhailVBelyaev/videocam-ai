# Test Checklist

- [x] Identify the project's test command (`python3 -m unittest -v tests/test_snapshot_triage.py`; broader: `python3 -m unittest discover -s tests -v`).
- [x] Install local validation dependencies from `requirements-dev.txt` into ignored `.venv`.
- [x] Run focused tests before committing: `.venv/bin/python -m unittest -v tests/test_snapshot_triage.py`.
- [x] Run broader test discovery: `.venv/bin/python -m unittest discover -s tests -v`.
- [x] Compile changed Python files: `.venv/bin/python -m py_compile cams_grabber/snapshot_triage.py tests/test_snapshot_triage.py`.
