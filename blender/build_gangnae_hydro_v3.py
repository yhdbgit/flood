"""Build Gangnae hydro digital-twin v3 with terrain-draped flat geometry.

Run with:
  Blender --background blender/gangnae_terrain_v1.blend \
    --python blender/build_gangnae_hydro_v3.py

V3 intentionally separates three concepts:
* official river-management zones: translucent terrain-draped polygons,
* visible water: flat ribbons derived from centreline and display width,
* water-level observations: compact map pins and object metadata.

The official UJ201/UJ301 polygons are not presented as the actual wetted area.
"""

from array import array
import json
import math
from pathlib import Path
import sys

import bpy
from mathutils import Euler, Vector
from mathutils.geometry import tessellate_polygon


ROOT = Path("/Users/hyeokjae/Desktop/ICTCB/flood")
GEOMETRY_PATH = ROOT / "data" / "processed" / "gangnae_hydro_geometry.json"
SNAPSHOT_PATH = ROOT / "data" / "runtime" / "hydro_snapshot.json"
HGT_PATH = ROOT / "data" / "terrain" / "N36E127.hgt"
BLEND_PATH = ROOT / "blender" / "gangnae_hydro_v3.blend"
REPORT_PATH = ROOT / "output" / "hydro_v3_validation_report.json"
PREVIEW_PATH = ROOT / "output" / "gangnae_hydro_v3_preview.png"
TOP_PATH = ROOT / "output" / "gangnae_hydro_v3_top.png"
LOW_PATH = ROOT / "output" / "gangnae_hydro_v3_low.png"

COLLECTION_NAME = "DT_HYDRO_V3"
CAMERA_NAME = "Camera_Gangnae_Hydro_V3"
FONT_PATH = Path("/System/Library/Fonts/AppleSDGothicNeo.ttc")

HGT_GRID_SIZE = 3601
HGT_TILE_WEST = 127.0
HGT_TILE_SOUTH = 36.0

RISK_COLOURS = {
    "normal": (0.025, 0.25, 0.82, 1.0),
    "attention": (0.95, 0.60, 0.03, 1.0),
    "warning": (1.0, 0.25, 0.015, 1.0),
    "alarm": (0.78, 0.02, 0.01, 1.0),
    "serious": (0.40, 0.0, 0.0, 1.0),
    "unknown": (0.25, 0.28, 0.32, 1.0),
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
    for collection_name in ("DT_HYDRO_V2", COLLECTION_NAME):
        old = bpy.data.collections.get(collection_name)
        if old is None:
            continue
        for obj in list(old.objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        for parent in list(bpy.data.collections):
            if old.name in parent.children:
                parent.children.unlink(old)
        if old.name in scene.collection.children:
            scene.collection.children.unlink(old)
        bpy.data.collections.remove(old)

    collection = bpy.data.collections.new(COLLECTION_NAME)
    scene.collection.children.link(collection)
    scene.name = "Gangnae_Hydro_V3"
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.length_unit = "METERS"
    scene.unit_settings.scale_length = 1.0
    return scene, collection


def material(name, colour, roughness=0.55, metallic=0.0, alpha=1.0, emission=0.0):
    existing = bpy.data.materials.get(name)
    if existing is not None:
        bpy.data.materials.remove(existing, do_unlink=True)
    item = bpy.data.materials.new(name)
    rgba = (colour[0], colour[1], colour[2], alpha)
    item.diffuse_color = rgba
    item.use_nodes = True
    nodes = item.node_tree.nodes
    links = item.node_tree.links
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    shader = nodes.new("ShaderNodeBsdfPrincipled")
    shader.inputs["Base Color"].default_value = rgba
    shader.inputs["Roughness"].default_value = roughness
    shader.inputs["Metallic"].default_value = metallic
    if shader.inputs.get("Alpha") is not None:
        shader.inputs["Alpha"].default_value = alpha
    if shader.inputs.get("Emission Color") is not None:
        shader.inputs["Emission Color"].default_value = rgba
        shader.inputs["Emission Strength"].default_value = emission
    elif shader.inputs.get("Emission") is not None:
        shader.inputs["Emission"].default_value = rgba
    links.new(shader.outputs["BSDF"], output.inputs["Surface"])
    if alpha < 1.0:
        try:
            item.surface_render_method = "DITHERED"
        except (AttributeError, TypeError):
            try:
                item.blend_method = "BLEND"
            except (AttributeError, TypeError):
                pass
        item.use_transparency_overlap = False
    return item


def local_to_lonlat(x, y, geometry):
    origin_lon, origin_lat = geometry["origin_wgs84"]
    scale = geometry["metres_per_degree"]
    return origin_lon + x / scale["longitude"], origin_lat + y / scale["latitude"]


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
    terrain = geometry["terrain"]
    return (
        (sample_elevation(values, lon, lat) - terrain["elevation_min_m"])
        * terrain["vertical_exaggeration"]
        + extra
    )


def move_to_collection(obj, collection):
    for current in list(obj.users_collection):
        current.objects.unlink(obj)
    collection.objects.link(obj)


def point_at(obj, target):
    obj.rotation_euler = (Vector(target) - obj.location).to_track_quat("-Z", "Y").to_euler()


def clean_path(path):
    points = [(float(point[0]), float(point[1])) for point in path]
    if len(points) > 1 and points[0] == points[-1]:
        points.pop()
    return points


def point_in_polygon(x, y, polygon):
    inside = False
    previous = polygon[-1]
    for current in polygon:
        x1, y1 = current
        x2, y2 = previous
        crosses = (y1 > y) != (y2 > y)
        if crosses:
            intersection_x = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x < intersection_x:
                inside = not inside
        previous = current
    return inside


def create_draped_polygon(name, polygon, collection, polygon_material, values, geometry, z_offset):
    exterior = clean_path(polygon["exterior"])
    boundary = [Vector((x, y)) for x, y in exterior]
    min_x = min(x for x, _ in exterior)
    max_x = max(x for x, _ in exterior)
    min_y = min(y for _, y in exterior)
    max_y = max(y for _, y in exterior)
    terrain_obj = bpy.data.objects.get("Terrain_Gangnae")
    if terrain_obj is None:
        raise RuntimeError("Terrain_Gangnae is missing")
    world = terrain_obj.matrix_world
    source_mesh = terrain_obj.data
    vertices = []
    faces = []
    vertex_map = {}
    for source_face in source_mesh.polygons:
        centre = world @ source_face.center
        if not (min_x <= centre.x <= max_x and min_y <= centre.y <= max_y):
            continue
        if not point_in_polygon(centre.x, centre.y, exterior):
            continue
        face_indices = []
        for source_index in source_face.vertices:
            if source_index not in vertex_map:
                coordinate = world @ source_mesh.vertices[source_index].co
                vertex_map[source_index] = len(vertices)
                vertices.append((coordinate.x, coordinate.y, coordinate.z + z_offset))
            face_indices.append(vertex_map[source_index])
        faces.append(face_indices)
    if not faces:
        vectors_2d = [Vector((x, y)) for x, y in exterior]
        triangles = tessellate_polygon([vectors_2d])
        key_to_index = {(round(v.x, 6), round(v.y, 6)): index for index, v in enumerate(vectors_2d)}
        for triangle in triangles:
            if triangle and isinstance(triangle[0], int):
                face = list(triangle)
            else:
                face = [key_to_index[(round(v.x, 6), round(v.y, 6))] for v in triangle]
            if len(set(face)) == 3:
                faces.append(face)
        vertices = [
            (x, y, terrain_z(values, x, y, geometry, z_offset))
            for x, y in exterior
        ]
    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    obj.data.materials.append(polygon_material)
    obj["terrain_face_count"] = len(faces)
    return obj


def densify_path(points, max_step=28.0):
    if len(points) < 2:
        return points
    dense = [points[0]]
    for start, end in zip(points, points[1:]):
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        distance = math.hypot(dx, dy)
        steps = max(1, math.ceil(distance / max_step))
        for step in range(1, steps + 1):
            ratio = step / steps
            dense.append((start[0] + dx * ratio, start[1] + dy * ratio))
    return dense


def path_normals(points, closed):
    normals = []
    count = len(points)
    for index in range(count):
        if closed:
            previous = points[(index - 1) % count]
            following = points[(index + 1) % count]
        else:
            previous = points[max(0, index - 1)]
            following = points[min(count - 1, index + 1)]
        tangent = Vector((following[0] - previous[0], following[1] - previous[1]))
        if tangent.length < 1e-6:
            tangent = Vector((1.0, 0.0))
        tangent.normalize()
        normals.append(Vector((-tangent.y, tangent.x)))
    return normals


def create_flat_strips(
    name,
    paths,
    collection,
    strip_material,
    values,
    geometry,
    width,
    z_offset,
    closed=False,
):
    vertices = []
    faces = []
    half = width / 2.0
    for raw_path in paths:
        points = densify_path(clean_path(raw_path))
        if len(points) < 2:
            continue
        is_closed = closed or (len(raw_path) > 2 and raw_path[0] == raw_path[-1])
        normals = path_normals(points, is_closed)
        centre_heights = [terrain_z(values, x, y, geometry, z_offset) for x, y in points]
        smoothed_heights = []
        for index in range(len(centre_heights)):
            start = max(0, index - 3)
            end = min(len(centre_heights), index + 4)
            smoothed_heights.append(sum(centre_heights[start:end]) / (end - start))
        base = len(vertices)
        for (x, y), normal, height in zip(points, normals, smoothed_heights):
            left = (x + normal.x * half, y + normal.y * half)
            right = (x - normal.x * half, y - normal.y * half)
            left_floor = terrain_z(values, left[0], left[1], geometry, z_offset)
            right_floor = terrain_z(values, right[0], right[1], geometry, z_offset)
            surface_height = max(height, left_floor, right_floor)
            vertices.append((left[0], left[1], surface_height))
            vertices.append((right[0], right[1], surface_height))
        segment_count = len(points) if is_closed else len(points) - 1
        for index in range(segment_count):
            following = (index + 1) % len(points)
            faces.append(
                (
                    base + index * 2,
                    base + following * 2,
                    base + following * 2 + 1,
                    base + index * 2 + 1,
                )
            )
    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    for polygon in mesh.polygons:
        polygon.use_smooth = True
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    obj.data.materials.append(strip_material)
    return obj


def zone_paths(zone):
    result = []
    for polygon in zone["polygons"]:
        result.append(polygon["exterior"])
        result.extend(polygon["holes"])
    return result


def create_camera(scene, collection):
    camera_data = bpy.data.cameras.new(f"{CAMERA_NAME}_Data")
    camera = bpy.data.objects.new(CAMERA_NAME, camera_data)
    collection.objects.link(camera)
    camera_data.sensor_width = 36.0
    camera_data.clip_start = 1.0
    camera_data.clip_end = 100_000.0
    scene.camera = camera
    return camera


def create_station_pin(name, x, y, collection, pin_material, values, geometry):
    ground = terrain_z(values, x, y, geometry, 1.8)
    bpy.ops.mesh.primitive_cone_add(
        vertices=24,
        radius1=5.0,
        radius2=13.0,
        depth=28.0,
        location=(x, y, ground + 14.0),
    )
    pointer = bpy.context.object
    pointer.name = f"{name}_Pointer"
    move_to_collection(pointer, collection)
    pointer.data.materials.append(pin_material)

    bpy.ops.mesh.primitive_uv_sphere_add(
        segments=24,
        ring_count=12,
        radius=13.0,
        location=(x, y, ground + 36.0),
    )
    head = bpy.context.object
    head.name = name
    move_to_collection(head, collection)
    head.data.materials.append(pin_material)
    return head, pointer


def create_map_text(name, body, location, size, collection, text_material, font):
    data = bpy.data.curves.new(f"{name}_Text", type="FONT")
    data.body = body
    data.align_x = "CENTER"
    data.align_y = "CENTER"
    data.size = size
    data.extrude = 0.0
    data.offset = 0.01
    if font is not None:
        data.font = font
    obj = bpy.data.objects.new(name, data)
    collection.objects.link(obj)
    obj.location = location
    obj.data.materials.append(text_material)
    obj.show_in_front = True
    return obj


def clamp_station_to_scene(station, geometry):
    origin_lon, origin_lat = geometry["origin_wgs84"]
    scale = geometry["metres_per_degree"]
    x = (station["longitude"] - origin_lon) * scale["longitude"]
    y = (station["latitude"] - origin_lat) * scale["latitude"]
    width, depth, _ = geometry["terrain"]["dimensions_m"]
    margin = 320.0
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
    scene.render.film_transparent = False
    scene.view_settings.look = "AgX - Medium High Contrast"
    return scene.render.engine


def render_view(scene, camera, output_path, location, target, lens):
    camera.location = location
    camera.data.lens = lens
    point_at(camera, target)
    scene.render.filepath = str(output_path)
    bpy.ops.render.render(write_still=True)
    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise RuntimeError(f"Render was not generated: {output_path}")


def configure_saved_viewport(terrain_dimensions):
    width, depth, _ = terrain_dimensions
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type != "VIEW_3D":
                continue
            space = area.spaces.active
            space.clip_start = 1.0
            space.clip_end = 100_000.0
            region = space.region_3d
            region.view_location = (0.0, 0.0, 80.0)
            region.view_distance = max(width, depth) * 0.82
            region.view_rotation = Euler(
                (math.radians(58.0), 0.0, math.radians(32.0)), "XYZ"
            ).to_quaternion()
            region.view_perspective = "PERSP"


def main():
    geometry = load_json(GEOMETRY_PATH)
    snapshot = load_json(SNAPSHOT_PATH)
    values = read_hgt()
    scene, collection = prepare_scene()
    camera = create_camera(scene, collection)
    engine = configure_render(scene)

    risk_code = snapshot["scene_state"]["risk"]["code"]
    water_colour = RISK_COLOURS.get(risk_code, RISK_COLOURS["unknown"])
    water_material = material(
        "Material_V3_WaterSurface", water_colour, roughness=0.20, metallic=0.08, emission=0.04
    )
    main_zone_fill = material(
        "Material_V3_MainZoneFill", (0.02, 0.58, 0.95, 1.0), roughness=0.70, alpha=0.10
    )
    small_zone_fill = material(
        "Material_V3_SmallZoneFill", (0.02, 0.85, 0.55, 1.0), roughness=0.72, alpha=0.07
    )
    main_boundary = material(
        "Material_V3_MainZoneBoundary", (0.12, 0.72, 1.0, 1.0), roughness=0.50, emission=0.12
    )
    small_boundary = material(
        "Material_V3_SmallZoneBoundary", (0.08, 0.92, 0.58, 1.0), roughness=0.55, emission=0.08
    )
    pin_material = material(
        "Material_V3_StationPin", (1.0, 0.12, 0.025, 1.0), roughness=0.36, emission=0.12
    )
    text_material = material(
        "Material_V3_MapText", (0.92, 0.97, 1.0, 1.0), roughness=0.62, emission=0.20
    )

    zone_fills = []
    zone_boundaries = []
    for zone in geometry["official_zones"]:
        is_main = zone["source_layer"] == "UJ201"
        for polygon_index, polygon in enumerate(zone["polygons"], start=1):
            fill = create_draped_polygon(
                f"ZoneFill_{zone['name']}_{polygon_index}",
                polygon,
                collection,
                main_zone_fill if is_main else small_zone_fill,
                values,
                geometry,
                z_offset=2.4 if is_main else 1.8,
            )
            fill["source_layer"] = zone["source_layer"]
            fill["display_role"] = "official_management_zone_fill"
            fill["is_actual_water_surface"] = False
            zone_fills.append(fill)
        boundary = create_flat_strips(
            f"ZoneBoundary_{zone['name']}",
            zone_paths(zone),
            collection,
            main_boundary if is_main else small_boundary,
            values,
            geometry,
            width=5.0 if is_main else 2.6,
            z_offset=3.0 if is_main else 2.3,
            closed=True,
        )
        boundary["source_layer"] = zone["source_layer"]
        boundary["display_role"] = "official_management_zone_boundary"
        zone_boundaries.append(boundary)

    level_delta = snapshot["scene_state"].get("visual_level_delta_m", 0.0)
    vertical_scale = geometry["terrain"]["vertical_exaggeration"]
    water_objects = []
    for centreline in geometry["centerlines"]:
        is_main = centreline["name"] == "미호강"
        water = create_flat_strips(
            f"WaterSurface_{centreline['name']}",
            centreline["parts"],
            collection,
            water_material,
            values,
            geometry,
            width=centreline["visual_width_m"],
            z_offset=3.8 + (level_delta * vertical_scale if is_main else 0.0),
            closed=False,
        )
        water["source"] = centreline["source"]
        water["source_name"] = centreline["source_name"]
        water["display_role"] = "visual_water_surface_ribbon"
        water["visual_width_m"] = centreline["visual_width_m"]
        water["hydraulic_simulation"] = False
        water_objects.append(water)

    font = None
    if FONT_PATH.is_file():
        try:
            font = bpy.data.fonts.load(str(FONT_PATH), check_existing=True)
        except RuntimeError:
            font = None

    station_objects = []
    for station in snapshot["stations"]:
        x, y, external = clamp_station_to_scene(station, geometry)
        head, pointer = create_station_pin(
            f"StationPin_{station['code']}", x, y, collection, pin_material, values, geometry
        )
        for obj in (head, pointer):
            obj["station_code"] = station["code"]
            obj["station_name"] = station["name"]
            obj["water_level_m"] = station["water_level_m"]
            obj["flow_m3s"] = station["flow_m3s"]
            obj["risk_stage"] = station["risk"]["label"]
            obj["outside_terrain_bounds"] = external
            obj["display_role"] = "observation_station_pin"
        station_objects.append(head)
        label_z = terrain_z(values, x, y, geometry, 4.5)
        create_map_text(
            f"MapLabel_Station_{station['code']}",
            station["name"],
            (x + 62.0, y + 38.0, label_z),
            27.0,
            collection,
            text_material,
            font,
        )

    for centreline in geometry["centerlines"]:
        longest = max(centreline["parts"], key=len)
        x, y = longest[len(longest) // 2]
        create_map_text(
            f"MapLabel_River_{centreline['name']}",
            centreline["name"],
            (x, y, terrain_z(values, x, y, geometry, 7.0)),
            42.0 if centreline["name"] == "미호강" else 27.0,
            collection,
            text_material,
            font,
        )

    width, depth, height = geometry["terrain"]["dimensions_m"]
    target = (0.0, 0.0, max(55.0, height * 0.18))
    render_view(
        scene,
        camera,
        PREVIEW_PATH,
        (width * 0.10, -depth * 1.72, width * 1.06),
        target,
        52.0,
    )
    render_view(
        scene,
        camera,
        TOP_PATH,
        (0.0, -depth * 0.05, width * 1.58),
        (0.0, 0.0, 30.0),
        55.0,
    )
    render_view(
        scene,
        camera,
        LOW_PATH,
        (-width * 0.78, -depth * 1.18, width * 0.42),
        (0.0, 0.0, 75.0),
        52.0,
    )

    camera.location = (width * 0.10, -depth * 1.72, width * 1.06)
    camera.data.lens = 52.0
    point_at(camera, target)
    configure_saved_viewport(geometry["terrain"]["dimensions_m"])

    terrain = bpy.data.objects.get("Terrain_Gangnae")
    bpy.ops.object.select_all(action="DESELECT")
    if terrain is not None:
        terrain.select_set(True)
        bpy.context.view_layer.objects.active = terrain

    bpy.ops.wm.save_as_mainfile(filepath=str(BLEND_PATH))
    report = {
        "status": "ok",
        "scene": scene.name,
        "collection": collection.name,
        "representation": {
            "official_zones": "terrain-draped translucent polygon meshes",
            "zone_boundaries": "flat terrain-draped mesh strips",
            "visible_water": "flat terrain-draped centreline ribbons",
            "stations": "compact cone-and-sphere map pins",
        },
        "official_zone_fill_count": len(zone_fills),
        "official_zone_boundary_count": len(zone_boundaries),
        "water_surface_count": len(water_objects),
        "station_count": len(station_objects),
        "tube_curve_count": len(
            [
                obj
                for obj in collection.objects
                if obj.type == "CURVE" and getattr(obj.data, "bevel_depth", 0.0) > 0.0
            ]
        ),
        "render_engine": engine,
        "renders": {
            "overview": {"path": str(PREVIEW_PATH), "bytes": PREVIEW_PATH.stat().st_size},
            "top": {"path": str(TOP_PATH), "bytes": TOP_PATH.stat().st_size},
            "low": {"path": str(LOW_PATH), "bytes": LOW_PATH.stat().st_size},
        },
        "blend_path": str(BLEND_PATH),
        "blend_bytes": BLEND_PATH.stat().st_size,
        "api_key_in_scene": False,
        "limitations": [
            "UJ201/UJ301 meshes are legal or management zones, not actual wetted surfaces.",
            "Water ribbons use centreline display widths and are not surveyed river-bank polygons.",
            "Gauge-level motion remains a relative visualization, not a hydraulic simulation.",
        ],
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("[hydro-v3] build complete")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
