#!/usr/bin/env python3
"""Resolve registered fields for trusted V23 trigger events."""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import re
from typing import Any, Dict, Iterable, List, Optional

from pyproj import Geod, Transformer
from shapely.geometry import Point, shape
from shapely.ops import transform

from v23_event_contract import validate_event


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY_PATH = ROOT / "data" / "v23" / "fields" / "field_registry_v23.json"
SAFE_ID = re.compile(r"^[A-Za-z0-9._:-]+$")
GEOD = Geod(ellps="WGS84")
TO_UTM52N = Transformer.from_crs("EPSG:4326", "EPSG:32652", always_xy=True)


class FieldRegistryError(ValueError):
    """Raised when field registry data or event ownership is invalid."""

    def __init__(self, errors: Iterable[str]):
        self.errors = list(errors)
        super().__init__("; ".join(self.errors))


def _valid_id(value: Any) -> bool:
    return isinstance(value, str) and 0 < len(value) <= 128 and SAFE_ID.fullmatch(value) is not None


def _distance_m(first: List[float], second: List[float]) -> float:
    return abs(GEOD.inv(first[0], first[1], second[0], second[1])[2])


def validate_registry(registry: Dict[str, Any]) -> Dict[str, Any]:
    """Validate IDs, ownership, polygons, metrics, and deferred asset bindings."""
    errors: List[str] = []
    if not isinstance(registry, dict):
        raise FieldRegistryError(["registry must be a JSON object"])
    if registry.get("schema_version") != "1.0":
        errors.append("schema_version must be 1.0")
    if registry.get("crs") != "EPSG:4326":
        errors.append("crs must be EPSG:4326")
    if not isinstance(registry.get("registry_id"), str) or not registry.get("registry_id"):
        errors.append("registry_id must be a non-empty string")

    fields = registry.get("fields")
    if not isinstance(fields, list) or not fields:
        errors.append("fields must be a non-empty array")
        fields = []

    seen_field_ids = set()
    seen_sources = set()
    for index, field in enumerate(fields):
        path = f"fields[{index}]"
        if not isinstance(field, dict):
            errors.append(f"{path} must be an object")
            continue
        field_id = field.get("field_id")
        owner_id = field.get("owner_user_id")
        if not _valid_id(field_id):
            errors.append(f"{path}.field_id is invalid")
        elif field_id in seen_field_ids:
            errors.append(f"duplicate field_id: {field_id}")
        else:
            seen_field_ids.add(field_id)
        if not _valid_id(owner_id):
            errors.append(f"{path}.owner_user_id is invalid")

        geometry = field.get("geometry")
        try:
            polygon = shape(geometry)
        except Exception as exc:
            errors.append(f"{path}.geometry cannot be parsed: {exc}")
            continue
        if polygon.geom_type != "Polygon" or polygon.is_empty or not polygon.is_valid:
            errors.append(f"{path}.geometry must be a non-empty valid Polygon")
            continue

        metrics = field.get("derived_metrics")
        if not isinstance(metrics, dict):
            errors.append(f"{path}.derived_metrics must be an object")
            continue
        centre = metrics.get("centre_wgs84")
        bounds = metrics.get("bounds_wgs84")
        area = metrics.get("area_m2")
        flood_area = metrics.get("official_flood_intersection_area_m2")
        flood_percent = metrics.get("official_flood_intersection_percent")
        flood_source = metrics.get("official_flood_intersection_source")
        if not isinstance(centre, list) or len(centre) != 2 or not all(isinstance(value, (int, float)) for value in centre):
            errors.append(f"{path}.derived_metrics.centre_wgs84 is invalid")
        else:
            centroid = polygon.centroid
            if _distance_m(centre, [centroid.x, centroid.y]) > 2.0:
                errors.append(f"{path}.derived_metrics.centre_wgs84 differs from polygon centroid")
            if not polygon.covers(Point(centre)):
                errors.append(f"{path}.derived_metrics.centre_wgs84 is outside the polygon")
        if not isinstance(bounds, list) or len(bounds) != 4:
            errors.append(f"{path}.derived_metrics.bounds_wgs84 is invalid")
        elif any(abs(float(actual) - float(expected)) > 1e-7 for actual, expected in zip(bounds, polygon.bounds)):
            errors.append(f"{path}.derived_metrics.bounds_wgs84 differs from polygon bounds")
        measured_area = transform(TO_UTM52N.transform, polygon).area
        if not isinstance(area, (int, float)) or area <= 0:
            errors.append(f"{path}.derived_metrics.area_m2 must be positive")
        elif abs(float(area) - measured_area) > max(5.0, measured_area * 0.005):
            errors.append(f"{path}.derived_metrics.area_m2 differs from projected polygon area")
        if not isinstance(flood_area, (int, float)) or flood_area < 0 or flood_area > measured_area + 5.0:
            errors.append(f"{path}.derived_metrics.official_flood_intersection_area_m2 is invalid")
        expected_percent = (float(flood_area) / measured_area * 100.0) if isinstance(flood_area, (int, float)) and measured_area else 0.0
        if not isinstance(flood_percent, (int, float)) or not 0 <= flood_percent <= 100:
            errors.append(f"{path}.derived_metrics.official_flood_intersection_percent is invalid")
        elif abs(float(flood_percent) - expected_percent) > 0.05:
            errors.append(f"{path}.derived_metrics official flood intersection values disagree")
        if not isinstance(flood_source, str) or not flood_source:
            errors.append(f"{path}.derived_metrics.official_flood_intersection_source is required")

        binding = field.get("asset_binding")
        if not isinstance(binding, dict):
            errors.append(f"{path}.asset_binding must be an object")
        else:
            for key in ("scene_zone_id", "scene_pack_id"):
                if not isinstance(binding.get(key), str) or not binding.get(key):
                    errors.append(f"{path}.asset_binding.{key} is required")
            if binding.get("preparation_status") not in {"pending", "ready", "failed"}:
                errors.append(f"{path}.asset_binding.preparation_status is invalid")

        shelter = field.get("shelter")
        if not isinstance(shelter, dict):
            errors.append(f"{path}.shelter must be an object")
        elif isinstance(centre, list) and len(centre) == 2:
            shelter_location = shelter.get("location_wgs84")
            if not isinstance(shelter_location, list) or len(shelter_location) != 2:
                errors.append(f"{path}.shelter.location_wgs84 is invalid")
            else:
                measured_distance = _distance_m(centre, shelter_location)
                stored_distance = shelter.get("distance_m")
                if not isinstance(stored_distance, (int, float)) or abs(stored_distance - measured_distance) > 2.0:
                    errors.append(f"{path}.shelter.distance_m differs from geodesic distance")

        source = field.get("source")
        if not isinstance(source, dict):
            errors.append(f"{path}.source must be an object")
        else:
            source_key = (source.get("provider"), source.get("element_type"), source.get("element_id"))
            if source_key in seen_sources:
                errors.append(f"{path}.source duplicates another field source")
            seen_sources.add(source_key)

    if errors:
        raise FieldRegistryError(errors)
    return deepcopy(registry)


class FieldRegistry:
    """Read-only field lookup with event ownership enforcement."""

    def __init__(self, registry: Dict[str, Any]):
        validated = validate_registry(registry)
        self.registry_id = validated["registry_id"]
        self._fields = {item["field_id"]: item for item in validated["fields"]}

    @classmethod
    def load(cls, path: Path = DEFAULT_REGISTRY_PATH) -> "FieldRegistry":
        return cls(json.loads(path.read_text(encoding="utf-8")))

    def get(self, field_id: str) -> Dict[str, Any]:
        try:
            return deepcopy(self._fields[field_id])
        except KeyError as exc:
            raise FieldRegistryError([f"unknown field_id: {field_id}"]) from exc

    def for_user(self, user_id: str) -> List[Dict[str, Any]]:
        return [deepcopy(item) for item in self._fields.values() if item["owner_user_id"] == user_id]

    def resolve_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        accepted = validate_event(event)
        field = self.get(accepted["field_id"])
        if field["owner_user_id"] != accepted["user_id"]:
            raise FieldRegistryError([
                f"event user_id {accepted['user_id']} does not own field_id {accepted['field_id']}"
            ])
        if field["registration_status"] == "disabled":
            raise FieldRegistryError([f"field_id {accepted['field_id']} is disabled"])
        return field


def main() -> None:
    parser = argparse.ArgumentParser(description="Resolve a V23 registered field")
    parser.add_argument("field_id")
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY_PATH)
    args = parser.parse_args()
    field = FieldRegistry.load(args.registry).get(args.field_id)
    print(json.dumps({
        "status": "resolved",
        "field_id": field["field_id"],
        "owner_user_id": field["owner_user_id"],
        "centre_wgs84": field["derived_metrics"]["centre_wgs84"],
        "area_m2": field["derived_metrics"]["area_m2"],
        "scene_pack_id": field["asset_binding"]["scene_pack_id"],
        "preparation_status": field["asset_binding"]["preparation_status"],
        "shelter": field["shelter"]["name"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
