"""Build the Gangnae hydro digital-twin v2 on top of terrain-v1.

Run with:
  Blender --background blender/gangnae_terrain_v1.blend \
    --python blender/build_gangnae_hydro_v2.py

The script does not call external APIs. It consumes sanitized JSON prepared by
the external Python collectors, renders one preview, and saves one v2 blend.
"""

from array import array
import json
import math
from pathlib import Path
import sys

import bpy
from mathutils import Vector


ROOT = Path("/Users/hyeokjae/Desktop/ICTCB/flood")
GEOMETRY_PATH = ROOT / "data" / "processed" / "gangnae_hydro_geometry.json"
SNAPSHOT_PATH = ROOT / "data" / "runtime" / "hydro_snapshot.json"
HGT_PATH = ROOT / "data" / "terrain" / "N36E127.hgt"
PREVIEW_PATH = ROOT / "output" / "gangnae_hydro_v2_preview.png"
BLEND_PATH = ROOT / "blender" / "gangnae_hydro_v2.blend"
REPORT_PATH = ROOT / "output" / "hydro_v2_validation_report.json"

COLLECTION_NAME = "DT_HYDRO_V2"
CAMERA_NAME = "Camera_Gangnae_Hydro_V2"
FONT_PATH = Path("/System/Library/Fonts/AppleSDGothicNeo.ttc")

HGT_GRID_SIZE = 3601
HGT_TILE_WEST = 127.0
HGT_TILE_SOUTH = 36.0

RISK_COLOURS = {
    "normal": (0.015, 0.24, 0.72, 1.0),
    "attention": (0.95, 0.68, 0.04, 1.0),
    "warning": (1.0, 0.30, 0.02, 1.0),
    "alarm": (0.82, 0.025, 0.02, 1.0),
    "serious": (0.46, 0.0, 0.0, 1.0),
    "unknown": (0.35, 0.35, 0.38, 1.0),
}


def load_json(path):
    if not path.is_file():
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))


def read_hgt():
    values = array("h")
    with HGT_PATH.open("rb") as source:
        values.fromfile(source, HGT_GRID_SIZE * HGT_GRID_SIZE)
    if sys.byteorder == "little":
        values.byteswap()
    return values


def prepare_scene():
    scene = bpy.context.scene
    old = bpy.data.collections.get(COLLECTION_NAME)
    if old is not None:
        for obj in list(old.objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        for parent in bpy.data.collections:
            if old.name in parent.children:
                parent.children.unlink(old)
        if old.name in scene.collection.children:
            scene.collection.children.unlink(old)
        bpy.data.collections.remove(old)
    collection = bpy.data.collections.new(COLLECTION_NAME)
    scene.collection.children.link(collection)
    scene.name = "Gangnae_Hydro_V2"
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.length_unit = "METERS"
    scene.unit_settings.scale_length = 1.0
    return scene, collection


def material(name, colour, metallic=0.0, roughness=0.55, emission_strength=0.0):
    existing = bpy.data.materials.get(name)
    if existing is not None:
        bpy.data.materials.remove(existing, do_unlink=True)
    item = bpy.data.materials.new(name)
    item.diffuse_color = colour
    item.use_nodes = True
    nodes = item.node_tree.nodes
    links = item.node_tree.links
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    shader = nodes.new("ShaderNodeBsdfPrincipled")
    shader.inputs.get("Base Color").default_value = colour
    shader.inputs.get("Roughness").default_value = roughness
    shader.inputs.get("Metallic").default_value = metallic
    if shader.inputs.get("Emission Color") is not None:
        shader.inputs.get("Emission Color").default_value = colour
        shader.inputs.get("Emission Strength").default_value = emission_strength
    elif shader.inputs.get("Emission") is not None:
        shader.inputs.get("Emission").default_value = colour
    links.new(shader.outputs.get("BSDF"), output.inputs.get("Surface"))
    return item


def local_to_lonlat(x, y, geometry):
    origin_lon, origin_lat = geometry["origin_wgs84"]
    scale = geometry["metres_per_degree"]
    return (
        origin_lon + x / scale["longitude"],
        origin_lat + y / scale["latitude"],
    )


def sample_elevation(values, lon, lat):
    column = round((lon - HGT_TILE_WEST) * (HGT_GRID_SIZE - 1))
    row = round(((HGT_TILE_SOUTH + 1.0) - lat) * (HGT_GRID_SIZE - 1))
    column = max(0, min(HGT_GRID_SIZE - 1, column))
    row = max(0, min(HGT_GRID_SIZE - 1, row))
    value = int(values[row * HGT_GRID_SIZE + column])
    if value == -32768:
        raise ValueError(f"HGT void at {lon}, {lat}")
    return value


def terrain_z(values, x, y, geometry, extra=0.0):
    lon, lat = local_to_lonlat(x, y, geometry)
    elevation = sample_elevation(values, lon, lat)
    terrain = geometry["terrain"]
    return (
        (elevation - terrain["elevation_min_m"])
        * terrain["vertical_exaggeration"]
        + extra
    )


def add_curve_object(
    name,
    paths,
    collection,
    curve_material,
    values,
    geometry,
    bevel_depth,
    z_offset,
    level_delta=0.0,
):
    data = bpy.data.curves.new(f"{name}_Curve", type="CURVE")
    data.dimensions = "3D"
    data.resolution_u = 1
    data.bevel_depth = bevel_depth
    data.bevel_resolution = 2
    data.resolution_v = 1
    for path in paths:
        if len(path) < 2:
            continue
        spline = data.splines.new("POLY")
        spline.points.add(len(path) - 1)
        for point, (x, y) in zip(spline.points, path):
            z = terrain_z(values, x, y, geometry, z_offset + level_delta)
            point.co = (x, y, z, 1.0)
        spline.use_cyclic_u = path[0] == path[-1]
    obj = bpy.data.objects.new(name, data)
    collection.objects.link(obj)
    obj.data.materials.append(curve_material)
    return obj


def zone_paths(zone):
    paths = []
    for polygon in zone["polygons"]:
        paths.append(polygon["exterior"])
        paths.extend(polygon["holes"])
    return paths


def point_at(obj, target):
    obj.rotation_euler = (
        Vector(target) - obj.location
    ).to_track_quat("-Z", "Y").to_euler()


def face_camera(obj, camera):
    obj.rotation_euler = (
        camera.location - obj.location
    ).to_track_quat("Z", "Y").to_euler()


def create_camera(scene, collection, terrain_dimensions):
    width, depth, height = terrain_dimensions
    camera_data = bpy.data.cameras.new(f"{CAMERA_NAME}_Data")
    camera = bpy.data.objects.new(CAMERA_NAME, camera_data)
    collection.objects.link(camera)
    target = (0.0, 0.0, max(55.0, height * 0.18))
    camera.location = (width * 0.07, -depth * 1.82, width * 1.14)
    point_at(camera, target)
    camera_data.lens = 52.0
    camera_data.sensor_width = 36.0
    camera_data.clip_start = 1.0
    camera_data.clip_end = 100_000.0
    scene.camera = camera
    return camera


def create_marker(name, x, y, collection, marker_material, values, geometry):
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=24,
        radius=42.0,
        depth=84.0,
        location=(x, y, terrain_z(values, x, y, geometry, 42.0)),
    )
    marker = bpy.context.object
    marker.name = name
    for current in list(marker.users_collection):
        current.objects.unlink(marker)
    collection.objects.link(marker)
    marker.data.materials.append(marker_material)
    return marker


def create_text(name, body, location, size, collection, text_material, camera, font):
    data = bpy.data.curves.new(f"{name}_Text", type="FONT")
    data.body = body
    data.align_x = "CENTER"
    data.align_y = "CENTER"
    data.size = size
    data.extrude = max(0.2, size * 0.012)
    if font is not None:
        data.font = font
    obj = bpy.data.objects.new(name, data)
    collection.objects.link(obj)
    obj.location = location
    obj.data.materials.append(text_material)
    face_camera(obj, camera)
    return obj


def clamp_station_to_scene(station, geometry):
    origin_lon, origin_lat = geometry["origin_wgs84"]
    scale = geometry["metres_per_degree"]
    x = (station["longitude"] - origin_lon) * scale["longitude"]
    y = (station["latitude"] - origin_lat) * scale["latitude"]
    width, depth, _ = geometry["terrain"]["dimensions_m"]
    margin = 520.0
    clamped_x = max(-width / 2 + margin, min(width / 2 - margin, x))
    clamped_y = max(-depth / 2 + margin, min(depth / 2 - margin, y))
    external = abs(clamped_x - x) > 0.1 or abs(clamped_y - y) > 0.1
    return clamped_x, clamped_y, external


def configure_render(scene):
    for candidate in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE", "BLENDER_WORKBENCH"):
        try:
            scene.render.engine = candidate
            break
        except TypeError:
            continue
    else:
        raise RuntimeError("No supported Blender render engine")
    scene.render.resolution_x = 1280
    scene.render.resolution_y = 720
    scene.render.resolution_percentage = 100
    scene.render.image_settings.media_type = "IMAGE"
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.image_settings.color_depth = "8"
    scene.render.filepath = str(PREVIEW_PATH)
    scene.render.film_transparent = False
    return scene.render.engine


def main():
    geometry = load_json(GEOMETRY_PATH)
    snapshot = load_json(SNAPSHOT_PATH)
    values = read_hgt()
    scene, collection = prepare_scene()
    camera = create_camera(scene, collection, geometry["terrain"]["dimensions_m"])

    risk_code = snapshot["scene_state"]["risk"]["code"]
    water_colour = RISK_COLOURS.get(risk_code, RISK_COLOURS["unknown"])
    water_material = material(
        "Material_Hydro_Water", water_colour, metallic=0.12, roughness=0.28, emission_strength=0.08
    )
    main_zone_material = material(
        "Material_Hydro_MainZone", (0.02, 0.78, 0.94, 1.0), roughness=0.42, emission_strength=0.22
    )
    small_zone_material = material(
        "Material_Hydro_SmallZone", (0.0, 0.95, 0.62, 1.0), roughness=0.5, emission_strength=0.18
    )
    marker_material = material(
        "Material_Hydro_Station", (1.0, 0.19, 0.04, 1.0), roughness=0.38, emission_strength=0.28
    )
    text_material = material(
        "Material_Hydro_Text", (0.93, 0.97, 1.0, 1.0), roughness=0.55, emission_strength=0.35
    )

    zone_objects = []
    for zone in geometry["official_zones"]:
        is_main = zone["source_layer"] == "UJ201"
        obj = add_curve_object(
            f"Zone_{zone['name']}",
            zone_paths(zone),
            collection,
            main_zone_material if is_main else small_zone_material,
            values,
            geometry,
            bevel_depth=4.0 if is_main else 2.4,
            z_offset=7.0 if is_main else 5.0,
        )
        obj["source_layer"] = zone["source_layer"]
        obj["classification"] = zone["classification"]
        obj["official_alias"] = zone["official_alias"]
        obj["intersection_area_m2"] = zone["intersection_area_m2"]
        zone_objects.append(obj)

    level_delta = snapshot["scene_state"].get("visual_level_delta_m", 0.0)
    vertical_scale = geometry["terrain"]["vertical_exaggeration"]
    water_objects = []
    for centreline in geometry["centerlines"]:
        is_main = centreline["name"] == "미호강"
        obj = add_curve_object(
            f"Water_{centreline['name']}",
            centreline["parts"],
            collection,
            water_material,
            values,
            geometry,
            bevel_depth=centreline["visual_width_m"] / 2.0,
            z_offset=4.0,
            level_delta=(level_delta * vertical_scale if is_main else 0.0),
        )
        obj["source"] = centreline["source"]
        obj["source_name"] = centreline["source_name"]
        obj["official_display_name"] = centreline["name"]
        obj["visual_width_m"] = centreline["visual_width_m"]
        obj["level_delta_m"] = level_delta if is_main else 0.0
        obj["flow_m3s"] = snapshot["scene_state"].get("flow_m3s") if is_main else 0.0
        water_objects.append(obj)

    font = None
    if FONT_PATH.is_file():
        try:
            font = bpy.data.fonts.load(str(FONT_PATH), check_existing=True)
        except RuntimeError:
            font = None

    station_objects = []
    width, depth, _ = geometry["terrain"]["dimensions_m"]
    for index, station in enumerate(snapshot["stations"]):
        x, y, external = clamp_station_to_scene(station, geometry)
        marker = create_marker(
            f"Station_{station['code']}", x, y, collection, marker_material, values, geometry
        )
        marker["station_code"] = station["code"]
        marker["station_name"] = station["name"]
        marker["longitude"] = station["longitude"]
        marker["latitude"] = station["latitude"]
        marker["outside_terrain_bounds"] = external
        marker["water_level_m"] = station["water_level_m"]
        marker["flow_m3s"] = station["flow_m3s"]
        marker["risk_stage"] = station["risk"]["label"]
        station_objects.append(marker)
        external_note = " · 경계 밖 관측소" if external else ""
        create_text(
            f"Label_Station_{station['code']}",
            f"{station['name']}\n수위 {station['water_level_m']:.2f}m{external_note}",
            (x, y, marker.location.z + 135.0 + index * 8.0),
            54.0,
            collection,
            text_material,
            camera,
            font,
        )

    primary = next(
        item for item in snapshot["stations"] if item["code"] == snapshot["primary_station_code"]
    )
    trend_label = {"rising": "상승", "falling": "하강", "steady": "변동없음"}.get(
        primary.get("trend"), "확인중"
    )
    create_text(
        "Label_Hydro_Status",
        (
            f"미호강 현재 수문상태  |  {primary['risk']['label']} · {trend_label}\n"
            f"수위 {primary['water_level_m']:.2f}m   유량 {primary['flow_m3s']:.2f}㎥/s   "
            f"관측 {primary['observed_at'][11:16]}"
        ),
        (-width * 0.18, -depth * 0.36, 420.0),
        62.0,
        collection,
        text_material,
        camera,
        font,
    )

    for centreline in geometry["centerlines"]:
        longest = max(centreline["parts"], key=len)
        x, y = longest[len(longest) // 2]
        create_text(
            f"Label_River_{centreline['name']}",
            centreline["name"],
            (x, y, terrain_z(values, x, y, geometry, 110.0)),
            72.0 if centreline["name"] == "미호강" else 48.0,
            collection,
            text_material,
            camera,
            font,
        )

    engine = configure_render(scene)
    PREVIEW_PATH.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.render.render(write_still=True)
    if not PREVIEW_PATH.is_file() or PREVIEW_PATH.stat().st_size == 0:
        raise RuntimeError("Hydro preview was not generated")
    bpy.ops.wm.save_as_mainfile(filepath=str(BLEND_PATH))

    report = {
        "status": "ok",
        "scope": "terrain + official river zones + live hydro snapshot",
        "scene": scene.name,
        "collection": collection.name,
        "terrain_source_blend": "gangnae_terrain_v1.blend",
        "official_zone_count": len(zone_objects),
        "official_river_zone_count": len(
            [obj for obj in zone_objects if obj["source_layer"] == "UJ201"]
        ),
        "official_small_river_zone_count": len(
            [obj for obj in zone_objects if obj["source_layer"] == "UJ301"]
        ),
        "waterway_count": len(water_objects),
        "station_count": len(station_objects),
        "primary_station": primary["name"],
        "observed_at": primary["observed_at"],
        "water_level_m": primary["water_level_m"],
        "flow_m3s": primary["flow_m3s"],
        "risk_stage": primary["risk"],
        "trend": primary.get("trend"),
        "visual_level_delta_m": level_delta,
        "render_engine": engine,
        "camera": camera.name,
        "preview_path": str(PREVIEW_PATH),
        "preview_bytes": PREVIEW_PATH.stat().st_size,
        "blend_path": str(BLEND_PATH),
        "blend_bytes": BLEND_PATH.stat().st_size,
        "api_key_in_scene": False,
        "limitations": [
            "Official zone boundaries are legal/management extents, not exact water surfaces.",
            "OSM centerline widths are visualization parameters.",
            "Water geometry uses relative gauge-level change, not hydraulic simulation.",
        ],
    }
    REPORT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("[hydro-v2] build complete")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
