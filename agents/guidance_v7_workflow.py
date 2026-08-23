"""LangGraph MVP workflow: context -> script -> safety -> assets -> TTS -> timeline -> compose."""

import json
import math
from pathlib import Path
import re
import subprocess
from typing import Any, Dict, List

from langgraph.graph import END, START, StateGraph
from PIL import Image, ImageDraw, ImageFont
from typing_extensions import TypedDict


ROOT = Path("/Users/hyeokjae/Desktop/ICTCB/flood")
INPUT_PATH = ROOT / "config" / "guidance_demo_input.json"
POLICY_PATH = ROOT / "config" / "guidance_policy.json"
OUT = ROOT / "output" / "guidance_v7"
SLIDES = OUT / "slides"
AUDIO = OUT / "audio"
MANIFEST_PATH = OUT / "guidance_manifest.json"
STATE_PATH = OUT / "workflow_final_state.json"
SCRIPT_PATH = OUT / "narration_script.txt"
SRT_PATH = OUT / "guidance_subtitles.srt"
GRAPH_PATH = OUT / "langgraph_structure.mmd"
FINAL_VIDEO = OUT / "gangnae_guidance_v7.mp4"
FONT_PATH = Path("/System/Library/Fonts/AppleSDGothicNeo.ttc")
BLENDER = Path("/Applications/Blender.app/Contents/MacOS/Blender")
COMPOSER = ROOT / "blender" / "compose_guidance_video_v7.py"


class GuidanceState(TypedDict, total=False):
    run_id: str
    input_data: Dict[str, Any]
    policy: Dict[str, Any]
    field_result: Dict[str, Any]
    segments: List[Dict[str, Any]]
    safety_review: Dict[str, Any]
    tts_assets: Dict[str, Dict[str, Any]]
    timeline: List[Dict[str, Any]]
    manifest: Dict[str, Any]
    final_video: str
    trace: List[Dict[str, Any]]


def read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def traced(state: GuidanceState, node: str, detail: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [*state.get("trace", []), {"node": node, "status": "ok", **detail}]


def context_agent(state: GuidanceState) -> Dict[str, Any]:
    input_data = read_json(INPUT_PATH)
    policy = read_json(POLICY_PATH)
    field_result_path = Path(input_data["field_result"])
    video_path = Path(input_data["digital_twin_video"])
    if input_data["mode"] != "mvp_demo_not_live_forecast":
        raise RuntimeError("6차 MVP는 비실시간 데모 입력만 허용합니다.")
    if not field_result_path.is_file() or not video_path.is_file():
        raise FileNotFoundError("4차 침수 결과 또는 5차 디지털트윈 MP4가 없습니다.")
    field_result = read_json(field_result_path)
    if field_result.get("status") != "ok":
        raise RuntimeError("침수 결과 상태가 ok가 아닙니다.")
    if field_result.get("accuracy") != "heuristic_demo_not_hydraulic_model":
        raise RuntimeError("MVP 휴리스틱 정확도 라벨이 없습니다.")
    return {
        "input_data": input_data,
        "policy": policy,
        "field_result": field_result,
        "trace": traced(state, "context_agent", {"field_id": input_data["field_id"], "video_bytes": video_path.stat().st_size}),
    }


def script_agent(state: GuidanceState) -> Dict[str, Any]:
    data = state["input_data"]
    result = state["field_result"]["scenario_results"]
    warning = result["warning"]
    serious = result["serious"]
    rain = data["forecast"]
    recipient = data["recipient_label"]
    location = data["location_label"]
    segments = [
        {
            "id": "intro",
            "title": "등록 농경지 사전 안내",
            "headline": f"{recipient}의 농경지입니다",
            "bullets": [location, "하루 전 예방 행동을 안내합니다", "실제 예보가 아닌 공모전용 가상 시나리오입니다"],
            "narration": f"{recipient}, 등록하신 {location} 농경지의 사전 안내입니다. 실제 예보가 아닌 홍수 예방 서비스 설명용 가상 시나리오입니다.",
            "visual": "slide",
            "minimum_seconds": 10
        },
        {
            "id": "forecast",
            "title": "예상 상황",
            "headline": f"{rain['rain_start_label']}부터 많은 비를 가정했습니다",
            "bullets": [f"24시간 예상 강수량 {rain['predicted_24h_rain_mm']}mm", f"안내 시각 {rain['decision_time_label']}", "현재 비가 오기 전 준비 시간을 확보하는 단계"],
            "narration": f"가상 시나리오에서는 {rain['rain_start_label']}부터 이십사 시간 동안 {rain['predicted_24h_rain_mm']} 밀리미터의 비를 가정했습니다. 지금은 비가 오기 전에 시설을 점검할 준비 단계입니다.",
            "visual": "slide",
            "minimum_seconds": 13
        },
        {
            "id": "digital_twin",
            "title": "디지털트윈 침수 시나리오",
            "headline": "시간이 지날수록 저지대 침수 범위가 넓어집니다",
            "bullets": [f"경계 단계 농경지 영향 {warning['inundated_percent']:.1f}%", f"심각 단계 농경지 영향 {serious['inundated_percent']:.1f}%", "휴리스틱 MVP 결과이며 공식 침수예측이 아님"],
            "narration": f"화면은 미호강 주변 엠브이피 침수 시나리오입니다. 경계 단계는 등록 농경지의 약 {warning['inundated_percent']:.1f} 퍼센트, 심각 단계는 {serious['inundated_percent']:.1f} 퍼센트가 영향받는 것으로 계산됐습니다. 공식 수리 모형 결과가 아닌 시연용 값입니다.",
            "visual": "digital_twin",
            "minimum_seconds": 18
        },
        {
            "id": "before_rain",
            "title": "오늘, 비가 오기 전에",
            "headline": "안전할 때 세 가지만 확인합니다",
            "bullets": ["1. 주변 배수로와 막힌 곳 확인", "2. 농기계를 안전한 장소로 이동", "3. 비닐하우스와 지주시설 결박 확인"],
            "narration": "비가 오기 전에만 배수로를 확인하고, 농기계는 안전한 곳으로 옮겨 두십시오. 비닐하우스와 지주시설의 결박도 확인합니다. 어두워지거나 비가 시작되면 작업을 중단하십시오.",
            "visual": "slide",
            "minimum_seconds": 18
        },
        {
            "id": "during_rain",
            "title": "비가 시작된 뒤에는",
            "headline": "논밭으로 확인하러 나가지 않습니다",
            "bullets": ["논둑이나 물꼬 점검 금지", "하천변과 침수된 도로 접근 금지", "기상청·지자체 공식 안내 우선"],
            "narration": "비가 시작된 뒤에는 논둑이나 물꼬를 보러 나가지 마십시오. 하천변과 침수 도로에도 접근하지 마십시오. 기상청과 지자체의 공식 안내를 우선 확인하십시오.",
            "visual": "slide",
            "minimum_seconds": 16
        },
        {
            "id": "closing",
            "title": "공식 정보를 확인하세요",
            "headline": "이 영상은 참고자료입니다",
            "bullets": ["안전디딤돌 앱 · 기상청", "긴급상황 119", "AI 생성 참고자료 · 공식 재난예보 우선"],
            "narration": "이 영상은 인공지능 참고자료이며 공식 재난예보를 대체하지 않습니다. 실제 상황에서는 안전디딤돌 앱, 기상청, 지자체 안내를 확인하고, 긴급상황은 일일구에 연락하십시오.",
            "visual": "slide",
            "minimum_seconds": 12
        }
    ]
    return {"segments": segments, "trace": traced(state, "script_agent", {"segment_count": len(segments)})}


def safety_agent(state: GuidanceState) -> Dict[str, Any]:
    policy = state["policy"]
    combined = " ".join(segment["narration"] for segment in state["segments"])
    missing = [phrase for phrase in policy["required_phrases"] if phrase not in combined]
    forbidden = [phrase for phrase in policy["forbidden_phrases"] if phrase in combined]
    passed = not missing and not forbidden and state["input_data"]["forecast"]["is_live"] is False
    review = {
        "passed": passed,
        "mode": "deterministic_rule_review",
        "missing_required_phrases": missing,
        "forbidden_phrases_found": forbidden,
        "official_sources": policy["official_sources"],
        "live_forecast_claimed": False
    }
    if not passed:
        raise RuntimeError(f"안전성 검토 실패: {review}")
    return {"safety_review": review, "trace": traced(state, "safety_agent", {"passed": True})}


def load_font(size: int, bold: bool = False):
    return ImageFont.truetype(str(FONT_PATH), size=size, index=1 if bold else 0)


def wrapped_lines(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> List[str]:
    lines, current = [], ""
    for character in text:
        candidate = current + character
        width = draw.textbbox((0, 0), candidate, font=font)[2]
        if current and width > max_width:
            lines.append(current)
            current = character
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def create_slide(segment: Dict[str, Any], index: int, count: int, path: Path):
    width, height = 960, 540
    image = Image.new("RGB", (width, height), "#071522")
    draw = ImageDraw.Draw(image)
    for y in range(height):
        ratio = y / height
        colour = (7 + int(10 * ratio), 21 + int(24 * ratio), 34 + int(30 * ratio))
        draw.line((0, y, width, y), fill=colour)
    accent = "#43B9FF" if segment["id"] not in ("during_rain", "closing") else "#FF5A45"
    draw.rounded_rectangle((45, 35, 915, 505), radius=28, fill="#102B3D", outline="#2C5871", width=2)
    draw.rounded_rectangle((72, 62, 210, 102), radius=20, fill=accent)
    draw.text((92, 69), f"{index:02d} / {count:02d}", font=load_font(20, True), fill="#FFFFFF")
    draw.text((72, 125), segment["title"], font=load_font(28, True), fill="#B9E8FF")
    headline_lines = wrapped_lines(draw, segment["headline"], load_font(40, True), 780)
    y = 175
    for line in headline_lines[:2]:
        draw.text((72, y), line, font=load_font(40, True), fill="#FFFFFF")
        y += 51
    y += 18
    for bullet in segment["bullets"]:
        draw.ellipse((76, y + 10, 88, y + 22), fill=accent)
        draw.text((105, y), bullet, font=load_font(25), fill="#DCEBF2")
        y += 45
    draw.line((72, 458, 888, 458), fill="#315B70", width=2)
    draw.text((72, 474), "강내면 농경지 홍수 사전안내 · MVP", font=load_font(16), fill="#8EB1C1")
    image.save(path)


def create_digital_overlay(path: Path):
    image = Image.new("RGBA", (960, 540), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((42, 405, 918, 510), radius=18, fill=(4, 12, 22, 185), outline=(83, 184, 235, 220), width=2)
    draw.text((68, 423), "파란 범위는 MVP 침수 시나리오입니다", font=load_font(24, True), fill="#FFFFFF")
    draw.text((68, 462), "경계 62.5% · 심각 100% 농경지 영향", font=load_font(22), fill="#BFEAFF")
    image.save(path)


def visual_asset_agent(state: GuidanceState) -> Dict[str, Any]:
    SLIDES.mkdir(parents=True, exist_ok=True)
    slide_paths = {}
    for index, segment in enumerate(state["segments"], start=1):
        if segment["visual"] != "slide":
            continue
        path = SLIDES / f"{index:02d}_{segment['id']}.png"
        create_slide(segment, index, len(state["segments"]), path)
        slide_paths[segment["id"]] = str(path)
    overlay_path = SLIDES / "digital_twin_overlay.png"
    create_digital_overlay(overlay_path)
    segments = []
    for segment in state["segments"]:
        updated = dict(segment)
        if segment["visual"] == "slide":
            updated["visual_path"] = slide_paths[segment["id"]]
        else:
            updated["visual_path"] = state["input_data"]["digital_twin_video"]
            updated["overlay_path"] = str(overlay_path)
        segments.append(updated)
    return {"segments": segments, "trace": traced(state, "visual_asset_agent", {"slide_count": len(slide_paths), "overlay": str(overlay_path)})}


def audio_duration(path: Path) -> float:
    result = subprocess.run(["/usr/bin/afinfo", str(path)], check=True, capture_output=True, text=True)
    match = re.search(r"estimated duration:\s*([0-9.]+) sec", result.stdout)
    if not match:
        raise RuntimeError(f"TTS 길이를 읽을 수 없습니다: {path}")
    return float(match.group(1))


def tts_agent(state: GuidanceState) -> Dict[str, Any]:
    AUDIO.mkdir(parents=True, exist_ok=True)
    voice = state["input_data"]["voice"]
    assets = {}
    for index, segment in enumerate(state["segments"], start=1):
        path = AUDIO / f"{index:02d}_{segment['id']}.aiff"
        subprocess.run(
            ["/usr/bin/say", "-v", voice["name"], "-r", str(voice["rate"]), "-o", str(path), segment["narration"]],
            check=True,
        )
        duration = audio_duration(path)
        if duration <= 0.5 or path.stat().st_size <= 1024:
            raise RuntimeError(f"TTS 생성 실패: {path}")
        assets[segment["id"]] = {"path": str(path), "duration_seconds": round(duration, 3), "bytes": path.stat().st_size}
    return {"tts_assets": assets, "trace": traced(state, "tts_agent", {"voice": voice["name"], "audio_count": len(assets)})}


def timeline_agent(state: GuidanceState) -> Dict[str, Any]:
    fps = 24
    current_frame = 1
    timeline = []
    for segment in state["segments"]:
        audio = state["tts_assets"][segment["id"]]
        duration_seconds = max(segment["minimum_seconds"], math.ceil(audio["duration_seconds"] + 1.0))
        duration_frames = duration_seconds * fps
        item = {
            **segment,
            "audio_path": audio["path"],
            "audio_duration_seconds": audio["duration_seconds"],
            "duration_seconds": duration_seconds,
            "start_frame": current_frame,
            "end_frame": current_frame + duration_frames - 1,
            "duration_frames": duration_frames,
        }
        timeline.append(item)
        current_frame += duration_frames
    total_seconds = (current_frame - 1) / fps
    minimum, maximum = state["input_data"]["target_duration_seconds"]
    if not minimum <= total_seconds <= maximum:
        raise RuntimeError(f"최종 영상 길이가 목표 범위를 벗어남: {total_seconds}초")
    return {"timeline": timeline, "trace": traced(state, "timeline_agent", {"total_seconds": total_seconds, "total_frames": current_frame - 1})}


def srt_time(seconds: float) -> str:
    milliseconds = round(seconds * 1000)
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    secs, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03d}"


def subtitle_agent(state: GuidanceState) -> Dict[str, Any]:
    lines = []
    for index, segment in enumerate(state["timeline"], start=1):
        start = (segment["start_frame"] - 1) / 24
        end = segment["end_frame"] / 24
        lines.extend([str(index), f"{srt_time(start)} --> {srt_time(end)}", segment["narration"], ""])
    SRT_PATH.write_text("\n".join(lines), encoding="utf-8")
    return {"trace": traced(state, "subtitle_agent", {"subtitle_count": len(state["timeline"]), "path": str(SRT_PATH)})}


def manifest_agent(state: GuidanceState) -> Dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": "1.0",
        "run_id": state["run_id"],
        "mode": state["input_data"]["mode"],
        "fps": 24,
        "resolution": [960, 540],
        "segments": state["timeline"],
        "frame_start": 1,
        "frame_end": state["timeline"][-1]["end_frame"],
        "duration_seconds": state["timeline"][-1]["end_frame"] / 24,
        "safety_review": state["safety_review"],
        "subtitle_path": str(SRT_PATH),
        "output_video": str(FINAL_VIDEO),
        "disclaimer": "AI 생성 참고자료이며 공식 재난예보를 대체하지 않습니다."
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    SCRIPT_PATH.write_text("\n\n".join(f"[{item['title']}]\n{item['narration']}" for item in state["timeline"]), encoding="utf-8")
    return {"manifest": manifest, "trace": traced(state, "manifest_agent", {"path": str(MANIFEST_PATH)})}


def composition_agent(state: GuidanceState) -> Dict[str, Any]:
    log_path = OUT / "blender_composition.log"
    result = subprocess.run(
        [str(BLENDER), "--background", "--python", str(COMPOSER)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    log_path.write_text(result.stdout + "\n" + result.stderr, encoding="utf-8")
    if result.returncode != 0:
        raise RuntimeError(f"Blender 합성 실패. 로그: {log_path}")
    if not FINAL_VIDEO.is_file() or FINAL_VIDEO.stat().st_size < 100_000:
        raise RuntimeError("최종 안내 MP4가 생성되지 않았습니다.")
    return {"final_video": str(FINAL_VIDEO), "trace": traced(state, "composition_agent", {"video_bytes": FINAL_VIDEO.stat().st_size, "log": str(log_path)})}


def final_report_agent(state: GuidanceState) -> Dict[str, Any]:
    final_state = {
        "status": "ok",
        "run_id": state["run_id"],
        "trace": state["trace"],
        "safety_review": state["safety_review"],
        "manifest_path": str(MANIFEST_PATH),
        "script_path": str(SCRIPT_PATH),
        "subtitle_path": str(SRT_PATH),
        "final_video": state["final_video"],
        "video_bytes": Path(state["final_video"]).stat().st_size,
        "duration_seconds": state["manifest"]["duration_seconds"],
    }
    STATE_PATH.write_text(json.dumps(final_state, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"trace": traced(state, "final_report_agent", {"report": str(STATE_PATH)})}


def build_graph():
    builder = StateGraph(GuidanceState)
    nodes = [
        ("context_agent", context_agent),
        ("script_agent", script_agent),
        ("safety_agent", safety_agent),
        ("visual_asset_agent", visual_asset_agent),
        ("tts_agent", tts_agent),
        ("timeline_agent", timeline_agent),
        ("subtitle_agent", subtitle_agent),
        ("manifest_agent", manifest_agent),
        ("composition_agent", composition_agent),
        ("final_report_agent", final_report_agent),
    ]
    for name, function in nodes:
        builder.add_node(name, function)
    builder.add_edge(START, nodes[0][0])
    for (current, _), (following, _) in zip(nodes, nodes[1:]):
        builder.add_edge(current, following)
    builder.add_edge(nodes[-1][0], END)
    return builder.compile()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    graph = build_graph()
    GRAPH_PATH.write_text(graph.get_graph().draw_mermaid(), encoding="utf-8")
    result = graph.invoke({"run_id": "GANGNAE-GUIDANCE-V7", "trace": []})
    print(json.dumps({
        "status": "ok",
        "final_video": result["final_video"],
        "duration_seconds": result["manifest"]["duration_seconds"],
        "safety_passed": result["safety_review"]["passed"],
        "trace_nodes": [item["node"] for item in result["trace"]],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
