# V23 Stage 7 Event-Time Personalized Composition

## Goal

Stage 7 produces a personalized 60-second visual MP4 from cached media without re-rendering the Blender 3D scene after a trigger event. The upstream trigger service remains responsible for deciding when to request the video.

## Registration and Scene Pack preparation

The following media is rendered once:

- Three field-camera clean background clips for frames 241–719
- Three selected-field RGBA clips for frames 1–719
- One shared shelter RGBA clip for frames 720–960
- Stage 6 already supplies five reusable flood RGBA segments
- Stage 4 supplies the shared 60-second common background

The three field-camera background clips are required even for field 001. Its generated camera differs from the old fixed pilot camera by up to approximately 2.6 km during the field-focus interval.

## Trigger-time composition

```text
trusted event (field_id + scenario_id)
  -> ownership and field registry resolution
  -> select one field background and one field overlay
  -> select Stage 6 shared opening + field flood + shared ending
  -> add shared common background and shelter overlay
  -> Blender VSE media composition only
  -> personalized 1280x720 H.264 MP4
```

The seven VSE strips are:

1. Full common background, frames 1–960
2. Selected field-camera background replacement, frames 241–719
3. Shared overview flood, frames 1–240
4. Selected field-focus flood, frames 241–719
5. Shared shelter flood, frames 720–960
6. Selected field marker, frames 1–719
7. Shared shelter marker, frames 720–960

The opaque selected-field background replaces the old camera only in the personalized interval. RGBA flood, field, and shelter media are placed above it using alpha-over blending.

## Safety and truth constraints

- The workflow accepts the team-owned trigger result and does not recalculate trigger thresholds.
- The event user must own the requested field.
- Unsupported flood scenarios are rejected rather than substituted.
- Blender 3D scene rendering is forbidden at trigger time.
- A field damage claim is allowed only when the selected scenario visibility contract permits it.

## Main files

- Plan generator: `agents/v23_composition_asset_preparer.py`
- Asset renderer: `blender/render_osong_composition_assets_v23.py`
- Asset validator: `scripts/validate_v23_composition_assets.py`
- Event plan builder: `agents/v23_personalized_visual_builder.py`
- Cached-media compositor: `blender/compose_personalized_visual_v23.py`
- Media audit: `blender/audit_osong_composition_assets_v23.py`
- Final MP4 audit: `blender/audit_personalized_visual_v23.py`

## Verified result

- Seven composition assets passed Blender decoder, frame-count, resolution, size, hash, and alpha checks.
- Total one-time pre-rendered frames: 3,835.
- Example event: `FLOOD-2026-08-27-OSONG-001`.
- Selected field: `OSONG-FIELD-DEMO-001`; scenario: `caution`.
- Final visual: 1280x720, 960 frames, 60 seconds.
- Cached-media composition time: 7.905 seconds.
- Final audit confirms `cached_media_only = true` and `blender_3d_scene_render = false`.

The final LangGraph/TTS/card workflow can consume the resulting personalized visual MP4 in the next stage.
