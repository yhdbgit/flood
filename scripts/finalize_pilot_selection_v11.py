#!/usr/bin/env python3
"""Apply visual and operational adjudication to the V11 pilot screening."""

import json
import math
from pathlib import Path

from pyproj import Transformer


ROOT = Path("/Users/hyeokjae/Desktop/ICTCB/flood")
CANDIDATES_PATH = ROOT / "output" / "pilot_selection_v11" / "pilot_candidates.json"
SNAPSHOT_PATH = ROOT / "data" / "runtime" / "hydro_snapshot.json"
CONFIG_PATH = ROOT / "config" / "pilot_area_v11.json"
FINAL_JSON = ROOT / "output" / "pilot_selection_v11" / "final_selection.json"
FINAL_MD = ROOT / "output" / "pilot_selection_v11" / "final_selection.md"

FINAL_ID = "C19"
TO_UTM = Transformer.from_crs("EPSG:4326", "EPSG:32652", always_xy=True)
TO_WGS = Transformer.from_crs("EPSG:32652", "EPSG:4326", always_xy=True)


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    candidates = load(CANDIDATES_PATH)
    snapshot = load(SNAPSHOT_PATH)
    selected = next(item for item in candidates["top_candidates"] if item["id"] == FINAL_ID)
    centre_x, centre_y = selected["centre_utm52n"]
    stations = []
    for station in snapshot["stations"]:
        x, y = TO_UTM.transform(station["longitude"], station["latitude"])
        stations.append({
            "code": station["code"],
            "name": station["name"],
            "role": station["role"],
            "is_flood_forecast_station": station["is_flood_forecast_station"],
            "distance_m": round(math.hypot(centre_x - x, centre_y - y), 1),
        })
    stations.sort(key=lambda item: item["distance_m"])

    # The aerial image shows contiguous cultivated plots in the northern half.
    # This is a field-search zone, not a registered/cadastral parcel.
    west, south = TO_WGS.transform(centre_x - 450, centre_y + 80)
    east, north = TO_WGS.transform(centre_x + 320, centre_y + 460)
    field_search_bounds = [west, south, east, north]

    final = {
        "schema_version": "1.0",
        "selection_status": "final_pilot_aoi_selected_field_pending",
        "pilot_id": "OSONG-MIHO-AGRI-V11",
        "display_name": "청주시 오송읍 미호강 하류 농경지 파일럿",
        "selected_candidate_id": FINAL_ID,
        "centre_wgs84": selected["centre_wgs84"],
        "centre_utm52n": selected["centre_utm52n"],
        "aoi_bounds_wgs84": selected["aoi_bounds_wgs84"],
        "aoi_size_m": [1000.0, 1000.0],
        "administrative_area": {
            "town": "오송읍",
            "borough": "흥덕구",
            "city": "청주시",
            "province": "충청북도",
            "verification": "OpenStreetMap Nominatim reverse check for centre and northern field zone",
        },
        "river": "미호강",
        "metrics": selected["metrics"],
        "water_level_stations": {
            "nearest": stations[0],
            "upstream_flood_forecast_reference": next(
                item for item in stations if item["is_flood_forecast_station"]
            ),
        },
        "representative_field": {
            "status": "not_selected",
            "do_not_reuse": "config/mvp_farmland.json",
            "search_zone_bounds_wgs84": field_search_bounds,
            "requirement": "select a visible cultivated parcel, then replace with user registration or cadastral geometry",
        },
        "selection_reasons": [
            "Wide contiguous cultivated land is visible on the Chungbuk/Osong north bank.",
            "The Miho River is directly adjacent and crosses the same 1 km scene.",
            "No motorway crosses the AOI.",
            "The 25-point SRTM elevation range is 13 m, the flattest shortlisted site.",
            "HRFCO station 3011685 is approximately 956 m away.",
            "The site remains in Cheongju, Chungcheongbuk-do despite the cross-river station name.",
        ],
        "rejected_automatic_winner": {
            "candidate_id": "C02",
            "reason": "bridge, rail and road infrastructure dominate the frame and farmland occupies only a small edge",
        },
        "limitations": [
            "OSM farmland is land-cover reference data, not cadastral ownership geometry.",
            "Station 3011685 is not itself a flood-forecast station; use upstream station 3011665 as an additional forecast reference.",
            "The archived 50-year PNG is a local-river layer and is excluded from Miho national-river inundation claims.",
        ],
        "source_candidates": str(CANDIDATES_PATH),
        "evaluation_image": selected["evaluation_image"],
    }
    CONFIG_PATH.write_text(json.dumps(final, ensure_ascii=False, indent=2), encoding="utf-8")
    FINAL_JSON.write_text(json.dumps(final, ensure_ascii=False, indent=2), encoding="utf-8")
    FINAL_MD.write_text(
        "\n".join(
            [
                "# V11 최종 파일럿 선정",
                "",
                f"- 최종 위치: **{final['display_name']}**",
                f"- 후보 ID: `{FINAL_ID}`",
                f"- 중심좌표: `{selected['centre_wgs84'][0]:.7f}, {selected['centre_wgs84'][1]:.7f}`",
                f"- 최근접 수위관측소: `{stations[0]['name']} ({stations[0]['code']})`, 약 {stations[0]['distance_m']:.0f}m",
                f"- 보조 홍수예보 관측소: `{final['water_level_stations']['upstream_flood_forecast_reference']['name']} ({final['water_level_stations']['upstream_flood_forecast_reference']['code']})`",
                f"- 농경지 참고 비율: `{selected['metrics']['farmland_percent']:.1f}%`",
                f"- 미호강 길이: `{selected['metrics']['river_length_m']:.0f}m`",
                f"- 고속도로 길이: `{selected['metrics']['motorway_length_m']:.0f}m`",
                f"- 표고차: `{selected['metrics']['elevation_range_m']}m`",
                "",
                "자동 점수 1위 C02는 교량·철도·도로가 화면을 지배하므로 시각 검토에서 제외했다. C19는 충북 오송읍 북측에 연속 농경지가 있고 미호강과 맞닿아 있어 농업 홍수 범람 시연에 가장 적합하다.",
                "",
                "현재 확정한 것은 1km 파일럿 지형이다. 실제 대표 농경지 경계는 아직 확정하지 않았으며 기존 `config/mvp_farmland.json`은 재사용하지 않는다.",
            ]
        ),
        encoding="utf-8",
    )
    print(json.dumps({
        "status": "ok",
        "selected": FINAL_ID,
        "display_name": final["display_name"],
        "centre_wgs84": final["centre_wgs84"],
        "nearest_station": stations[0],
        "config": str(CONFIG_PATH),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
