# V23 Trigger Event Contract

## Purpose

V23 consumes a video-generation request only after the team-owned trigger service has decided that an event should be sent. The flood-video service validates the request shape and identity, but it does not recalculate rainfall thresholds, water-level thresholds, cooldowns, or whether a video should be generated.

## Ownership boundary

| Responsibility | Owner |
|---|---|
| Observe forecasts and water levels | Upstream trigger service |
| Apply thresholds and cooldown rules | Upstream trigger service |
| Select `scenario_id` and emit the event | Upstream trigger service |
| Validate the event contract | V23 video service |
| Resolve field assets and produce the personalized MP4 | V23 video service |

Fields such as `should_generate_video`, `rain_threshold_mm`, and `cooldown_hours` are intentionally rejected by the V23 contract.

## Required fields

- `schema_version`: currently `1.0`
- `event_type`: `flood_guidance_requested`
- `event_id`: unique upstream event identity
- `user_id`: owner of the requested guidance
- `field_id`: registered field to personalize
- `scenario_id`: upstream-selected flood scenario identity
- `triggered_at`: decision time with timezone
- `requested_at`: delivery request time with timezone
- `source.system_id`: emitting system identity
- At least one of `forecast_summary` or `hydrology_summary`

Field geometry is not carried in every trigger event. V23 stage 2 will resolve it from the field registry using `field_id`.

## Examples and validation

Valid example:

```text
data/v23/events/valid_forecast_and_hydrology.json
```

Contract validation:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 agents/v23_event_contract.py \
  data/v23/events/valid_forecast_and_hydrology.json
```

Tests:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_v23_event_contract -v
```

## Deferred to later V23 stages

- `field_id` lookup and geometry validation
- Scene Pack and camera profile selection
- scenario asset availability
- event idempotency and output cache lookup
- LangGraph workflow and MP4 production
