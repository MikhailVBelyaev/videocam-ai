"""Geometry and state for low-noise home-approach events.

This module deliberately has no camera, YOLO, Telegram, or filesystem
dependency.  The grabber uses it after a detection has passed its existing
quality/confidence/persistence gates.  Keeping the decision pure makes the
owner's calibrated geometry testable before it is deployed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import hypot


# Coordinates are fractions of the source frame, not pixels.  They trace the
# red owner-marked boundary clockwise, then close along the bottom image edge.
# The interior is the forecourt/home side of that boundary.
DEFAULT_APPROACH_POLYGON = (
    (0.17, 1.00), (0.17, 0.49), (0.24, 0.44), (0.38, 0.40),
    (0.43, 0.38), (0.65, 0.37), (0.67, 0.40), (0.68, 0.47),
    (0.65, 0.51), (0.66, 0.58), (0.70, 0.61), (0.79, 0.62),
    (0.83, 0.67), (0.88, 0.75), (0.94, 0.90), (1.00, 1.00),
)

ALERT_CLASSES = frozenset({
    "person", "bicycle", "motorcycle", "car", "truck", "bus",
    "bird", "cat", "dog", "horse", "sheep", "cow",
})


def point_in_polygon(point: tuple[float, float], polygon) -> bool:
    """Return whether a normalised point is inside a polygon (edge inclusive)."""
    x, y = point
    inside = False
    previous = polygon[-1]
    for current in polygon:
        x1, y1 = current
        x2, y2 = previous
        if ((y1 > y) != (y2 > y)) and (
            x < (x2 - x1) * (y - y1) / (y2 - y1) + x1
        ):
            inside = not inside
        previous = current
    return inside


def ground_point(box: list[float], frame_width: int, frame_height: int) -> tuple[float, float]:
    """Bottom-centre is a better ground-location proxy than a box centre."""
    return ((box[0] + box[2]) / (2 * frame_width), box[3] / frame_height)


@dataclass(frozen=True)
class ZoneEvent:
    tracking_id: int
    class_name: str
    timestamp: datetime
    point: tuple[float, float]
    reason: str


class ApproachEventGate:
    """Emit one event when a stable object enters the calibrated forecourt.

    A new ID that first appears *inside* the polygon is ignored while the
    service warms up.  Once warm, it is admitted as a fallback because a
    tracker can lose an ID at the entrance.  A short spatial/class cooldown
    prevents that ID churn from becoming a notification storm.
    """

    def __init__(
        self,
        polygon=DEFAULT_APPROACH_POLYGON,
        min_inside_frames: int = 4,
        warmup_seconds: float = 30.0,
        nearby_cooldown_seconds: float = 45.0,
        nearby_distance: float = 0.12,
        alert_classes=None,
    ):
        self.polygon = tuple(polygon)
        self.min_inside_frames = min_inside_frames
        self.warmup_seconds = warmup_seconds
        self.nearby_cooldown_seconds = nearby_cooldown_seconds
        self.nearby_distance = nearby_distance
        self.alert_classes = frozenset(alert_classes or ALERT_CLASSES)
        self.started_at: datetime | None = None
        self._tracks: dict[int, dict] = {}
        self._recent: list[ZoneEvent] = []

    def forget(self, tracking_id: int) -> None:
        self._tracks.pop(tracking_id, None)

    def _recently_emitted(self, class_name: str, point, timestamp: datetime) -> bool:
        self._recent = [
            event for event in self._recent
            if (timestamp - event.timestamp).total_seconds() <= self.nearby_cooldown_seconds
        ]
        return any(
            event.class_name == class_name
            and hypot(event.point[0] - point[0], event.point[1] - point[1]) <= self.nearby_distance
            for event in self._recent
        )

    def observe(
        self,
        tracking_id: int,
        class_name: str,
        box: list[float],
        frame_width: int,
        frame_height: int,
        timestamp: datetime,
    ) -> ZoneEvent | None:
        if class_name not in self.alert_classes:
            return None
        if self.started_at is None:
            self.started_at = timestamp

        point = ground_point(box, frame_width, frame_height)
        inside = point_in_polygon(point, self.polygon)
        state = self._tracks.get(tracking_id)
        if state is None:
            self._tracks[tracking_id] = {
                "inside": inside,
                "frames": 1 if inside else 0,
                "emitted": False,
                "new_inside": inside,
            }
            return None

        if not inside:
            state.update(inside=False, frames=0, emitted=False, new_inside=False)
            return None

        if not state["inside"]:
            state.update(inside=True, frames=1, emitted=False, new_inside=False)
            reason = "entered"
        else:
            state["frames"] += 1
            reason = "appeared-inside" if state["new_inside"] else "entered"

        warmed_up = (timestamp - self.started_at).total_seconds() >= self.warmup_seconds
        may_emit = not state["new_inside"] or warmed_up
        if state["emitted"] or not may_emit or state["frames"] < self.min_inside_frames:
            return None
        if self._recently_emitted(class_name, point, timestamp):
            state["emitted"] = True
            return None

        event = ZoneEvent(tracking_id, class_name, timestamp, point, reason)
        state["emitted"] = True
        self._recent.append(event)
        return event
