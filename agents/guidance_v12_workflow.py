"""V12 60-second flood guidance workflow aligned to the repeated camera story."""

import json
import math
import os
from pathlib import Path
import re
import subprocess
from typing import Any, Dict, List

from dotenv import load_dotenv
from langgraph.graph import END, START, StateGraph
from openai import OpenAI
from PIL import Image, ImageDraw, ImageFont
from typing_extensions import TypedDict

ROOT = Path("/Users/hyeokjae/Desktop/ICTCB/flood")
INPUT_PATH = ROOT / "config" / "osong_guidance_input_v12.json"
FIELD_RESULT_PATH = ROOT / "output" / "guidance_v12" / "osong_inundation_v12_field_result.json"
INUNDATION_PATH = ROOT / "data" / "processed" / "osong_inundation_v12.json"
SOURCE_BLEND = ROOT / "blender" / "osong_hq_v11.blend"
BASE_BUILDER = ROOT / "blender" / "build_osong_story_v12.py"
COMPOSER = ROOT / "blender" / "compose_guidance_video_v12.py"
BLENDER = Path("/Applications/Blender.app/Contents/MacOS/Blender")
OUT = ROOT / "output" / "guidance_v12"
ASSETS = OUT / "visuals"
AUDIO = OUT / "audio"
BASE_VIDEO = OUT / "osong_story_v12_base.mp4"
FINAL_VIDEO = OUT / "osong_guidance_v12_60s.mp4"
MANIFEST_PATH = OUT / "guidance_manifest.json"
STATE_PATH = OUT / "workflow_final_state.json"
SCRIPT_PATH = OUT / "narration_script.txt"
SRT_PATH = OUT / "guidance_subtitles.srt"
GRAPH_PATH = OUT / "langgraph_structure.mmd"
FONT_PATH = Path("/System/Library/Fonts/AppleSDGothicNeo.ttc")
FPS = 24


class StoryState(TypedDict, total=False):
    run_id: str
    input_data: Dict[str, Any]
    field_result: Dict[str, Any]
    inundation_meta: Dict[str, Any]
    segments: List[Dict[str, Any]]
    safety_review: Dict[str, Any]
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


def context_agent(state: StoryState) -> Dict[str, Any]:
    data = read_json(INPUT_PATH)
    field_result = read_json(FIELD_RESULT_PATH)
    for path in (SOURCE_BLEND, BASE_BUILDER, COMPOSER, INUNDATION_PATH):
        if not path.is_file():
            raise FileNotFoundError(path)
    if field_result.get("status") != "ok":
        raise RuntimeError("field result is not ready")
    return {
        "input_data": data,
        "field_result": field_result,
        "trace": traced(state, "context_agent", {"field_id": data["field_id"]}),
    }


def inundation_agent(state: StoryState) -> Dict[str, Any]:
    progression = read_json(INUNDATION_PATH)
    steps = progression.get("progression", [])
    impacts = [float(step.get("field_affected_percent", -1)) for step in steps]
    meta = {
        "candidate_id": progression.get("selected_candidate"),
        "step_count": len(steps),
        "impacts_monotonic": all(a <= b for a, b in zip(impacts, impacts[1:])),
        "old_results_not_reused": progression.get("validation", {}).get("old_gangnae_results_reused") is False,
    }
    expected = {
        "candidate_id": "C19",
        "step_count": 10,
        "impacts_monotonic": True,
        "old_results_not_reused": True,
    }
    if meta != expected:
        raise RuntimeError(f"V12 inundation validation failed: {meta}")
    return {
        "inundation_meta": meta,
        "trace": traced(state, "inundation_agent", meta),
    }


def script_agent(state: StoryState) -> Dict[str, Any]:
    data = state["input_data"]
    forecast = data["forecast"]
    scenario = state["field_result"]["scenario_results"]
    warning = scenario["warning"]["inundated_percent"]
    serious = scenario["serious"]["inundated_percent"]
    segments = [
        {
            "id": "wide_flood_1", "start_frame": 1, "end_frame": 240,
            "title": "오송읍 미호강 하류 하천 범람 예상",
            "subtitle": f"{forecast['rain_start_label']} · 24시간 {forecast['predicted_24h_rain_mm']}mm",
            "narration": f"오송읍 미호강 하류에 {forecast['rain_start_label']}부터 많은 비가 예상됩니다. 24시간 예상 강수량은 {forecast['predicted_24h_rain_mm']} 밀리미터이며 하천 주변 저지대부터 물이 퍼집니다.",
            "visual_type": "overlay",
        },
        {
            "id": "zoom_field_1", "start_frame": 241, "end_frame": 336,
            "title": "대상 농경지 확대",
            "subtitle": "하천과 가까운 저지대 농경지",
            "narration": "하천과 가까운 대상 농경지를 확대해 확인합니다.",
            "visual_type": "overlay",
        },
        {
            "id": "close_flood_1", "start_frame": 337, "end_frame": 576,
            "title": "농경지 영향 범위",
            "subtitle": f"경계 단계 · 농경지 약 {warning:.1f}% 영향",
            "narration": f"하천 수위가 오르며 물이 농경지 방향으로 퍼집니다. 경계 단계에는 대상 농경지의 약 {warning:.1f} 퍼센트가 영향을 받습니다.",
            "visual_type": "overlay",
        },
        {
            "id": "wide_flood_2", "start_frame": 577, "end_frame": 816,
            "title": "침수 확산 경로 재확인",
            "subtitle": "하천 주변 → 저지대 → 대상 농경지",
            "narration": "전체 침수 과정을 다시 확인합니다. 하천 주변에서 시작된 물이 낮은 지형을 따라 대상 농경지까지 확산됩니다. 침수 범위가 넓어지는 순서를 다시 확인하십시오.",
            "visual_type": "overlay",
        },
        {
            "id": "zoom_field_2", "start_frame": 817, "end_frame": 912,
            "title": "비가 오기 전 준비",
            "subtitle": "지금이 안전하게 조치할 시간입니다",
            "narration": "비가 오기 전이 안전하게 준비할 시간입니다.",
            "visual_type": "overlay",
        },
        {
            "id": "close_flood_2_and_hold", "start_frame": 913, "end_frame": 1248,
            "title": "심각 단계 농경지 영향",
            "subtitle": f"대상 농경지 {serious:.1f}% 영향 예상",
            "narration": f"심각 단계에는 대상 농경지의 {serious:.1f} 퍼센트가 영향을 받습니다. 비가 오기 전에 배수로를 확인하고 농기계와 농자재를 안전한 곳으로 옮기십시오. 비닐하우스 결박 상태도 확인하십시오.",
            "visual_type": "overlay",
        },
        {
            "id": "final_information", "start_frame": 1249, "end_frame": 1440,
            "title": "오늘 안에 준비를 마치세요",
            "subtitle": "비가 시작되면 농경지에 접근하지 마십시오",
            "narration": "비가 시작되면 논둑이나 물꼬를 보러 나가지 마십시오. 하천변과 침수 도로를 피하고 긴급상황은 일일구에 신고하십시오.",
            "visual_type": "final_slide",
        },
    ]
    for item in segments:
        item["duration_seconds"] = (item["end_frame"] - item["start_frame"] + 1) / FPS
    return {
        "segments": segments,
        "trace": traced(state, "script_agent", {"provider": "editorial_locked", "segment_count": len(segments)}),
    }


def safety_agent(state: StoryState) -> Dict[str, Any]:
    combined = " ".join(item["narration"] for item in state["segments"])
    scenario = state["field_result"]["scenario_results"]
    warning = "{:.1f}".format(scenario["warning"]["inundated_percent"])
    serious = "{:.1f}".format(scenario["serious"]["inundated_percent"])
    required = ["80", warning, serious, "오송읍", "미호강", "배수로", "농기계", "비닐하우스", "논둑이나 물꼬", "일일구"]
    forbidden = ["시뮬레이션", "실제 상황이 아닙니다", "증거가 되지 않습니다", "공모전 시연용", "공식 경보입니다", "즉시 대피하십시오", "강내면", "GANGNAE", "62.5", "100.0"]
    missing = [value for value in required if value not in combined]
    found = [value for value in forbidden if value in combined]
    segments = state["segments"]
    timeline_valid = (
        segments[0]["start_frame"] == 1
        and segments[-1]["end_frame"] == 1440
        and all(a["end_frame"] + 1 == b["start_frame"] for a, b in zip(segments, segments[1:]))
    )
    inundation_valid = (
        state["inundation_meta"].get("candidate_id") == "C19"
        and state["inundation_meta"].get("old_results_not_reused") is True
    )
    passed = not missing and not found and timeline_valid and inundation_valid
    review = {
        "passed": passed,
        "required_missing": missing,
        "forbidden_found": found,
        "timeline_continuous": timeline_valid,
        "tts_starts_at_first_frame": segments[0]["start_frame"] == 1,
        "inundation_data_valid": inundation_valid,
        "total_seconds": segments[-1]["end_frame"] / FPS,
    }
    if not passed:
        raise RuntimeError(f"V12 safety review failed: {review}")
    return {"safety_review": review, "trace": traced(state, "safety_agent", review)}


def font(size: int, bold=False):
    return ImageFont.truetype(str(FONT_PATH), size=size, index=1 if bold else 0)


def overlay_asset(item: Dict[str, Any], path: Path):
    image = Image.new("RGBA", (960, 540), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((34, 28, 720, 128), radius=20, fill=(5, 20, 32, 210), outline=(73, 190, 236, 235), width=2)
    draw.text((58, 45), item["title"], font=font(30, True), fill=(255, 255, 255, 255))
    draw.text((58, 88), item["subtitle"], font=font(20), fill=(184, 229, 250, 255))
    if item["id"] == "close_flood_2_and_hold":
        draw.rounded_rectangle((500, 430, 926, 505), radius=16, fill=(62, 7, 5, 220), outline=(255, 84, 55, 245), width=2)
        draw.text((525, 450), "비가 시작되면 농경지에 들어가지 마십시오", font=font(19, True), fill=(255, 242, 235, 255))
    image.save(path)


def final_slide_asset(state: StoryState, item: Dict[str, Any], path: Path):
    data = state["input_data"]
    scenario = state["field_result"]["scenario_results"]
    image = Image.new("RGB", (960, 540), "#071522")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((38, 30, 922, 508), radius=26, fill="#102B3D", outline="#2C5871", width=2)
    draw.text((70, 60), item["title"], font=font(39, True), fill="#FFFFFF")
    draw.text((72, 122), f"{data['forecast']['rain_start_label']} · 24시간 예상 강수량 {data['forecast']['predicted_24h_rain_mm']}mm", font=font(25, True), fill="#7BD7FF")
    draw.text((72, 180), "예상 농경지 영향", font=font(23, True), fill="#FFFFFF")
    draw.text((72, 220), f"경계 {scenario['warning']['inundated_percent']:.1f}%   ·   심각 {scenario['serious']['inundated_percent']:.1f}%", font=font(31, True), fill="#FF8A62")
    draw.text((72, 285), "비가 오기 전", font=font(22, True), fill="#92E870")
    draw.text((72, 323), "배수로 확인 · 농기계 이동 · 비닐하우스 결박", font=font(24), fill="#E8F4F8")
    draw.text((72, 380), "비가 시작된 뒤", font=font(22, True), fill="#FF8A62")
    draw.text((72, 418), "농경지·하천변 접근 금지 · 긴급상황 119", font=font(24), fill="#FFFFFF")
    draw.line((72, 463, 888, 463), fill="#315B70", width=2)
    draw.text((72, 477), "기상청 예보 · SRTM 지형 · VWorld/OSM 공간자료  |  AI 생성 음성", font=font(17), fill="#A8C4D0")
    image.save(path)


def visual_asset_agent(state: StoryState) -> Dict[str, Any]:
    ASSETS.mkdir(parents=True, exist_ok=True)
    assets = {}
    updated = []
    for item in state["segments"]:
        path = ASSETS / f"{item['id']}.png"
        if item["visual_type"] == "overlay":
            overlay_asset(item, path)
        else:
            final_slide_asset(state, item, path)
        assets[item["id"]] = str(path)
        updated.append({**item, "visual_path": str(path)})
    return {
        "segments": updated,
        "visual_assets": assets,
        "trace": traced(state, "visual_asset_agent", {"asset_count": len(assets)}),
    }


def audio_duration(path: Path) -> float:
    result = subprocess.run(["/usr/bin/afinfo", str(path)], check=True, capture_output=True, text=True)
    match = re.search(r"estimated duration:\s*([0-9.]+) sec", result.stdout)
    if not match:
        raise RuntimeError(f"audio duration missing: {path}")
    return float(match.group(1))


def write_openai_audio(client, model, voice, text, speed, path):
    path.unlink(missing_ok=True)
    response = client.audio.speech.create(
        model=model,
        voice=voice,
        input=text,
        instructions="고령 농업인이 이해하기 쉽도록 침착하고 또렷한 한국어로 읽으세요. 숫자와 시간은 정확하게 읽고 불필요한 감정 연기는 하지 마세요.",
        response_format="mp3",
        speed=speed,
        timeout=90.0,
    )
    response.write_to_file(path)


def tts_agent(state: StoryState) -> Dict[str, Any]:
    AUDIO.mkdir(parents=True, exist_ok=True)
    model = os.getenv("OPENAI_TTS_MODEL", "gpt-4o-mini-tts")
    voice = os.getenv("OPENAI_TTS_VOICE", "alloy")
    base_speed = float(os.getenv("OPENAI_TTS_SPEED_V12", "1.15"))
    local_voice = state["input_data"]["voice"]
    client = OpenAI(timeout=90.0, max_retries=2) if os.getenv("OPENAI_API_KEY") else None
    assets = {}
    counts = {"openai": 0, "macos_say": 0}
    adjusted = {}
    fallback_reasons = {}
    for index, item in enumerate(state["segments"], start=1):
        target = item["duration_seconds"] - 0.20
        provider = "openai"
        speed = base_speed
        try:
            if client is None:
                raise RuntimeError("OPENAI_API_KEY is missing")
            path = AUDIO / f"{index:02d}_{item['id']}.mp3"
            write_openai_audio(client, model, voice, item["narration"], speed, path)
            duration = audio_duration(path)
            if duration > target:
                speed = min(1.50, round(speed * duration / target * 1.04, 2))
                write_openai_audio(client, model, voice, item["narration"], speed, path)
                duration = audio_duration(path)
                adjusted[item["id"]] = speed
        except Exception as exc:
            provider = "macos_say"
            fallback_reasons[item["id"]] = str(exc).replace("\n", " ")[:240]
            path = AUDIO / f"{index:02d}_{item['id']}.aiff"
            path.unlink(missing_ok=True)
            rate = int(local_voice["rate"])
            subprocess.run(["/usr/bin/say", "-v", local_voice["name"], "-r", str(rate), "-o", str(path), item["narration"]], check=True)
            duration = audio_duration(path)
            if duration > target:
                rate = max(rate, math.ceil(rate * duration / target * 1.04))
                subprocess.run(["/usr/bin/say", "-v", local_voice["name"], "-r", str(rate), "-o", str(path), item["narration"]], check=True)
                duration = audio_duration(path)
                adjusted[item["id"]] = rate
        if duration > item["duration_seconds"] or duration <= 0.5 or path.stat().st_size <= 1024:
            raise RuntimeError(f"TTS does not fit segment {item['id']}: {duration:.3f}/{item['duration_seconds']:.3f}")
        counts[provider] += 1
        assets[item["id"]] = {
            "path": str(path), "duration_seconds": round(duration, 3), "bytes": path.stat().st_size,
            "provider": provider, "speed_or_rate": adjusted.get(item["id"], speed if provider == "openai" else local_voice["rate"]),
        }
    meta = {
        "model": model, "voice": voice, "provider_counts": counts,
        "adjusted_segments": adjusted, "fallback_reasons": fallback_reasons,
        "ai_voice_disclosure": "AI 생성 음성 사용",
    }
    return {
        "tts_assets": assets,
        "tts_meta": meta,
        "trace": traced(state, "tts_agent", {"provider_counts": counts, "adjusted": adjusted}),
    }


def base_render_agent(state: StoryState) -> Dict[str, Any]:
    log = OUT / "base_render.log"
    report_path = OUT / "base_render_report.json"
    if BASE_VIDEO.is_file() and BASE_VIDEO.stat().st_size >= 100_000 and report_path.is_file():
        cached = read_json(report_path)
        if cached.get("status") == "ok" and cached.get("frames") == [1, 1248] and cached.get("flood_playback_speed") == 0.5:
            return {"trace": traced(state, "base_render_agent", {"base_video_bytes": BASE_VIDEO.stat().st_size, "reused": True})}
    result = subprocess.run(
        [str(BLENDER), "--background", str(SOURCE_BLEND), "--python", str(BASE_BUILDER)],
        cwd=str(ROOT), capture_output=True, text=True,
    )
    log.write_text(result.stdout + "\n" + result.stderr, encoding="utf-8")
    if result.returncode != 0 or not BASE_VIDEO.is_file() or BASE_VIDEO.stat().st_size < 100_000:
        raise RuntimeError(f"base render failed: {log}")
    return {"trace": traced(state, "base_render_agent", {"base_video_bytes": BASE_VIDEO.stat().st_size, "log": str(log)})}


def srt_time(seconds: float) -> str:
    ms = round(seconds * 1000)
    hours, ms = divmod(ms, 3_600_000)
    minutes, ms = divmod(ms, 60_000)
    seconds, ms = divmod(ms, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{ms:03d}"


def manifest_agent(state: StoryState) -> Dict[str, Any]:
    enriched = []
    srt = []
    for index, item in enumerate(state["segments"], start=1):
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
        "frame_end": 1440,
        "duration_seconds": 60.0,
        "base_video": str(BASE_VIDEO),
        "base_frame_end": 1248,
        "flood_playback_speed": 0.5,
        "segments": enriched,
        "safety_review": state["safety_review"],
        "tts_meta": state["tts_meta"],
        "ai_voice_disclosure": "AI 생성 음성 사용",
        "output_video": str(FINAL_VIDEO),
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    SCRIPT_PATH.write_text("\n\n".join(f"[{item['title']}]\n{item['narration']}" for item in enriched), encoding="utf-8")
    SRT_PATH.write_text("\n".join(srt), encoding="utf-8")
    return {"manifest": manifest, "trace": traced(state, "manifest_agent", {"duration_seconds": 60.0})}


def composition_agent(state: StoryState) -> Dict[str, Any]:
    log = OUT / "composition.log"
    result = subprocess.run([str(BLENDER), "--background", "--python", str(COMPOSER)], cwd=str(ROOT), capture_output=True, text=True)
    log.write_text(result.stdout + "\n" + result.stderr, encoding="utf-8")
    if result.returncode != 0 or not FINAL_VIDEO.is_file() or FINAL_VIDEO.stat().st_size < 100_000:
        raise RuntimeError(f"composition failed: {log}")
    return {"final_video": str(FINAL_VIDEO), "trace": traced(state, "composition_agent", {"video_bytes": FINAL_VIDEO.stat().st_size})}


def final_report_agent(state: StoryState) -> Dict[str, Any]:
    report = {
        "status": "ok", "run_id": state["run_id"], "duration_seconds": 60.0,
        "final_video": state["final_video"], "video_bytes": Path(state["final_video"]).stat().st_size,
        "manifest": str(MANIFEST_PATH), "script": str(SCRIPT_PATH), "subtitles": str(SRT_PATH),
        "safety_review": state["safety_review"], "tts_meta": state["tts_meta"], "trace": state["trace"],
    }
    STATE_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"trace": traced(state, "final_report_agent", {"report": str(STATE_PATH)})}


def build_graph():
    builder = StateGraph(StoryState)
    nodes = [
        ("context_agent", context_agent), ("inundation_agent", inundation_agent),
        ("script_agent", script_agent), ("safety_agent", safety_agent),
        ("visual_asset_agent", visual_asset_agent), ("base_render_agent", base_render_agent),
        ("tts_agent", tts_agent), ("manifest_agent", manifest_agent),
        ("composition_agent", composition_agent), ("final_report_agent", final_report_agent),
    ]
    for name, function in nodes: builder.add_node(name, function)
    builder.add_edge(START, nodes[0][0])
    for (current, _), (following, _) in zip(nodes, nodes[1:]): builder.add_edge(current, following)
    builder.add_edge(nodes[-1][0], END)
    return builder.compile()


def main():
    load_dotenv(ROOT / ".env")
    OUT.mkdir(parents=True, exist_ok=True)
    graph = build_graph()
    GRAPH_PATH.write_text(graph.get_graph().draw_mermaid(), encoding="utf-8")
    result = graph.invoke({"run_id": "OSONG-GUIDANCE-V12-60S", "trace": []})
    print(json.dumps({
        "status": "ok", "final_video": result["final_video"], "duration_seconds": 60.0,
        "tts_provider_counts": result["tts_meta"]["provider_counts"],
        "trace_nodes": [item["node"] for item in result["trace"]],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
