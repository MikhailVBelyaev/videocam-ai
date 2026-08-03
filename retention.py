#!/usr/bin/env python3
"""Independent retention for videocam-ai output.

Deletes per-camera date folders older than KEEP_DAYS calendar days.

Why this exists separately from tg_bot/bot.py: cleanup used to run only at the
end of the Telegram sender iteration, so a dead bot (or a stuck sender lock)
silently stopped deletion while the grabbers kept writing ~8 GB/day. This runs
on its own timer and does not import the bot or need Telegram.

Safety: the newest date folder of a camera is never deleted, so a camera that
stopped producing does not end up with its last footage removed.
"""

import argparse
import os
import re
import shutil
import sys
from datetime import date, timedelta

OUTPUT_DIR = os.environ.get(
    "VIDEOCAM_OUTPUT_DIR", "/home/user/Projects/videocam-ai/output"
)
KEEP_DAYS = int(os.environ.get("VIDEOCAM_KEEP_DAYS", "2"))

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _is_date_str(name):
    return bool(DATE_RE.match(name))


def _cameras():
    try:
        return sorted(
            e for e in os.listdir(OUTPUT_DIR)
            if os.path.isdir(os.path.join(OUTPUT_DIR, e))
            and not e.startswith(".")
            and not _is_date_str(e)
        )
    except OSError as e:
        print(f"cannot read {OUTPUT_DIR}: {e}", file=sys.stderr)
        return []


def _dates_for(camera):
    base = os.path.join(OUTPUT_DIR, camera)
    try:
        return sorted(
            e for e in os.listdir(base)
            if os.path.isdir(os.path.join(base, e)) and _is_date_str(e)
        )
    except OSError:
        return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    cutoff = date.today() - timedelta(days=KEEP_DAYS - 1)
    freed = 0
    for camera in _cameras():
        dates = _dates_for(camera)
        if not dates:
            continue
        newest = dates[-1]
        for d in dates:
            if d == newest:
                continue
            try:
                if date.fromisoformat(d) >= cutoff:
                    continue
            except ValueError:
                continue
            full = os.path.join(OUTPUT_DIR, camera, d)
            size = sum(
                os.path.getsize(os.path.join(root, f))
                for root, _, files in os.walk(full)
                for f in files
                if os.path.exists(os.path.join(root, f))
            )
            if args.dry_run:
                print(f"WOULD DELETE {full} ({size / 2**30:.2f} GiB)")
            else:
                try:
                    shutil.rmtree(full)
                    print(f"deleted {full} ({size / 2**30:.2f} GiB)")
                except OSError as e:
                    print(f"failed to delete {full}: {e}", file=sys.stderr)
                    continue
            freed += size

    print(
        f"keep_days={KEEP_DAYS} cutoff={cutoff} "
        f"{'would free' if args.dry_run else 'freed'}={freed / 2**30:.2f} GiB"
    )


if __name__ == "__main__":
    main()
