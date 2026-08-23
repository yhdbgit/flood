"""Build and validate the Gangnae terrain-only Blender prototype.

Scope:
- validate N36E127 SRTM HGT,
- build the Gangnae terrain mesh,
- add one material, camera, and sun,
- render one PNG preview,
- save one blend file and one validation report.

No river, road, farmland, flood layer, animation, or video is created.
"""

from array import array
import json
import math
from pathlib import Path
import sys

import bpy
from mathutils import Vector


ROOT = Path("/Users/hyeokjae/Desktop/ICTCB/flood")
HGT_PATH = ROOT / "data" / "terrain" / "N36E127.hgt"
PREVIEW_PATH = ROOT / "output" / "gangnae_terrain_preview.png"
BLEND_PATH = ROOT / "blender" / "gangnae_terrain_v1.blend"
REPORT_PATH = ROOT / "output" / "terrain_validation_report.json"

SCENE_NAME = "Gangnae_Terrain_V1"
COLLECTION_NAME = "DT_TERRAIN_V1"
TERRAIN_NAME = "Terrain_Gangnae"
CAMERA_NAME = "Camera_Gangnae_Overview"
SUN_NAME = "Sun_Gangnae"
MATERIAL_NAME = "Material_Gangnae_Terrain"

MIN_LON = 127.33154296875
MIN_LAT = 36.58465761247168
MAX_LON = 127.386474609375
MAX_LAT = 36.615527631349245

HGT_TILE_WEST = 127.0
HGT_TILE_SOUTH = 36.0
HGT_GRID_SIZE = 3601
HGT_EXPECTED_BYTES = HGT_GRID_SIZE * HGT_GRID_SIZE * 2

MESH_COLUMNS = 165
MESH_ROWS = 115
VERTICAL_EXAGGERATION = 2.0

METRES_PER_DEGREE_LAT = 111_320.0
CENTRE_LON = (MIN_LON + MAX_LON) / 2.0
CENTRE_LAT = (MIN_LAT + MAX_LAT) / 2.0
METRES_PER_DEGREE_LON = (
    METRES_PER_DEGREE_LAT * math.cos(math.radians(CENTRE_LAT))
)


def validate_inputs():
    if not HGT_PATH.is_file():
        raise FileNotFoundError(f"HGT file not found: {HGT_PATH}")
    if HGT_PATH.stat().st_size != HGT_EXPECTED_BYTES:
        raise ValueError(
            f"Unexpected HGT size: expected {HGT_EXPECTED_BYTES:,}, "
            f"got {HGT_PATH.stat().st_size:,}"
        )
    if not (
        HGT_TILE_WEST <= MIN_LON < MAX_LON <= HGT_TILE_WEST + 1.0
        and HGT_TILE_SOUTH <= MIN_LAT < MAX_LAT <= HGT_TILE_SOUTH + 1.0
    ):
        raise ValueError("Pilot bounds are outside the N36E127 tile")
    PREVIEW_PATH.parent.mkdir(parents=True, exist_ok=True)
    BLEND_PATH.parent.mkdir(parents=True, exist_ok=True)


def read_hgt():
    values = array("h")
    with HGT_PATH.open("rb") as source:
        values.fromfile(source, HGT_GRID_SIZE * HGT_GRID_SIZE)
    if sys.byteorder == "little":
        values.byteswap()
    if len(values) != HGT_GRID_SIZE * HGT_GRID_SIZE:
        raise ValueError(f"Incomplete HGT grid: {len(values):,} samples")
    return values


def sample_nearest(values, lon, lat):
    column = round((lon - HGT_TILE_WEST) * (HGT_GRID_SIZE - 1))
    row = round(((HGT_TILE_SOUTH + 1.0) - lat) * (HGT_GRID_SIZE - 1))
    column = max(0, min(HGT_GRID_SIZE - 1, column))
    row = max(0, min(HGT_GRID_SIZE - 1, row))
    elevation = int(values[row * HGT_GRID_SIZE + column])
    if elevation == -32768:
        raise ValueError(f"HGT void at lon={lon:.7f}, lat={lat:.7f}")
    return elevation


def to_local_metres(lon, lat):
    return (
        (lon - CENTRE_LON) * METRES_PER_DEGREE_LON,
        (lat - CENTRE_LAT) * METRES_PER_DEGREE_LAT,
    )


def prepare_scene():
    scene = bpy.data.scenes.get(SCENE_NAME)
    if scene is None:
        scene = bpy.data.scenes.new(SCENE_NAME)
    else:
        for obj in list(scene.objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        for child in list(scene.collection.children):
            scene.collection.children.unlink(child)
            if child.users == 0:
                bpy.data.collections.remove(child)

    bpy.context.window.scene = scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.length_unit = "METERS"
    scene.unit_settings.scale_length = 1.0

    collection = bpy.data.collections.new(COLLECTION_NAME)
    scene.collection.children.link(collection)
    return scene, collection


def create_terrain(values, collection):
    elevations = []
    raw_vertices = []
    for row in range(MESH_ROWS):
        lat = MAX_LAT - (MAX_LAT - MIN_LAT) * row / (MESH_ROWS - 1)
        for column in range(MESH_COLUMNS):
            lon = MIN_LON + (MAX_LON - MIN_LON) * column / (MESH_COLUMNS - 1)
            elevation = sample_nearest(values, lon, lat)
            x, y = to_local_metres(lon, lat)
            elevations.append(elevation)
            raw_vertices.append((x, y, float(elevation)))

    minimum = min(elevations)
    maximum = max(elevations)
    if minimum == maximum:
        raise ValueError("Terrain elevation range is zero")

    vertices = [
        (x, y, (z - minimum) * VERTICAL_EXAGGERATION)
        for x, y, z in raw_vertices
    ]
    faces = []
    for row in range(MESH_ROWS - 1):
        for column in range(MESH_COLUMNS - 1):
            index = row * MESH_COLUMNS + column
            faces.append(
                (
                    index,
                    index + MESH_COLUMNS,
                    index + MESH_COLUMNS + 1,
                    index + 1,
                )
            )

    mesh = bpy.data.meshes.new(f"{TERRAIN_NAME}_Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.validate(verbose=True)
    mesh.update(calc_edges=True)
    for polygon in mesh.polygons:
        polygon.use_smooth = True

    terrain = bpy.data.objects.new(TERRAIN_NAME, mesh)
    collection.objects.link(terrain)
    terrain.color = (0.16, 0.38, 0.12, 1.0)
    terrain["source"] = str(HGT_PATH)
    terrain["bounds_wgs84"] = [MIN_LON, MIN_LAT, MAX_LON, MAX_LAT]
    terrain["elevation_min_m"] = minimum
    terrain["elevation_max_m"] = maximum
    terrain["vertical_exaggeration"] = VERTICAL_EXAGGERATION
    return terrain, minimum, maximum, len(vertices), len(faces)


def create_material(terrain):
    old = bpy.data.materials.get(MATERIAL_NAME)
    if old is not None:
        bpy.data.materials.remove(old, do_unlink=True)

    material = bpy.data.materials.new(MATERIAL_NAME)
    material.diffuse_color = (0.16, 0.38, 0.12, 1.0)
    material.use_nodes = True
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    shader = nodes.new("ShaderNodeBsdfPrincipled")
    shader.inputs.get("Base Color").default_value = (0.16, 0.38, 0.12, 1.0)
    shader.inputs.get("Roughness").default_value = 0.88
    links.new(shader.outputs.get("BSDF"), output.inputs.get("Surface"))
    terrain.data.materials.append(material)
    return material


def point_at(obj, target):
    obj.rotation_euler = (
        Vector(target) - obj.location
    ).to_track_quat("-Z", "Y").to_euler()


def create_camera(scene, terrain):
    horizontal_span = max(terrain.dimensions.x, terrain.dimensions.y)
    target = (0.0, 0.0, max(20.0, terrain.dimensions.z * 0.25))
    base_location = Vector(
        (
            horizontal_span * 0.08,
            -horizontal_span * 1.35,
            horizontal_span * 1.00,
        )
    )
    target_vector = Vector(target)
    location = target_vector + (base_location - target_vector) * 1.18

    camera_data = bpy.data.cameras.new(f"{CAMERA_NAME}_Data")
    camera = bpy.data.objects.new(CAMERA_NAME, camera_data)
    scene.collection.objects.link(camera)
    camera.location = location
    point_at(camera, target)
    camera_data.lens = 52.0
    camera_data.sensor_width = 36.0
    camera_data.clip_start = 1.0
    camera_data.clip_end = 100_000.0
    scene.camera = camera
    return camera, target


def create_sun(scene):
    light_data = bpy.data.lights.new(f"{SUN_NAME}_Data", type="SUN")
    light_data.energy = 3.0
    light_data.angle = math.radians(8.0)
    sun = bpy.data.objects.new(SUN_NAME, light_data)
    scene.collection.objects.link(sun)
    sun.rotation_euler = (
        math.radians(28.0),
        math.radians(-22.0),
        math.radians(-35.0),
    )
    return sun


def configure_world(scene):
    world = bpy.data.worlds.new("Gangnae_World")
    world.use_nodes = True
    background = next(
        (node for node in world.node_tree.nodes if node.type == "BACKGROUND"), None
    )
    if background is not None:
        background.inputs.get("Color").default_value = (0.055, 0.075, 0.105, 1.0)
        background.inputs.get("Strength").default_value = 0.32
    scene.world = world


def configure_render(scene):
    engine = None
    for candidate in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE", "BLENDER_WORKBENCH"):
        try:
            scene.render.engine = candidate
            engine = candidate
            break
        except TypeError:
            continue
    if engine is None:
        raise RuntimeError("Blender did not accept EEVEE or Workbench")

    scene.render.resolution_x = 1280
    scene.render.resolution_y = 720
    scene.render.resolution_percentage = 100
    scene.render.image_settings.media_type = "IMAGE"
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.image_settings.color_depth = "8"
    scene.render.filepath = str(PREVIEW_PATH)
    scene.render.film_transparent = False
    return engine


def show_render_result_when_ready():
    attempts = {"remaining": 20}

    def show_result():
        screen = bpy.context.screen
        image = bpy.data.images.get("Render Result")
        if screen is None or image is None:
            attempts["remaining"] -= 1
            return 0.25 if attempts["remaining"] > 0 else None
        area = next((item for item in screen.areas if item.type == "VIEW_3D"), None)
        if area is None:
            return None
        area.type = "IMAGE_EDITOR"
        area.spaces.active.image = image
        area.tag_redraw()
        return None

    bpy.app.timers.register(show_result, first_interval=0.75)


def write_report(scene, terrain, camera, sun, material, engine, minimum, maximum):
    report = {
        "status": "ok",
        "scope": "terrain-only",
        "hgt_path": str(HGT_PATH),
        "hgt_bytes": HGT_PATH.stat().st_size,
        "hgt_grid": [HGT_GRID_SIZE, HGT_GRID_SIZE],
        "bounds_wgs84": [MIN_LON, MIN_LAT, MAX_LON, MAX_LAT],
        "mesh_grid": [MESH_COLUMNS, MESH_ROWS],
        "vertex_count": len(terrain.data.vertices),
        "face_count": len(terrain.data.polygons),
        "elevation_min_m": minimum,
        "elevation_max_m": maximum,
        "vertical_exaggeration": VERTICAL_EXAGGERATION,
        "terrain_dimensions_m": list(terrain.dimensions),
        "camera": camera.name,
        "camera_location": list(camera.location),
        "camera_lens_mm": camera.data.lens,
        "camera_clip": [camera.data.clip_start, camera.data.clip_end],
        "active_camera": scene.camera.name if scene.camera else None,
        "sun": sun.name,
        "sun_energy": sun.data.energy,
        "material": material.name,
        "render_engine": engine,
        "preview_path": str(PREVIEW_PATH),
        "preview_bytes": PREVIEW_PATH.stat().st_size,
        "blend_path": str(BLEND_PATH),
        "blend_bytes": BLEND_PATH.stat().st_size,
    }
    REPORT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


def main():
    validate_inputs()
    values = read_hgt()
    scene, collection = prepare_scene()
    terrain, minimum, maximum, _, _ = create_terrain(values, collection)
    material = create_material(terrain)
    camera, _ = create_camera(scene, terrain)
    sun = create_sun(scene)
    configure_world(scene)
    engine = configure_render(scene)

    bpy.ops.render.render(write_still=True)
    if not PREVIEW_PATH.is_file() or PREVIEW_PATH.stat().st_size == 0:
        raise RuntimeError(f"Preview render was not created: {PREVIEW_PATH}")
    bpy.ops.wm.save_as_mainfile(filepath=str(BLEND_PATH))

    report = write_report(
        scene, terrain, camera, sun, material, engine, minimum, maximum
    )
    show_render_result_when_ready()
    print("[terrain-v1] terrain-only build complete")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
