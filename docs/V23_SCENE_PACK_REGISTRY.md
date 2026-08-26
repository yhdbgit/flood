# V23 Regional Scene Pack Registry

## Purpose

Stage 3 groups reusable regional digital-twin assets by Scene Pack. All three Stage 2 demo fields resolve to `OSONG-MIHO-SCENE-PACK-V23`, so they can share the same terrain, regional context, shelter assets, coordinate origin, and future scenario layers.

## Verified V22 source assets

The first Scene Pack records and verifies:

- `blender/osong_visual_v22.blend`
- `output/visual_v22/osong_visual_v22_60s.mp4`
- V21 terrain context and V19 shelter manifest
- EPSG:32652 local-coordinate origin
- 12 km regional bounds and 1.5 km high-detail core
- existing shelter and water-level station references

The registered byte sizes and SHA-256 values are checked against local files.

## Important reuse boundary

The V22 `.blend` is a valid source scene for deriving V23 layers. The V22 reference MP4 is **not** a clean common base because it already contains the fixed pilot field and flood animation in its RGB frames.

Stage 7 has advanced the Scene Pack to:

```text
status = event_time_composition_ready
```

The layer-separated common blend, 60-second common background MP4, multi-field personalization blend, three field overlays, three camera profiles, five lossless RGBA flood segments, three field-specific clean backgrounds, and the shelter overlay are now `ready`. V22 remains unchanged. Trigger-time personalization uses cached media only and does not render the Blender 3D scene.

## Camera coverage

The V22 source camera remains as lineage only. Stage 5 adds one ready field-focused camera profile for each of demo fields 001, 002, and 003; all three still share the same regional Scene Pack and shelter assets.

## Commands

Inspect and verify the first Scene Pack:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 agents/v23_scene_pack_registry.py --verify-assets
```

Run tests:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_v23_scene_pack_registry -v
```
