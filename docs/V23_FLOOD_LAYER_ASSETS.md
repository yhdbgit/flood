# V23 Stage 6 Reusable Flood-Layer Assets

## Goal

Stage 6 converts the separated `V23_FLOOD_RGBA` view layer into lossless, transparent, pre-rendered assets. A trigger-time request selects cached clips; it does not launch Blender or render the 3D scene again.

## Why the flood layer is segmented

Flood geometry is shared by a regional Scene Pack, but the pixels produced by that geometry depend on the active camera. Frames 241–719 use a different field-focus camera for each registered field. The field camera reaches the common camera keyframe at frame 720, so frame 641 is not a safe reuse boundary.

The exact cache layout is:

| Segment | Frames | Camera | Reuse |
|---|---:|---|---|
| `shared_overview_flood` | 1–240 | regional source camera | shared once |
| `field_001_focus_flood` | 241–719 | field 001 camera | field 001 only |
| `field_002_focus_flood` | 241–719 | field 002 camera | field 002 only |
| `field_003_focus_flood` | 241–719 | field 003 camera | field 003 only |
| `shared_shelter_hold` | 720–960 | regional source camera | shared once |

This renders 1,918 frames instead of three complete 960-frame sequences. At request time, one 960-frame sequence is reconstructed from the shared opening, one requested field segment, and the shared ending.

## Media contract

- Resolution: 1280×720
- Frame rate: 16 FPS
- Container: QuickTime MOV
- Codec: QTRLE
- Colour mode: RGBA
- Alpha mode after Blender decode: straight alpha
- Audio: none
- Background: transparent

QTRLE is used because the final H.264 MP4 cannot retain the alpha channel required to place water over a matching background segment. The generated MOV files remain in `output/flood_assets/v23/clips/` and are intentionally ignored by Git. Their hashes, sizes, frame counts, and selection rules are recorded in the tracked manifest.

## Runtime selection

```text
trusted trigger event
        ↓ field_id + scenario_id
FloodAssetCatalog.select(...)
        ↓
shared opening + selected field segment + shared ending
        ↓
later composition stage
```

For example, field 002 resolves:

```text
shared_overview_flood
field_002_focus_flood
shared_shelter_hold
```

No Blender render is permitted in this selection path.

## Validation result

- Five MOV files rendered successfully.
- Total rendered frames: 1,918.
- Total Blender render time: 376.008 seconds.
- All files reopen in Blender as 1280×720, four-channel, straight-alpha movies.
- Every decoded frame count matches the planned frame count.
- Reviewed transparent PNG proof frames cover all five segments, including maximum flood frame 600 for all three fields.

The caution flood extent is visible in the field-001 focus camera at frame 600. It is not visible in the field-002 or field-003 focus cameras. This is retained as a data-bound result: downstream scripts must not claim those two fields are flooded under this scenario.

## Files

- Render plan: `data/v23/flood_assets/flood_render_plan_v23.json`
- Final manifest: `data/v23/flood_assets/flood_assets_manifest_v23.json`
- Blender movie audit: `data/v23/flood_assets/flood_movie_audit_v23.json`
- Planner: `agents/v23_flood_asset_preparer.py`
- Runtime selector: `agents/v23_flood_asset_catalog.py`
- Blender renderer: `blender/render_osong_flood_assets_v23.py`
- Blender decoder audit: `blender/audit_osong_flood_assets_v23.py`
- Validator/registrar: `scripts/validate_v23_flood_assets.py`

## Stage 7 integration

Stage 7 now combines these flood RGBA clips with field-specific clean backgrounds, the selected field overlay, the shared shelter overlay, and the common background. A complete personalized MP4 is produced without rendering the Blender 3D scene; Blender VSE is used only as the cached-media encoder.
