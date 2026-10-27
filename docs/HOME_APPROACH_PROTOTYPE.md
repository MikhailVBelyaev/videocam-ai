# Home-Approach Notification Prototype

## Owner outcome

Retain the current raw camera archive and its date-folder retention, but send a
Telegram notification only when a supported object enters the owner-calibrated
forecourt. Road traffic remains available for local statistics and review.

## Calibration

The initial polygon is the home-side area bounded by the red line supplied by
the owner on 2026-10-27. It is stored in normalised coordinates in
`cams_grabber/zone_config.default.json`. On the first new capture-container
start it is copied to `output/<camera>/zone_config.json`; future manual/UI
edits must change that persisted file, not the image.

The approach polygon excludes the public road. A separate `exclusion_polygons`
mask has priority for the whole right-hand parking/planter sector; this is
necessary because the parked car's bottom-centre can otherwise be geometrically
inside the red boundary, and night detection boxes can span most of that
sector. Its bottom-centre bounding-box test approximates where an object
touches the ground, which is more stable than a box centre under perspective.

## Data contracts

Existing artefacts are unchanged:

```
output/cam1/YYYY-MM-DD/frame_*.jpg
output/cam1/YYYY-MM-DD/frame_*_debug.jpg
```

New retained artefacts are inside the same dated folder:

```
analytics.jsonl                 # one semantic record for each saved raw capture
events/event_<timestamp>_*.json # atomic Telegram queue item
events/event_<timestamp>_*.jpg  # evidence with polygon + object overlay
```

The retention job already deletes whole dated folders, so it retains and
deletes event evidence on the same two-day policy as the raw archive. The bot
cursor is per camera: `output/<camera>/.last_sent_zone_event`. On first start
it is placed at the newest historical event; no historical event is replayed.

## Detection policy

- Classes recorded in the archive/analytics: person, bicycle, motorcycle, car,
  truck, bus, and the existing animal classes.
- Notification candidates: the same supported classes after existing confidence
  and four-frame persistence gates.
- A candidate becomes an event only after its bottom-centre is inside the
  polygon for four frames.
- The process warms up for 30 seconds after restart, avoiding a boot alert for
  objects already parked in the zone.
- A 45-second nearby class/position cooldown suppresses tracker-ID churn.
- The bot sends only evidence from `events/`, never ordinary `frame_*.jpg`.
- Mute advances the event cursor without delivery; events remain in the local
  dated archive and therefore cannot later cause a delayed notification flood.

## Owner controls in the first version

`/menu` supplies Today, seven-day statistics, mute for one hour, and unmute.
`/stats` returns semantic raw-detection counts and entry-event counts. These
raw counts are detections/saved capture records, not yet a guarantee of unique
road crossings; the current tracker can change IDs. A later statistics phase
should add separately calibrated road counting lines and tracklet merging.

## Acceptance checks before production activation

1. The red owner boundary matches `zone_config.json` on an annotated live
   frame in both day and IR night modes.
2. A vehicle travelling only along the road writes no event JSON and produces
   no Telegram delivery.
3. A vehicle/person crossing into the forecourt writes exactly one JSON + one
   evidence image and produces exactly one Telegram photo.
4. The parked vehicle at startup produces no event during the 30-second warmup.
5. `/stats` class counts increase while existing raw images remain browseable
   through `/raw` for the normal retention window.
6. Mute creates no Telegram delivery and does not replay its suppressed events
   after unmute.
