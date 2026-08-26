# V23 Stage 4 Layer Separation

## Goal

Derive a reusable V23 scene from the approved V22 source without changing V22. The new scene separates expensive regional background rendering from event-specific flood water and user-specific field or shelter markers.

## Blender layers

- `V23_COMMON_BACKGROUND`: terrain, aerial context, buildings, roads, baseline river, vegetation
- `V23_FLOOD_RGBA`: ten existing V21 flood-stage objects on a transparent background
- `V23_FIELD_TEMPLATE_RGBA`: the legacy fixed field only, retained as a template and excluded from common output
- `V23_SHELTER_RGBA`: shelter marker and label on a transparent background
- `V23_RENDER_INFRA`: animated camera and lights shared by render layers

The V23 common view layer excludes the fixed registered field, flood stages, and shelter marker. No user identity or field-risk claim is baked into the common background.

## Outputs

- `blender/osong_common_v23.blend`
- `data/v23/scene_packs/osong_miho_v23_layer_manifest.json`
- `output/scene_packs/osong_miho_v23/previews/*.png`
- `output/scene_packs/osong_miho_v23/common_background_v23_60s.mp4`

The nine proof frames passed visual review. The common 60-second MP4 was rendered once at 1280x720, 16 FPS and is now a reusable cache. The reusable flood RGBA sequence was completed in Stage 6 as five camera-aligned QTRLE clips and is documented in `docs/V23_FLOOD_LAYER_ASSETS.md`. Per-field overlays and camera profiles are documented in `docs/V23_FIELD_PERSONALIZATION.md`.

## Rebuild commands

```bash
/Applications/Blender.app/Contents/MacOS/Blender \
  -b blender/osong_visual_v22.blend \
  --python blender/build_osong_common_v23.py

/Applications/Blender.app/Contents/MacOS/Blender \
  -b blender/osong_common_v23.blend \
  --python blender/render_osong_common_v23_previews.py

PYTHONDONTWRITEBYTECODE=1 python3 scripts/validate_v23_layer_previews.py

/Applications/Blender.app/Contents/MacOS/Blender \
  -b blender/osong_common_v23.blend \
  --python blender/render_osong_common_v23_video.py
```
