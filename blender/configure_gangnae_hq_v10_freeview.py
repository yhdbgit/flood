"""Create a free-navigation copy of the V10 scene for Blender on macOS."""

from pathlib import Path

import bpy
from mathutils import Vector


ROOT = Path("/Users/hyeokjae/Desktop/ICTCB/flood")
OUTPUT = ROOT / "blender" / "gangnae_hq_v10_freeview.blend"


def main():
    configured = 0
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type != "VIEW_3D":
                continue
            for space in area.spaces:
                if space.type != "VIEW_3D":
                    continue
                space.clip_start = 0.1
                space.clip_end = 100_000.0
                space.shading.type = "RENDERED"
                if hasattr(space, "lock_camera"):
                    space.lock_camera = False
                region = space.region_3d
                region.view_perspective = "PERSP"
                region.view_location = Vector((0.0, 0.0, 18.0))
                region.view_distance = 900.0
                if hasattr(region, "use_clip_planes"):
                    region.use_clip_planes = False
                if hasattr(region, "use_box_clip"):
                    region.use_box_clip = False
                configured += 1

    for camera in (obj for obj in bpy.data.objects if obj.type == "CAMERA"):
        camera.data.clip_start = 0.1
        camera.data.clip_end = 100_000.0

    scene = bpy.context.scene
    scene["freeview_configured"] = True
    scene["freeview_clip_start_m"] = 0.1
    scene["freeview_clip_end_m"] = 100_000.0
    scene["freeview_viewport_count"] = configured
    bpy.ops.wm.save_as_mainfile(filepath=str(OUTPUT))
    print(
        {
            "status": "ok",
            "output": str(OUTPUT),
            "configured_viewports": configured,
            "clip_start": 0.1,
            "clip_end": 100_000.0,
            "shading": "RENDERED",
        }
    )


if __name__ == "__main__":
    main()
