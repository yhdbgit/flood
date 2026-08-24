"""Build the georeferenced Gangnae HQ V10 Blender scene.

Run:
  /Applications/Blender.app/Contents/MacOS/Blender --background --factory-startup \
    --python blender/build_gangnae_hq_v10.py

V10 is a new scene and never modifies the V9 blend files.  It combines a
textured SRTM terrain, OSM roads/bridges/buildings/water, the registered field,
and the official VWorld river-management boundary inside a 1 km AOI.
"""

from __future__ import annotations

import addon_utils
import json
import math
from pathlib import Path

import bpy
from mathutils import Vector
from mathutils.geometry import tessellate_polygon


ROOT = Path("/Users/hyeokjae/Desktop/ICTCB/flood")
CONTEXT_PATH = ROOT / "data" / "processed" / "gangnae_hq_v10_context.json"
BLEND_PATH = ROOT / "blender" / "gangnae_hq_v10.blend"
OUTPUT_DIR = ROOT / "output" / "hq_v10"
OVERVIEW_PATH = OUTPUT_DIR / "gangnae_hq_v10_overview.png"
TOP_PATH = OUTPUT_DIR / "gangnae_hq_v10_top.png"
FIELD_PATH = OUTPUT_DIR / "gangnae_hq_v10_field.png"
REPORT_PATH = OUTPUT_DIR / "scene_report.json"

SCENE_NAME = "Gangnae_HQ_V10"
COLLECTIONS = {
    "terrain": "V10_TERRAIN",
    "water": "V10_WATER",
    "roads": "V10_ROADS",
    "buildings": "V10_BUILDINGS",
    "field": "V10_REGISTERED_FIELD",
    "reference": "V10_OFFICIAL_REFERENCE",
    "lighting": "V10_LIGHTING",
}


def load_context():
    if not CONTEXT_PATH.is_file():
        raise FileNotFoundError(
            f"Missing V10 context: {CONTEXT_PATH}. Run scripts/prepare_gangnae_hq_v10.py first."
        )
    return json.loads(CONTEXT_PATH.read_text(encoding="utf-8"))


def reset_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.name = SCENE_NAME
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.length_unit = "METERS"
    scene.unit_settings.scale_length = 1.0
    collections = {}
    for key, name in COLLECTIONS.items():
        collection = bpy.data.collections.new(name)
        scene.collection.children.link(collection)
        collections[key] = collection
    return scene, collections


def configure_georeference(scene, context):
    georef = context["georeference"]
    origin_lon, origin_lat = georef["origin_wgs84"]
    origin_x, origin_y = georef["origin_utm"]
    # These are the BlenderGIS GeoScene keys.  Keeping them in the file lets
    # later BlenderGIS imports use the same projected origin.
    scene["SRID"] = georef["crs"]
    scene["crs x"] = float(origin_x)
    scene["crs y"] = float(origin_y)
    scene["longitude"] = float(origin_lon)
    scene["latitude"] = float(origin_lat)
    scene["scale"] = 1.0
    scene["zoom"] = int(context["aerial"]["zoom"])
    scene["v10_aoi_bounds_wgs84"] = georef["bounds_wgs84"]
    scene["v10_aoi_size_m"] = [1000.0, 1000.0]
    scene["v10_coordinate_policy"] = "EPSG:32652 metre offsets from registered field centre"


def enable_blendergis():
    try:
        addon_utils.enable("BlenderGIS", default_set=False, persistent=False)
    except Exception:
        pass
    enabled, loaded = addon_utils.check("BlenderGIS")
    return bool(enabled or loaded)


def new_material(name, colour, roughness=0.55, metallic=0.0, alpha=1.0):
    material = bpy.data.materials.new(name)
    material.diffuse_color = (*colour[:3], alpha)
    material.use_nodes = True
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    shader = nodes.new("ShaderNodeBsdfPrincipled")
    shader.inputs["Base Color"].default_value = (*colour[:3], alpha)
    shader.inputs["Roughness"].default_value = roughness
    shader.inputs["Metallic"].default_value = metallic
    if shader.inputs.get("Alpha") is not None:
        shader.inputs["Alpha"].default_value = alpha
    links.new(shader.outputs["BSDF"], output.inputs["Surface"])
    if alpha < 1.0:
        try:
            material.surface_render_method = "DITHERED"
        except (AttributeError, TypeError):
            try:
                material.blend_method = "BLEND"
            except (AttributeError, TypeError):
                pass
    return material


def aerial_material(image_path):
    if not image_path.is_file():
        raise FileNotFoundError(image_path)
    material = bpy.data.materials.new("V10_Mat_AerialTerrain")
    material.use_nodes = True
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    shader = nodes.new("ShaderNodeBsdfPrincipled")
    texture = nodes.new("ShaderNodeTexImage")
    texture.image = bpy.data.images.load(str(image_path), check_existing=True)
    texture.interpolation = "Linear"
    shader.inputs["Roughness"].default_value = 0.86
    shader.inputs["Metallic"].default_value = 0.0
    links.new(texture.outputs["Color"], shader.inputs["Base Color"])
    links.new(shader.outputs["BSDF"], output.inputs["Surface"])
    return material


class TerrainSampler:
    def __init__(self, terrain):
        self.rows = int(terrain["rows"])
        self.columns = int(terrain["columns"])
        self.vertices = terrain["vertices"]
        xs = [item[0] for item in self.vertices]
        ys = [item[1] for item in self.vertices]
        self.min_x, self.max_x = min(xs), max(xs)
        self.min_y, self.max_y = min(ys), max(ys)

    def z(self, x, y):
        u = max(0.0, min(1.0, (x - self.min_x) / (self.max_x - self.min_x)))
        v = max(0.0, min(1.0, (self.max_y - y) / (self.max_y - self.min_y)))
        column_f = u * (self.columns - 1)
        row_f = v * (self.rows - 1)
        c0 = min(self.columns - 2, max(0, math.floor(column_f)))
        r0 = min(self.rows - 2, max(0, math.floor(row_f)))
        dc = column_f - c0
        dr = row_f - r0

        def value(row, column):
            return float(self.vertices[row * self.columns + column][2])

        z00 = value(r0, c0)
        z10 = value(r0, c0 + 1)
        z01 = value(r0 + 1, c0)
        z11 = value(r0 + 1, c0 + 1)
        north = z00 * (1.0 - dc) + z10 * dc
        south = z01 * (1.0 - dc) + z11 * dc
        return north * (1.0 - dr) + south * dr


def create_terrain(context, collection):
    terrain_data = context["terrain"]
    rows = int(terrain_data["rows"])
    columns = int(terrain_data["columns"])
    vertices = [tuple(item) for item in terrain_data["vertices"]]
    faces = []
    for row in range(rows - 1):
        for column in range(columns - 1):
            index = row * columns + column
            faces.append((index, index + columns, index + columns + 1, index + 1))
    mesh = bpy.data.meshes.new("V10_TerrainMesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.validate(verbose=True)
    mesh.update(calc_edges=True)
    for polygon in mesh.polygons:
        polygon.use_smooth = True
    uv_layer = mesh.uv_layers.new(name="AerialUV")
    for polygon in mesh.polygons:
        for loop_index in polygon.loop_indices:
            vertex_index = mesh.loops[loop_index].vertex_index
            row = vertex_index // columns
            column = vertex_index % columns
            uv_layer.data[loop_index].uv = (
                column / (columns - 1),
                1.0 - row / (rows - 1),
            )
    obj = bpy.data.objects.new("Terrain_Gangnae_HQ_V10", mesh)
    collection.objects.link(obj)
    obj.data.materials.append(aerial_material(Path(context["aerial"]["path"])))
    obj["source_dem"] = terrain_data["source"]
    obj["aerial_source"] = context["aerial"]["provider"]
    obj["vertical_exaggeration"] = terrain_data["vertical_exaggeration"]
    return obj, TerrainSampler(terrain_data)


def polygon_mesh(name, points, sampler, collection, material, z_offset=0.5):
    clean = [tuple(map(float, point)) for point in points]
    if len(clean) < 3:
        return None
    vectors = [Vector((x, y)) for x, y in clean]
    triangles = tessellate_polygon([vectors])
    index_map = {(round(v.x, 6), round(v.y, 6)): index for index, v in enumerate(vectors)}
    faces = []
    for triangle in triangles:
        if triangle and isinstance(triangle[0], int):
            face = list(triangle)
        else:
            face = [index_map[(round(v.x, 6), round(v.y, 6))] for v in triangle]
        if len(set(face)) == 3:
            faces.append(face)
    vertices = [(x, y, sampler.z(x, y) + z_offset) for x, y in clean]
    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update(calc_edges=True)
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    obj.data.materials.append(material)
    return obj


def densify(points, step=8.0):
    if len(points) < 2:
        return points
    result = [tuple(points[0])]
    for start, end in zip(points, points[1:]):
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        distance = math.hypot(dx, dy)
        count = max(1, math.ceil(distance / step))
        for index in range(1, count + 1):
            ratio = index / count
            result.append((start[0] + dx * ratio, start[1] + dy * ratio))
    return result


def strip_mesh(name, points, width, sampler, collection, material, z_offset=0.4):
    points = densify(points)
    if len(points) < 2:
        return None
    vertices = []
    faces = []
    half = width / 2.0
    for index, point in enumerate(points):
        previous = points[max(0, index - 1)]
        following = points[min(len(points) - 1, index + 1)]
        tangent = Vector((following[0] - previous[0], following[1] - previous[1]))
        if tangent.length < 1e-5:
            tangent = Vector((1.0, 0.0))
        tangent.normalize()
        normal = Vector((-tangent.y, tangent.x))
        left = (point[0] + normal.x * half, point[1] + normal.y * half)
        right = (point[0] - normal.x * half, point[1] - normal.y * half)
        vertices.append((left[0], left[1], sampler.z(*left) + z_offset))
        vertices.append((right[0], right[1], sampler.z(*right) + z_offset))
    for index in range(len(points) - 1):
        base = index * 2
        faces.append((base, base + 2, base + 3, base + 1))
    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update(calc_edges=True)
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    obj.data.materials.append(material)
    return obj


def create_water(context, sampler, collection):
    water = new_material("V10_Mat_Water", (0.015, 0.24, 0.42), 0.18, 0.12, 0.88)
    count = 0
    for index, item in enumerate(context["water_polygons"]):
        obj = polygon_mesh(
            f"WaterPolygon_{index:03d}", item["polygon"], sampler, collection, water, 0.75
        )
        if obj:
            obj["source"] = "OpenStreetMap"
            obj["osm_id"] = item["osm_id"]
            obj["water_type"] = item["water"] or "water"
            count += 1
    for index, item in enumerate(context["waterways"]):
        obj = strip_mesh(
            f"Waterway_{index:03d}",
            item["path"],
            float(item["width_m"]),
            sampler,
            collection,
            water,
            0.8,
        )
        if obj:
            obj["source"] = "OpenStreetMap"
            obj["osm_id"] = item["osm_id"]
            obj["waterway"] = item["waterway"]
            count += 1
    return count


def create_roads(context, sampler, collection):
    major = new_material("V10_Mat_RoadMajor", (0.19, 0.20, 0.21), 0.9)
    minor = new_material("V10_Mat_RoadMinor", (0.28, 0.28, 0.26), 0.95)
    bridge = new_material("V10_Mat_Bridge", (0.42, 0.43, 0.44), 0.78)
    major_types = {"motorway", "trunk", "primary", "secondary", "tertiary"}
    count = 0
    bridge_count = 0
    for index, item in enumerate(context["roads"]):
        is_bridge = bool(item["bridge"])
        material = bridge if is_bridge else major if item["highway"] in major_types else minor
        z_offset = 4.0 if is_bridge else 0.55
        obj = strip_mesh(
            f"Road_{index:03d}_{item['highway']}",
            item["path"],
            float(item["width_m"]),
            sampler,
            collection,
            material,
            z_offset,
        )
        if obj:
            obj["source"] = "OpenStreetMap"
            obj["osm_id"] = item["osm_id"]
            obj["highway"] = item["highway"]
            obj["bridge"] = is_bridge
            count += 1
            bridge_count += int(is_bridge)
    return count, bridge_count


def create_building(item, sampler, collection, wall_material, roof_material, index):
    points = [tuple(map(float, point)) for point in item["polygon"]]
    if len(points) < 3:
        return None
    floor = max(sampler.z(x, y) for x, y in points) + 0.25
    height = float(item["height_m"])
    vertices = [(x, y, floor) for x, y in points] + [(x, y, floor + height) for x, y in points]
    size = len(points)
    faces = []
    material_indices = []
    for i in range(size):
        following = (i + 1) % size
        faces.append((i, following, size + following, size + i))
        material_indices.append(0)
    roof_vectors = [Vector((x, y)) for x, y in points]
    index_map = {(round(v.x, 6), round(v.y, 6)): i for i, v in enumerate(roof_vectors)}
    for triangle in tessellate_polygon([roof_vectors]):
        if triangle and isinstance(triangle[0], int):
            face = [size + i for i in triangle]
        else:
            face = [size + index_map[(round(v.x, 6), round(v.y, 6))] for v in triangle]
        if len(set(face)) == 3:
            faces.append(face)
            material_indices.append(1)
    mesh = bpy.data.meshes.new(f"Building_{index:03d}_Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update(calc_edges=True)
    mesh.materials.append(wall_material)
    mesh.materials.append(roof_material)
    for polygon, material_index in zip(mesh.polygons, material_indices):
        polygon.material_index = material_index
    obj = bpy.data.objects.new(f"Building_{index:03d}", mesh)
    collection.objects.link(obj)
    obj["source"] = "OpenStreetMap"
    obj["osm_id"] = item["osm_id"]
    obj["height_m"] = height
    bevel = obj.modifiers.new("Small edge bevel", "BEVEL")
    bevel.width = 0.35
    bevel.segments = 2
    return obj


def create_buildings(context, sampler, collection):
    wall = new_material("V10_Mat_BuildingWall", (0.53, 0.48, 0.42), 0.78)
    roof = new_material("V10_Mat_BuildingRoof", (0.25, 0.18, 0.15), 0.72)
    count = 0
    for index, item in enumerate(context["buildings"]):
        if create_building(item, sampler, collection, wall, roof, index):
            count += 1
    return count


def create_field(context, sampler, collection):
    field = context["field"]
    fill = new_material("V10_Mat_FieldFill", (0.52, 0.85, 0.08), 0.5, 0.0, 0.20)
    border = new_material("V10_Mat_FieldBorder", (0.95, 0.98, 0.12), 0.38, 0.0, 1.0)
    obj = polygon_mesh("RegisteredField_V10", field["polygon"], sampler, collection, fill, 1.25)
    boundary = field["polygon"] + [field["polygon"][0]]
    outline = strip_mesh("RegisteredFieldBoundary_V10", boundary, 2.8, sampler, collection, border, 1.45)
    for item in (obj, outline):
        if item:
            item["field_id"] = field["field_id"]
            item["geometry_accuracy"] = field["geometry_accuracy"]
            item["area_m2"] = field["area_m2"]
    return obj, outline


def create_official_reference(context, sampler, collection):
    material = new_material("V10_Mat_OfficialRiverBoundary", (0.0, 0.86, 1.0), 0.42, 0.0, 0.78)
    count = 0
    for zone in context["official_river_reference"]:
        for index, item in enumerate(zone["polygons"]):
            boundary = item["exterior"] + [item["exterior"][0]]
            obj = strip_mesh(
                f"OfficialBoundary_{zone['id']}_{index}",
                boundary,
                1.4,
                sampler,
                collection,
                material,
                1.1,
            )
            if obj:
                obj["source"] = "VWorld"
                obj["source_layer"] = zone["source_layer"]
                obj["zone_name"] = zone["name"]
                obj["meaning"] = "river management reference boundary, not current water surface"
                count += 1
    return count


def point_at(obj, target):
    obj.rotation_euler = (Vector(target) - obj.location).to_track_quat("-Z", "Y").to_euler()


def create_camera(name, location, target, lens, collection, orthographic=False):
    data = bpy.data.cameras.new(f"{name}_Data")
    obj = bpy.data.objects.new(name, data)
    collection.objects.link(obj)
    obj.location = location
    point_at(obj, target)
    data.lens = lens
    data.sensor_width = 36.0
    data.clip_start = 0.5
    data.clip_end = 20_000.0
    if orthographic:
        data.type = "ORTHO"
        data.ortho_scale = 1120.0
    return obj


def create_lighting(scene, collection):
    world = bpy.data.worlds.new("V10_World")
    world.use_nodes = True
    background = world.node_tree.nodes.get("Background")
    background.inputs["Color"].default_value = (0.19, 0.25, 0.34, 1.0)
    background.inputs["Strength"].default_value = 0.62
    scene.world = world

    sun_data = bpy.data.lights.new("V10_Sun_Data", "SUN")
    sun_data.energy = 2.4
    sun_data.angle = math.radians(5.5)
    sun = bpy.data.objects.new("V10_Sun", sun_data)
    collection.objects.link(sun)
    sun.rotation_euler = (math.radians(28), math.radians(-18), math.radians(-32))

    area_data = bpy.data.lights.new("V10_Softbox_Data", "AREA")
    area_data.energy = 650.0
    area_data.shape = "DISK"
    area_data.size = 650.0
    area = bpy.data.objects.new("V10_Softbox", area_data)
    collection.objects.link(area)
    area.location = (-260.0, -120.0, 620.0)
    point_at(area, (0.0, 0.0, 0.0))
    return sun, area


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
        raise RuntimeError("No supported Blender render engine")
    scene.render.resolution_x = 1280
    scene.render.resolution_y = 720
    scene.render.resolution_percentage = 100
    scene.render.image_settings.media_type = "IMAGE"
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.image_settings.color_depth = "8"
    scene.render.film_transparent = False
    try:
        scene.render.image_settings.color_management = "FOLLOW_SCENE"
        scene.view_settings.look = "AgX - Medium High Contrast"
    except (AttributeError, TypeError):
        pass
    return engine


def render(scene, camera, path):
    scene.camera = camera
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)
    if not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError(f"Render failed: {path}")


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    BLEND_PATH.parent.mkdir(parents=True, exist_ok=True)
    context = load_context()
    scene, collections = reset_scene()
    configure_georeference(scene, context)
    blendergis_enabled = enable_blendergis()
    terrain, sampler = create_terrain(context, collections["terrain"])
    water_count = create_water(context, sampler, collections["water"])
    road_count, bridge_count = create_roads(context, sampler, collections["roads"])
    building_count = create_buildings(context, sampler, collections["buildings"])
    field, field_outline = create_field(context, sampler, collections["field"])
    official_count = create_official_reference(context, sampler, collections["reference"])
    create_lighting(scene, collections["lighting"])

    overview = create_camera(
        "Camera_Gangnae_HQ_V10_Overview",
        (720.0, -1040.0, 690.0),
        (-30.0, 25.0, 18.0),
        52.0,
        collections["lighting"],
    )
    top = create_camera(
        "Camera_Gangnae_HQ_V10_Top",
        (0.0, 0.0, 1300.0),
        (0.0, 0.0, 0.0),
        50.0,
        collections["lighting"],
        orthographic=True,
    )
    field_camera = create_camera(
        "Camera_Gangnae_HQ_V10_Field",
        (330.0, -430.0, 310.0),
        (0.0, 0.0, sampler.z(0.0, 0.0) + 4.0),
        58.0,
        collections["lighting"],
    )
    engine = configure_render(scene)

    render(scene, overview, OVERVIEW_PATH)
    render(scene, top, TOP_PATH)
    render(scene, field_camera, FIELD_PATH)
    scene.camera = overview
    scene["v10_stage"] = "HQ GIS background stages 1-3 complete"
    scene["v10_blendergis_enabled"] = blendergis_enabled
    scene["v10_visible_water_source"] = "OpenStreetMap"
    scene["v10_official_river_reference_source"] = "VWorld UJ201/UJ301"
    scene["v10_v9_files_modified"] = False
    bpy.ops.wm.save_as_mainfile(filepath=str(BLEND_PATH))

    report = {
        "status": "ok",
        "scene": scene.name,
        "blend_path": str(BLEND_PATH),
        "render_engine": engine,
        "blender_version": bpy.app.version_string,
        "blendergis_enabled": blendergis_enabled,
        "georeference": {
            "crs": scene["SRID"],
            "origin_utm": [scene["crs x"], scene["crs y"]],
            "origin_wgs84": [scene["longitude"], scene["latitude"]],
            "scale": scene["scale"],
        },
        "objects": {
            "terrain": 1,
            "water": water_count,
            "roads": road_count,
            "bridges": bridge_count,
            "buildings": building_count,
            "registered_field": int(field is not None),
            "field_outline": int(field_outline is not None),
            "official_reference_boundaries": official_count,
        },
        "renders": [str(OVERVIEW_PATH), str(TOP_PATH), str(FIELD_PATH)],
        "aerial_texture": context["aerial"]["path"],
        "aerial_pixel_size": context["aerial"]["pixel_size"],
        "limitations": [
            "Terrain is SRTM approximately 30 m, not a national 1-5 m DEM/DSM.",
            "OSM building count can be zero where contributors have not mapped footprints.",
            "Official VWorld polygons are river-management reference zones, not current wetted water.",
            "This scene improves visual spatial context; it is not a hydraulic inundation computation.",
        ],
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
