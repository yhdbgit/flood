"""Refined visual pass for Gangnae HQ V10.

The aerial image remains the primary visual source.  Vector layers stay in the
scene for inspection and future animation, but use restrained transparency so
they do not paint over the real-world imagery.
"""

from pathlib import Path
import sys

import bpy


ROOT = Path("/Users/hyeokjae/Desktop/ICTCB/flood")
sys.path.insert(0, str(ROOT / "blender"))
import build_gangnae_hq_v10 as base


def create_water(context, sampler, collection):
    material = base.new_material(
        "V10_Mat_Water", (0.01, 0.19, 0.34), roughness=0.22, metallic=0.08, alpha=0.52
    )
    count = 0
    for index, item in enumerate(context["water_polygons"]):
        obj = base.polygon_mesh(
            f"WaterPolygon_{index:03d}", item["polygon"], sampler, collection, material, 0.48
        )
        if obj:
            obj["source"] = "OpenStreetMap"
            obj["osm_id"] = item["osm_id"]
            obj["water_type"] = item["water"] or "water"
            count += 1
    for index, item in enumerate(context["waterways"]):
        obj = base.strip_mesh(
            f"Waterway_{index:03d}", item["path"], float(item["width_m"]),
            sampler, collection, material, 0.5
        )
        if obj:
            obj["source"] = "OpenStreetMap"
            obj["osm_id"] = item["osm_id"]
            obj["waterway"] = item["waterway"]
            count += 1
    return count


def create_roads(context, sampler, collection):
    major = base.new_material("V10_Mat_RoadMajor", (0.22, 0.23, 0.24), 0.92, alpha=0.18)
    minor = base.new_material("V10_Mat_RoadMinor", (0.32, 0.31, 0.28), 0.96, alpha=0.10)
    bridge = base.new_material("V10_Mat_Bridge", (0.52, 0.54, 0.57), 0.82, alpha=0.26)
    major_types = {"motorway", "trunk", "primary", "secondary", "tertiary"}
    count = 0
    bridge_count = 0
    for index, item in enumerate(context["roads"]):
        is_bridge = bool(item["bridge"])
        material = bridge if is_bridge else major if item["highway"] in major_types else minor
        obj = base.strip_mesh(
            f"Road_{index:03d}_{item['highway']}", item["path"], float(item["width_m"]),
            sampler, collection, material, 0.65 if is_bridge else 0.28
        )
        if obj:
            obj["source"] = "OpenStreetMap"
            obj["osm_id"] = item["osm_id"]
            obj["highway"] = item["highway"]
            obj["bridge"] = is_bridge
            count += 1
            bridge_count += int(is_bridge)
    return count, bridge_count


def create_field(context, sampler, collection):
    field = context["field"]
    fill = base.new_material("V10_Mat_FieldFill", (0.62, 0.92, 0.10), 0.5, alpha=0.10)
    border = base.new_material("V10_Mat_FieldBorder", (0.95, 0.98, 0.12), 0.38, alpha=0.92)
    obj = base.polygon_mesh("RegisteredField_V10", field["polygon"], sampler, collection, fill, 0.85)
    boundary = field["polygon"] + [field["polygon"][0]]
    outline = base.strip_mesh(
        "RegisteredFieldBoundary_V10", boundary, 2.2, sampler, collection, border, 1.05
    )
    for item in (obj, outline):
        if item:
            item["field_id"] = field["field_id"]
            item["geometry_accuracy"] = field["geometry_accuracy"]
            item["area_m2"] = field["area_m2"]
    return obj, outline


def create_official_reference(context, sampler, collection):
    material = base.new_material(
        "V10_Mat_OfficialRiverBoundary", (0.0, 0.68, 0.92), 0.5, alpha=0.32
    )
    count = 0
    for zone in context["official_river_reference"]:
        for index, item in enumerate(zone["polygons"]):
            boundary = item["exterior"] + [item["exterior"][0]]
            obj = base.strip_mesh(
                f"OfficialBoundary_{zone['id']}_{index}", boundary, 0.8,
                sampler, collection, material, 0.75
            )
            if obj:
                obj["source"] = "VWorld"
                obj["source_layer"] = zone["source_layer"]
                obj["zone_name"] = zone["name"]
                obj["meaning"] = "river management reference boundary, not current water surface"
                count += 1
    return count


base.create_water = create_water
base.create_roads = create_roads
base.create_field = create_field
base.create_official_reference = create_official_reference
base.main()
