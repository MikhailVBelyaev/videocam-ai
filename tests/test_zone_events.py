import unittest
from datetime import datetime, timedelta

from cams_grabber.zone_events import ApproachEventGate, point_in_polygon


class ZoneGeometryTests(unittest.TestCase):
    def test_polygon_has_home_and_road_sides(self):
        polygon = ((0, 0.5), (1, 0.5), (1, 1), (0, 1))
        self.assertTrue(point_in_polygon((0.5, 0.75), polygon))
        self.assertFalse(point_in_polygon((0.5, 0.25), polygon))

    def test_entering_after_required_frames_emits_once(self):
        gate = ApproachEventGate(
            polygon=((0, 0.5), (1, 0.5), (1, 1), (0, 1)),
            min_inside_frames=2,
            warmup_seconds=0,
        )
        now = datetime(2026, 10, 27, 10, 0, 0)
        outside = [40, 10, 60, 30]
        inside = [40, 50, 60, 80]
        self.assertIsNone(gate.observe(1, "car", outside, 100, 100, now))
        self.assertIsNone(gate.observe(1, "car", inside, 100, 100, now + timedelta(seconds=1)))
        event = gate.observe(1, "car", inside, 100, 100, now + timedelta(seconds=2))
        self.assertIsNotNone(event)
        self.assertEqual(event.reason, "entered")
        self.assertIsNone(gate.observe(1, "car", inside, 100, 100, now + timedelta(seconds=3)))

    def test_new_object_inside_waits_for_warmup(self):
        gate = ApproachEventGate(
            polygon=((0, 0.5), (1, 0.5), (1, 1), (0, 1)),
            min_inside_frames=2,
            warmup_seconds=10,
        )
        now = datetime(2026, 10, 27, 10, 0, 0)
        inside = [40, 50, 60, 80]
        self.assertIsNone(gate.observe(1, "car", inside, 100, 100, now))
        self.assertIsNone(gate.observe(1, "car", inside, 100, 100, now + timedelta(seconds=1)))
        event = gate.observe(1, "car", inside, 100, 100, now + timedelta(seconds=11))
        self.assertIsNotNone(event)
        self.assertEqual(event.reason, "appeared-inside")

    def test_road_only_and_unsupported_classes_do_not_emit(self):
        gate = ApproachEventGate(
            polygon=((0, 0.5), (1, 0.5), (1, 1), (0, 1)), min_inside_frames=1, warmup_seconds=0
        )
        now = datetime(2026, 10, 27, 10, 0, 0)
        self.assertIsNone(gate.observe(1, "car", [40, 5, 60, 30], 100, 100, now))
        self.assertIsNone(gate.observe(2, "bench", [40, 50, 60, 80], 100, 100, now))

    def test_nearby_reidentified_object_is_suppressed(self):
        gate = ApproachEventGate(
            polygon=((0, 0.5), (1, 0.5), (1, 1), (0, 1)), min_inside_frames=1, warmup_seconds=0
        )
        now = datetime(2026, 10, 27, 10, 0, 0)
        outside = [40, 10, 60, 30]
        inside = [40, 50, 60, 80]
        gate.observe(1, "person", outside, 100, 100, now)
        self.assertIsNotNone(gate.observe(1, "person", inside, 100, 100, now + timedelta(seconds=1)))
        gate.observe(2, "person", outside, 100, 100, now + timedelta(seconds=2))
        self.assertIsNone(gate.observe(2, "person", inside, 100, 100, now + timedelta(seconds=3)))
