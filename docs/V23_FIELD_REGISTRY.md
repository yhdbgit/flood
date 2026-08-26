# V23 Registered Field Registry

## Purpose

Stage 2 resolves the `field_id` received in a trusted trigger event into a registered polygon and its reusable asset bindings. Field geometry is stored once in the registry rather than copied into every trigger event.

## Demo records

`data/v23/fields/field_registry_v23.json` contains three distinct OSM `landuse=farmland` polygons in the Osong/Miho regional context. They share the reserved V23 Scene Pack and the Osong-eup Welfare Center shelter reference, but each has a different `field_id`, owner, geometry, centre, area, and distance to the shelter.

These are land-cover examples for multi-user workflow testing. They are not cadastral ownership parcels and must be replaced by boundaries registered by real users before production use.

## Ownership protection

`FieldRegistry.resolve_event()` performs both checks:

1. Validate the V23 upstream event contract.
2. Confirm that `event.user_id` owns `event.field_id`.

This prevents a trigger event for one user from rendering another user's registered field.

## Deferred asset state

All three fields currently have:

```text
scene_pack_id = OSONG-MIHO-SCENE-PACK-V23
camera_profile_id = null
preparation_status = pending
```

Stage 3 will create and validate the Scene Pack registry. Camera assignment and registration-time media preparation remain later V23 stages.

## Commands

Resolve a field:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 agents/v23_field_registry.py OSONG-FIELD-DEMO-001
```

Run tests:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_v23_field_registry -v
```
