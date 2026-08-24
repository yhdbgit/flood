"""V13 four-agent flood guidance workflow with parallel TTS generation."""

import asyncio
import json
import os
from pathlib import Path
import subprocess
from time import perf_counter
from typing import Any, Dict, List

from dotenv import load_dotenv
from langgraph.graph import END, START, StateGraph
from openai import AsyncOpenAI
from PIL import Image, ImageDraw, ImageFont
from typing_extensions import TypedDict

ROOT = Path("/Users/hyeokjae/Desktop/ICTCB/flood")
INPUT_PATH = ROOT / "config" / "osong_guidance_input_v13.json"
INUNDATION_PATH = ROOT / "data" / "processed" / "osong_official_inundation_v13.json"
COMPOSER = ROOT / "blender" / "compose_guidance_video_v13.py"
BLENDER = Path("/Applications/Blender.app/Contents/MacOS/Blender")
OUT = ROOT / "output" / "guidance_v13"
ASSETS = OUT / "visuals"
AUDIO = OUT / "audio"
BASE_VIDEO = OUT / "osong_story_v13_base.mp4"
FINAL_VIDEO = OUT / "osong_guidance_v13_64s.mp4"
MANIFEST_PATH = OUT / "guidance_manifest.json"
STATE_PATH = OUT / "workflow_final_state.json"
SCRIPT_PATH = OUT / "narration_script.txt"
SRT_PATH = OUT / "guidance_subtitles.srt"
GRAPH_PATH = OUT / "langgraph_structure.mmd"
FONT_PATH = Path("/System/Library/Fonts/AppleSDGothicNeo.ttc")
ROADS_PATH = ROOT / "data/gis/osong_v13/osm_roads.json"
ROUTE_PATH = ROOT / "data/processed/osong_shelter_route_v13.geojson"
FIELD_CONFIG_PATH = ROOT / "config/osong_farmland_v11.json"
FPS = 24


class StoryState(TypedDict, total=False):
    run_id: str
    input_data: Dict[str, Any]
    field_result: Dict[str, Any]
    segments: List[Dict[str, Any]]
    visual_assets: Dict[str, str]
    tts_assets: Dict[str, Dict[str, Any]]
    tts_meta: Dict[str, Any]
    manifest: Dict[str, Any]
    final_video: str
    trace: List[Dict[str, Any]]


def read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def traced(state: StoryState, node: str, detail: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [*state.get("trace", []), {"node": node, "status": "ok", **detail}]


def script_agent(state: StoryState) -> Dict[str, Any]:
    """Load official inputs and create the complete narration timeline."""
    data = read_json(INPUT_PATH)
    official = read_json(INUNDATION_PATH)
    affected = official["field"]["official_flood_affected_percent"]
    shelter = official["shelter"]
    route = official["route"]
    segments = [
        {
            "id": "wide_official_flood", "start_frame": 1, "end_frame": 480,
            "title": "환경부 100년 빈도 침수예상 범위",
            "subtitle": "미호강 주변 저지대 · 수위 단계당 2초",
            "narration": "환경부 국가하천 100년 빈도 홍수위험지도에 따르면, 미호강 주변 저지대로 침수 범위가 확산될 수 있습니다. 물의 확산은 한 단계에 이 초씩 천천히 표시됩니다. 대상 농경지는 하천과 가까워 비가 시작되기 전에 준비를 마쳐야 합니다.",
            "visual_type": "overlay",
        },
        {
            "id": "zoom_registered_field", "start_frame": 481, "end_frame": 576,
            "title": "등록 농경지 확대",
            "subtitle": "오송읍 미호강 인접 농경지",
            "narration": "등록된 농경지를 확대해 다시 확인합니다.",
            "visual_type": "overlay",
        },
        {
            "id": "close_official_flood", "start_frame": 577, "end_frame": 1056,
            "title": "농경지 침수 영향 예상",
            "subtitle": f"필지 약 {affected:.1f}% · 주된 수심 등급 2~5m",
            "narration": f"공식 침수예상도와 등록 농경지를 겹쳐 계산하면 대상 면적의 약 {affected:.1f} 퍼센트가 침수 범위에 포함됩니다. 필지 대부분의 공식 수심 등급은 이에서 오 미터입니다. 화면의 물 높이는 과장을 줄이기 위해 이 미터에서 멈춥니다. 오늘 해가 있을 때 배수로를 확인하고 농기계와 농자재를 높은 곳으로 옮기며 비닐하우스 결박을 마치십시오.",
            "visual_type": "overlay",
        },
        {
            "id": "field_hold", "start_frame": 1057, "end_frame": 1128,
            "title": "비가 시작되면 접근 금지",
            "subtitle": "논둑·물꼬·하천변에 가지 마십시오",
            "narration": "비가 오면 논에 가지 마십시오.",
            "visual_type": "overlay",
        },
        {
            "id": "shelter_route", "start_frame": 1129, "end_frame": 1536,
            "title": "비 오기 전 사전 이동 경로",
            "subtitle": f"{shelter['name']} · 약 {route['route_length_m']/1000:.1f}km",
            "narration": f"대피가 필요하면 지자체의 시설 개방을 확인한 뒤, 실제 재해구호시설인 {shelter['name']}으로 이동하십시오. 표시 경로는 약 {route['route_length_m']/1000:.1f} 킬로미터입니다. 농경지가 침수예상구역 안에 있어 이 경로는 반드시 비가 시작되기 전에 이용해야 합니다. 비가 온 뒤에는 통제 안내를 따르고 긴급상황은 일일구에 신고하십시오.",
            "visual_type": "route_map",
        },
    ]
    for item in segments:
        item["duration_seconds"] = (item["end_frame"] - item["start_frame"] + 1) / FPS
    return {
        "input_data": data,
        "field_result": official,
        "segments": segments,
        "trace": traced(state, "script_agent", {
            "provider": "official_data_editorial",
            "field_id": data.get("field_id"),
            "segment_count": len(segments),
        }),
    }

def font(size: int, bold=False):
    return ImageFont.truetype(str(FONT_PATH), size=size, index=1 if bold else 0)


def overlay_asset(item: Dict[str, Any], path: Path):
    image = Image.new("RGBA", (960, 540), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((34, 28, 720, 128), radius=20, fill=(5, 20, 32, 210), outline=(73, 190, 236, 235), width=2)
    draw.text((58, 45), item["title"], font=font(30, True), fill=(255, 255, 255, 255))
    draw.text((58, 88), item["subtitle"], font=font(20), fill=(184, 229, 250, 255))
    if item["id"] == "close_official_flood":
        draw.rounded_rectangle((500, 430, 926, 505), radius=16, fill=(62, 7, 5, 220), outline=(255, 84, 55, 245), width=2)
        draw.text((525, 450), "표시 상한 2.0m · 비가 시작되면 접근 금지", font=font(19, True), fill=(255, 242, 235, 255))
    image.save(path)


def route_map_asset(state: StoryState, item: Dict[str, Any], path: Path):
    roads = read_json(ROADS_PATH)
    route_data = read_json(ROUTE_PATH)
    field = read_json(FIELD_CONFIG_PATH)
    official = state["field_result"]
    features = {feature["properties"]["kind"]: feature for feature in route_data["features"]}
    route = features["pre_rain_route"]["geometry"]["coordinates"]
    shelter = official["shelter"]
    field_lon, field_lat = field["derived_metrics"]["centre_wgs84"]
    points = route + [[shelter["lon"], shelter["lat"]], [field_lon, field_lat]]
    lons = [p[0] for p in points]; lats = [p[1] for p in points]
    margin_lon = max(0.002, (max(lons) - min(lons)) * 0.10)
    margin_lat = max(0.002, (max(lats) - min(lats)) * 0.10)
    bounds = (min(lons)-margin_lon, min(lats)-margin_lat, max(lons)+margin_lon, max(lats)+margin_lat)
    map_box = (42, 132, 918, 500)

    def project(coord):
        lon, lat = coord
        x = map_box[0] + (lon - bounds[0]) / (bounds[2] - bounds[0]) * (map_box[2] - map_box[0])
        y = map_box[3] - (lat - bounds[1]) / (bounds[3] - bounds[1]) * (map_box[3] - map_box[1])
        return (round(x), round(y))

    image = Image.new("RGB", (960, 540), "#071522")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((24, 18, 936, 522), radius=24, fill="#102B3D", outline="#2C5871", width=2)
    draw.text((48, 38), item["title"], font=font(34, True), fill="#FFFFFF")
    draw.text((50, 84), item["subtitle"], font=font(22, True), fill="#7BD7FF")
    draw.rectangle(map_box, fill="#E8EEF0", outline="#6C8793", width=2)

    nodes = {int(e["id"]): (float(e["lon"]), float(e["lat"])) for e in roads["elements"] if e["type"] == "node"}
    for way in (e for e in roads["elements"] if e["type"] == "way" and e.get("tags", {}).get("highway")):
        coords = [nodes[int(n)] for n in way.get("nodes", []) if int(n) in nodes]
        visible = [project(c) for c in coords if bounds[0] <= c[0] <= bounds[2] and bounds[1] <= c[1] <= bounds[3]]
        if len(visible) >= 2:
            draw.line(visible, fill="#AAB7BC", width=2)

    flood_overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    flood_draw = ImageDraw.Draw(flood_overlay)
    geometry = features["official_flood_extent"]["geometry"]
    polygons = geometry["coordinates"] if geometry["type"] == "MultiPolygon" else [geometry["coordinates"]]
    for polygon in polygons:
        if polygon and polygon[0]:
            ring = [project(c) for c in polygon[0]]
            if len(ring) >= 3:
                flood_draw.polygon(ring, fill=(224, 76, 106, 95), outline=(190, 45, 75, 170))
    image = Image.alpha_composite(image.convert("RGBA"), flood_overlay)
    draw = ImageDraw.Draw(image)
    draw.line([project(c) for c in route], fill="#F39C35", width=7, joint="curve")
    fx, fy = project((field_lon, field_lat))
    sx, sy = project((shelter["lon"], shelter["lat"]))
    draw.ellipse((fx-10, fy-10, fx+10, fy+10), fill="#E43D30", outline="#FFFFFF", width=3)
    draw.ellipse((sx-12, sy-12, sx+12, sy+12), fill="#1484D6", outline="#FFFFFF", width=3)
    draw.text((fx+14, fy-13), "등록 농경지", font=font(17, True), fill="#532019", stroke_width=2, stroke_fill="#FFFFFF")
    draw.text((sx+16, sy-13), shelter["name"], font=font(17, True), fill="#0B3958", stroke_width=2, stroke_fill="#FFFFFF")
    draw.rounded_rectangle((55, 444, 905, 491), radius=12, fill=(7, 21, 34, 225))
    draw.text((72, 457), "주황: 비 오기 전 이동 경로   분홍: 100년 빈도 침수예상 범위   파랑: 재해구호시설", font=font(17), fill="#FFFFFF")
    draw.text((48, 505), "시설 개방 확인 후 이동 · 비가 시작된 뒤에는 도로 통제 안내를 따르십시오", font=font(16, True), fill="#FFD27D")
    image.convert("RGB").save(path)

async def write_openai_audio(client, model, voice, text, speed, path):
    path.unlink(missing_ok=True)
    response = await client.audio.speech.create(
        model=model,
        voice=voice,
        input=text,
        instructions="고령 농업인이 이해하기 쉽도록 침착하고 또렷한 한국어로 읽으세요. 숫자와 시간은 정확하게 읽고 불필요한 감정 연기는 하지 마세요.",
        response_format="mp3",
        speed=speed,
        timeout=90.0,
    )
    await asyncio.to_thread(response.write_to_file, path)


async def write_local_audio(local_voice, text, path):
    path.unlink(missing_ok=True)
    process = await asyncio.create_subprocess_exec(
        "/usr/bin/say", "-v", local_voice["name"], "-r", str(int(local_voice["rate"])),
        "-o", str(path), text,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    if process.returncode != 0:
        raise RuntimeError(stderr.decode("utf-8", errors="replace")[:500])


async def generate_tts_segment(client, model, voice, speed, local_voice, index, item):
    provider = "openai"
    fallback_reason = None
    try:
        if client is None:
            raise RuntimeError("OPENAI_API_KEY is missing")
        path = AUDIO / f"{index:02d}_{item['id']}.mp3"
        await write_openai_audio(client, model, voice, item["narration"], speed, path)
    except Exception as exc:
        provider = "macos_say"
        fallback_reason = str(exc).replace("\n", " ")[:240]
        path = AUDIO / f"{index:02d}_{item['id']}.aiff"
        await write_local_audio(local_voice, item["narration"], path)

    return item["id"], {
        "path": str(path),
        "duration_seconds": item["duration_seconds"],
        "bytes": path.stat().st_size if path.exists() else 0,
        "provider": provider,
        "speed_or_rate": speed if provider == "openai" else local_voice["rate"],
    }, fallback_reason


async def tts_agent(state: StoryState) -> Dict[str, Any]:
    """Generate every segment concurrently; one failed request falls back independently."""
    AUDIO.mkdir(parents=True, exist_ok=True)
    model = os.getenv("OPENAI_TTS_MODEL", "gpt-4o-mini-tts")
    voice = os.getenv("OPENAI_TTS_VOICE", "alloy")
    speed = float(os.getenv("OPENAI_TTS_SPEED_V13", "1.08"))
    local_voice = state["input_data"]["voice"]
    client = AsyncOpenAI(timeout=90.0, max_retries=0) if os.getenv("OPENAI_API_KEY") else None
    started = perf_counter()

    try:
        results = await asyncio.gather(*[
            generate_tts_segment(client, model, voice, speed, local_voice, index, item)
            for index, item in enumerate(state["segments"], start=1)
        ])
    finally:
        if client is not None:
            await client.close()

    assets = {}
    counts = {"openai": 0, "macos_say": 0}
    fallback_reasons = {}
    for segment_id, asset, fallback_reason in results:
        assets[segment_id] = asset
        counts[asset["provider"]] += 1
        if fallback_reason:
            fallback_reasons[segment_id] = fallback_reason

    elapsed = round(perf_counter() - started, 3)
    meta = {
        "model": model,
        "voice": voice,
        "provider_counts": counts,
        "fallback_reasons": fallback_reasons,
        "generation_mode": "async_parallel",
        "request_count": len(results),
        "elapsed_seconds": elapsed,
        "ai_voice_disclosure": "AI 생성 음성 사용",
    }
    return {
        "tts_assets": assets,
        "tts_meta": meta,
        "trace": traced(state, "tts_agent", {
            "provider_counts": counts,
            "generation_mode": "async_parallel",
            "request_count": len(results),
            "elapsed_seconds": elapsed,
        }),
    }


def srt_time(seconds: float) -> str:
    ms = round(seconds * 1000)
    hours, ms = divmod(ms, 3_600_000)
    minutes, ms = divmod(ms, 60_000)
    seconds, ms = divmod(ms, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{ms:03d}"


def video_production_agent(state: StoryState) -> Dict[str, Any]:
    """Create visual assets, subtitles, script, and the composition manifest."""
    started = perf_counter()
    ASSETS.mkdir(parents=True, exist_ok=True)
    assets = {}
    segments = []
    for item in state["segments"]:
        path = ASSETS / f"{item['id']}.png"
        if item["visual_type"] == "overlay":
            overlay_asset(item, path)
        else:
            route_map_asset(state, item, path)
        assets[item["id"]] = str(path)
        segments.append({**item, "visual_path": str(path)})

    enriched = []
    srt = []
    for index, item in enumerate(segments, start=1):
        audio = state["tts_assets"][item["id"]]
        enriched.append({**item, "audio_path": audio["path"], "audio_duration_seconds": audio["duration_seconds"]})
        srt.extend([
            str(index),
            f"{srt_time((item['start_frame'] - 1) / FPS)} --> {srt_time(item['end_frame'] / FPS)}",
            item["narration"], "",
        ])
    manifest = {
        "schema_version": "4.0",
        "run_id": state["run_id"],
        "fps": FPS,
        "resolution": [960, 540],
        "frame_end": 1536,
        "duration_seconds": 64.0,
        "base_video": str(BASE_VIDEO),
        "base_frame_end": 1128,
        "flood_step_seconds": 2.0,
        "visual_depth_cap_m": 2.0,
        "official_floodmap_scenario": "국가하천 금강권역 100년 빈도",
        "segments": enriched,
        "tts_meta": state["tts_meta"],
        "ai_voice_disclosure": "AI 생성 음성 사용",
        "output_video": str(FINAL_VIDEO),
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    SCRIPT_PATH.write_text("\n\n".join(f"[{item['title']}]\n{item['narration']}" for item in enriched), encoding="utf-8")
    SRT_PATH.write_text("\n".join(srt), encoding="utf-8")
    elapsed = round(perf_counter() - started, 3)
    return {
        "segments": segments,
        "visual_assets": assets,
        "manifest": manifest,
        "trace": traced(state, "video_production_agent", {
            "asset_count": len(assets),
            "duration_seconds": 64.0,
            "elapsed_seconds": elapsed,
        }),
    }


def composition_agent(state: StoryState) -> Dict[str, Any]:
    """Compose the cached base video with generated audio and visuals."""
    started = perf_counter()
    log = OUT / "composition.log"
    result = subprocess.run(
        [str(BLENDER), "--background", "--python", str(COMPOSER)],
        cwd=str(ROOT), capture_output=True, text=True,
    )
    log.write_text(result.stdout + "\n" + result.stderr, encoding="utf-8")
    if result.returncode != 0:
        raise RuntimeError(f"Blender composition process failed: {log}")

    elapsed = round(perf_counter() - started, 3)
    final_trace = traced(state, "composition_agent", {"elapsed_seconds": elapsed})
    video = FINAL_VIDEO
    report = {
        "status": "completed",
        "run_id": state["run_id"],
        "duration_seconds": 64.0,
        "final_video": str(video),
        "video_bytes": video.stat().st_size if video.exists() else 0,
        "manifest": str(MANIFEST_PATH),
        "script": str(SCRIPT_PATH),
        "subtitles": str(SRT_PATH),
        "tts_meta": state["tts_meta"],
        "base_video_policy": "required_pre_rendered_asset",
        "trace": final_trace,
    }
    STATE_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"final_video": str(video), "trace": final_trace}


def build_graph():
    builder = StateGraph(StoryState)
    nodes = [
        ("script_agent", script_agent),
        ("tts_agent", tts_agent),
        ("video_production_agent", video_production_agent),
        ("composition_agent", composition_agent),
    ]
    for name, function in nodes:
        builder.add_node(name, function)
    builder.add_edge(START, nodes[0][0])
    for (current, _), (following, _) in zip(nodes, nodes[1:]):
        builder.add_edge(current, following)
    builder.add_edge(nodes[-1][0], END)
    return builder.compile()


async def main():
    load_dotenv(ROOT / ".env")
    OUT.mkdir(parents=True, exist_ok=True)
    graph = build_graph()
    GRAPH_PATH.write_text(graph.get_graph().draw_mermaid(), encoding="utf-8")
    result = await graph.ainvoke({"run_id": "OSONG-GUIDANCE-V13-64S-PARALLEL", "trace": []})
    print(json.dumps({
        "status": "ok",
        "final_video": result["final_video"],
        "duration_seconds": 64.0,
        "tts_provider_counts": result["tts_meta"]["provider_counts"],
        "tts_elapsed_seconds": result["tts_meta"]["elapsed_seconds"],
        "trace_nodes": [item["node"] for item in result["trace"]],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
