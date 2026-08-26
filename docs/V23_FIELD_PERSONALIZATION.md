# V23 Stage 5 Field Personalization

## Goal

Generate reusable field overlays and camera profiles automatically from registered field polygons. One regional Scene Pack stores multiple field assets, but output enables only the field requested by the trusted trigger event.

## Registration-time flow

```text
field registry polygon
  -> EPSG:4326 to Scene Pack local metres
  -> size-aware border and camera parameters
  -> terrain-conforming fill, boundary, and label
  -> field-specific RGBA/composite view layers
  -> reusable camera profile
  -> ready asset binding in the field registry
```

The current demonstration prepares three fields in one derived scene:

- `OSONG-FIELD-DEMO-001`
- `OSONG-FIELD-DEMO-002`
- `OSONG-FIELD-DEMO-003`

Each field has its own collection, transparent overlay view layer, composite review layer, camera object, target object, and camera profile ID. Camera distance, height, lens, and boundary width are derived from the registered polygon dimensions rather than hard-coded to one pilot field.

## Trigger-time contract

The trigger event supplies `field_id`. The resolver checks ownership and obtains the registered `camera_profile_id`. Later composition must enable exactly that field's view layer and must not render the other registered fields.

No full Blender render is allowed at trigger time. These objects and camera profiles are prepared when the field is registered or when the regional Scene Pack is built. A later stage may pre-render reusable per-field camera segments.

## Outputs

- `data/v23/field_assets/field_asset_plan_v23.json`
- `blender/osong_personalization_v23.blend`
- `data/v23/field_assets/field_assets_manifest_v23.json`
- `output/field_assets/v23/previews/*.png`

The preview set contains a focus composite, a close composite, and a transparent RGBA overlay for each field. Validation checks file hashes, alpha coverage, and that each field remains inside the frame.

## Commands

```bash
PYTHONDONTWRITEBYTECODE=1 python3 agents/v23_field_asset_preparer.py

/Applications/Blender.app/Contents/MacOS/Blender \
  -b blender/osong_common_v23.blend \
  --python blender/build_osong_field_assets_v23.py

/Applications/Blender.app/Contents/MacOS/Blender \
  -b blender/osong_personalization_v23.blend \
  --python blender/render_osong_field_assets_v23_previews.py

PYTHONDONTWRITEBYTECODE=1 python3 scripts/validate_v23_field_assets.py
```

## Known limits

- The demonstration boundaries are OSM farmland polygons, not cadastral ownership parcels.
- The overlays identify the selected field; they do not calculate flood damage.
- Fields 002 and 003 use the lower-detail regional background because they are outside the current 1.5 km high-detail core.
- Stage 7 now supplies matching field-specific clean backgrounds and cached-media event-time composition. The selected field is resolved from the trusted event and only its registered overlay and camera background are used.
