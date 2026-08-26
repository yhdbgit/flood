"""V23 four-agent workflow for event-driven personalized flood guidance."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import re
from time import perf_counter
from typing import Any, Dict, List

from dotenv import load_dotenv
from langgraph.graph import END, START, StateGraph
from openai import AsyncOpenAI
from PIL import Image, ImageDraw, ImageFont
from typing_extensions import TypedDict

import runtime_utils
from runtime_config import ROOT, blender_binary, font_path, output_root
from v23_event_contract import load_and_validate_event, validate_event
from v23_field_registry import FieldRegistry
from v23_personalized_visual_builder import build_personalized_visual_plan


DEFAULT_EVENT = ROOT / "data" / "v23" / "events" / "valid_forecast_and_hydrology.json"
DEFAULT_OUTPUT_ROOT = output_root() / "guidance_v23"
PERSONALIZED_ROOT = output_root() / "personalized_visuals" / "v23"
VISUAL_COMPOSER = ROOT / "blender" / "compose_personalized_visual_v23.py"
VISUAL_AUDITOR = ROOT / "blender" / "audit_personalized_visual_v23.py"
FINAL_COMPOSER = ROOT / "blender" / "compose_guidance_video_v23.py"
FPS = 16
PERSONALIZED_VISUAL_END = 960
FRAME_END = 1280


class StoryState(TypedDict, total=False):
    run_id: str
    mode: str
    event_path: str
    event: Dict[str, Any]
    field: Dict[str, Any]
    run_dir: str
    segments: List[Dict[str, Any]]
    tts_assets: Dict[str, Dict[str, Any]]
    tts_meta: Dict[str, Any]
    visual_assets: Dict[str, str]
    manifest: Dict[str, Any]
    final_video: str
    trace: List[Dict[str, Any]]


def read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def traced(state: StoryState, node: str, detail: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [*state.get("trace", []), {"node": node, "status": "ok", **detail}]


def slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-")


def safe_run_id(event: Dict[str, Any]) -> str:
    identity = f"{event['event_id']}:{event['user_id']}:{event['field_id']}:{event['scenario_id']}"
    suffix = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:10]
    return f"V23-{slug(event['event_id'])}-{suffix}"


def segment(identifier: str, start: int, end: int, title: str, subtitle: str, narration: str, visual_key: str) -> Dict[str, Any]:
    return {
        "id": identifier,
        "start_frame": start,
        "end_frame": end,
        "duration_seconds": (end - start + 1) / FPS,
        "title": title,
        "subtitle": subtitle,
        "narration": narration,
        "visual_key": visual_key,
        "visual_type": "dynamic_video" if end <= PERSONALIZED_VISUAL_END else "information_card",
    }


def build_segments(event: Dict[str, Any], field: Dict[str, Any]) -> List[Dict[str, Any]]:
    forecast = event["forecast_summary"]
    hydro = event["hydrology_summary"]
    metrics = field["derived_metrics"]
    shelter = field["shelter"]
    rain = float(forecast["rain_24h_mm"])
    level = float(hydro["water_level_m"])
    overlap = float(metrics["official_flood_intersection_percent"])
    field_name = field["display_name"]
    shelter_name = shelter["name"]
    distance_km = float(shelter["distance_m"]) / 1000.0
    return [
        segment(
            "regional_flood", 1, 180,
            "등록 농경지 호우 대비 안내", f"24시간 예상 강수 {rain:.0f}mm",
            f"{field_name} 주변 안내입니다. 기상예보에는 24시간 {rain:.0f} 밀리미터의 비가 예상됩니다. 화면에서 하천 주변 물의 확산 범위를 확인하십시오.",
            "personalized_visual",
        ),
        segment(
            "field_focus", 181, 360,
            "등록 농경지 위치", "범람 이전 상태에서 농경지로 이동",
            f"화면이 범람 이전으로 돌아간 뒤 등록 농경지를 확대합니다. 관측소 수위는 {level:.2f} 미터로 전달됐으며, 계속 갱신되는 기상청과 홍수통제소 정보를 함께 확인해야 합니다.",
            "personalized_visual",
        ),
        segment(
            "field_flood", 361, 560,
            "농경지 침수 위험", f"공식 위험범위 중첩 {overlap:.1f}%",
            f"환경부 100년 빈도 홍수위험 범위와 등록 농경지 경계는 약 {overlap:.1f} 퍼센트 겹칩니다. 비가 오기 전에 배수로와 막힌 곳을 확인하고 농기계를 안전한 장소로 옮기십시오.",
            "personalized_visual",
        ),
        segment(
            "field_final_state", 561, 719,
            "비가 시작되기 전 조치", "농기계 이동 · 시설물 고정",
            "비닐하우스와 지주시설의 결박 상태를 확인하고 이동 가능한 물건은 높은 곳으로 옮기십시오. 안전조치는 반드시 비가 시작되기 전에 마쳐야 합니다.",
            "personalized_visual",
        ),
        segment(
            "shelter_location", 720, 960,
            "가까운 재해구호시설", shelter_name,
            f"화면에 표시된 곳은 등록 농경지에서 약 {distance_km:.1f} 킬로미터 떨어진 {shelter_name}입니다. 이동이 필요하면 비가 오기 전에 시설 개방 여부와 도로 통제 상황을 확인하십시오.",
            "personalized_visual",
        ),
        segment(
            "action_card", 961, 1120,
            "비가 오기 전에 마치십시오", "배수로 · 농기계 · 시설물 점검",
            "배수로 확인, 농기계 이동, 시설물 고정은 비가 오기 전에 마치십시오. 비가 시작된 뒤에는 논둑이나 물꼬를 확인하러 나가지 마십시오.",
            "action_card",
        ),
        segment(
            "official_information", 1121, 1280,
            "공식 재난 안내 확인", "안전디딤돌 · 기상청 · 지자체 · 119",
            "비가 시작되면 논밭과 하천변에 접근하지 마십시오. 기상청과 지자체 안내를 계속 확인하고, 도로 침수나 긴급 상황은 일일구에 신고하십시오.",
            "source_card",
        ),
    ]


def script_agent(state: StoryState) -> Dict[str, Any]:
    segments = build_segments(state["event"], state["field"])
    return {
        "segments": segments,
        "trace": traced(state, "script_agent", {
            "provider": "v23_event_and_field_policy_template",
            "segment_count": len(segments),
            "tts_starts_at_first_frame": segments[0]["start_frame"] == 1,
            "duration_seconds": FRAME_END / FPS,
        }),
    }


async def tts_agent(state: StoryState) -> Dict[str, Any]:
    if state["mode"] == "plan":
        assets = {
            item["id"]: {"path": None, "bytes": 0, "provider": "planned", "assigned_duration_seconds": item["duration_seconds"]}
            for item in state["segments"]
        }
        meta = {"generation_mode": "plan_only", "request_count": 0, "provider_counts": {"planned": len(assets)}}
        return {"tts_assets": assets, "tts_meta": meta, "trace": traced(state, "tts_agent", meta)}
    audio_dir = Path(state["run_dir"]) / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    model = os.getenv("OPENAI_TTS_MODEL", "gpt-4o-mini-tts")
    voice = os.getenv("OPENAI_TTS_VOICE", "alloy")
    speed = float(os.getenv("OPENAI_TTS_SPEED_V23", os.getenv("OPENAI_TTS_SPEED_V18", "1.12")))
    client = AsyncOpenAI(timeout=90.0, max_retries=0) if os.getenv("OPENAI_API_KEY") else None
    started = perf_counter()
    try:
        results = await asyncio.gather(*[
            runtime_utils.generate_tts_segment(client, model, voice, speed, audio_dir, index, item)
            for index, item in enumerate(state["segments"], start=1)
        ])
    finally:
        if client is not None:
            await client.close()
    assets: Dict[str, Dict[str, Any]] = {}
    counts = {"openai": 0, "macos_say": 0}
    fallbacks = {}
    for identifier, asset, fallback in results:
        duration = runtime_utils.read_audio_duration_seconds(Path(asset["path"]))
        assigned = float(asset["assigned_duration_seconds"])
        asset["source_duration_seconds"] = round(duration, 3)
        asset["cropped_seconds"] = round(max(0.0, duration - assigned), 3)
        assets[identifier] = asset
        counts[asset["provider"]] += 1
        if fallback:
            fallbacks[identifier] = fallback
    meta = {
        "model": model,
        "voice": voice,
        "generation_mode": "async_parallel",
        "request_count": len(results),
        "provider_counts": counts,
        "fallback_types": fallbacks,
        "audio_crop_policy": "forced_to_segment_end_frame",
        "elapsed_seconds": round(perf_counter() - started, 3),
    }
    return {"tts_assets": assets, "tts_meta": meta, "trace": traced(state, "tts_agent", meta)}


def font(size: int):
    return ImageFont.truetype(str(font_path()), size=size)


def information_card(path: Path, title: str, subtitle: str, lines: List[str], accent: str) -> None:
    image = Image.new("RGB", (1280, 720), "#06131F")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((54, 46, 1226, 674), radius=34, fill="#10283A", outline=accent, width=4)
    draw.text((92, 86), title, font=font(48), fill="#FFFFFF")
    draw.text((94, 158), subtitle, font=font(31), fill=accent)
    y = 250
    for line in lines:
        draw.rounded_rectangle((92, y - 14, 1188, y + 70), radius=18, fill="#19394D")
        draw.text((124, y + 8), line, font=font(29), fill="#FFFFFF")
        y += 112
    image.save(path)


def ensure_personalized_visual(state: StoryState) -> Dict[str, Any]:
    event = state["event"]
    field = state["field"]
    run_dir = PERSONALIZED_ROOT / slug(event["event_id"])
    plan_path = run_dir / "composition_plan_v23.json"
    report_path = run_dir / "composition_report_v23.json"
    video_path = run_dir / f"{slug(field['field_id'])}_personalized_visual_v23.mp4"
    if state["mode"] == "plan":
        return {"status": "planned", "video": str(video_path), "report": str(report_path), "reused": False}
    reusable = False
    if report_path.is_file() and video_path.is_file():
        report = read_json(report_path)
        audit = report.get("decoder_audit", {})
        reusable = (
            report.get("event_id") == event["event_id"]
            and report.get("field_id") == field["field_id"]
            and audit.get("status") == "passed"
            and report.get("video_bytes") == video_path.stat().st_size
        )
    if not reusable:
        plan = build_personalized_visual_plan(event, output_root=PERSONALIZED_ROOT)
        write_json(plan_path, plan)
        logs = Path(state["run_dir"]) / "logs"
        runtime_utils.run_logged(
            [str(blender_binary()), "--background", "--python", str(VISUAL_COMPOSER), "--", "--plan", str(plan_path)],
            ROOT, logs / "personalized_visual_composition.log",
        )
        runtime_utils.run_logged(
            [str(blender_binary()), "--background", "--python", str(VISUAL_AUDITOR), "--", "--report", str(report_path)],
            ROOT, logs / "personalized_visual_audit.log",
        )
    report = read_json(report_path)
    if report.get("decoder_audit", {}).get("status") != "passed":
        raise RuntimeError("V23 personalized visual did not pass the structural audit")
    return {"status": "ready", "video": str(video_path), "report": str(report_path), "reused": reusable}


def video_production_agent(state: StoryState) -> Dict[str, Any]:
    run_dir = Path(state["run_dir"])
    visuals_dir = run_dir / "visuals"
    visuals_dir.mkdir(parents=True, exist_ok=True)
    visual = ensure_personalized_visual(state)
    action_card = visuals_dir / "action_card.png"
    source_card = visuals_dir / "source_card.png"
    if state["mode"] != "plan":
        field = state["field"]
        information_card(
            action_card, "비가 오기 전에 마치십시오", field["display_name"],
            ["배수로와 막힌 곳을 확인합니다", "농기계를 안전한 곳으로 옮깁니다", "시설물과 비닐하우스를 고정합니다"], "#FFB84D",
        )
        information_card(
            source_card, "공식 재난 안내를 확인하십시오", field["shelter"]["name"],
            ["비가 시작되면 논밭과 하천변에 가지 않습니다", "침수된 도로를 건너지 않습니다", "긴급 상황은 119에 신고합니다"], "#58D2FF",
        )
    visual_assets = {"personalized_visual": visual["video"], "action_card": str(action_card), "source_card": str(source_card)}
    enriched = []
    subtitles: List[str] = []
    for index, item in enumerate(state["segments"], start=1):
        audio = state["tts_assets"][item["id"]]
        enriched.append({**item, "visual_path": visual_assets[item["visual_key"]], "audio_path": audio["path"], "audio_provider": audio["provider"]})
        subtitles.extend([str(index), f"{runtime_utils.srt_time((item['start_frame'] - 1) / FPS)} --> {runtime_utils.srt_time(item['end_frame'] / FPS)}", item["narration"], ""])
    manifest = {
        "schema_version": "1.0",
        "workflow_version": "V23",
        "run_id": state["run_id"],
        "mode": state["mode"],
        "event_id": state["event"]["event_id"],
        "field_id": state["field"]["field_id"],
        "user_id": state["event"]["user_id"],
        "scenario_id": state["event"]["scenario_id"],
        "fps": FPS,
        "resolution": [1280, 720],
        "frame_start": 1,
        "frame_end": FRAME_END,
        "personalized_visual_end_frame": PERSONALIZED_VISUAL_END,
        "duration_seconds": FRAME_END / FPS,
        "visual_mode": "v23_field_specific_cached_visual_plus_information_cards",
        "base_render_policy": "cached_personalized_visual_reuse_no_3d_rerender",
        "personalized_visual": visual,
        "segments": enriched,
        "tts_meta": state["tts_meta"],
        "output_video": str(run_dir / f"{slug(state['field']['field_id'])}_guidance_v23.mp4"),
        "output_blend": str(run_dir / f"{slug(state['field']['field_id'])}_guidance_v23_composition.blend"),
    }
    write_json(run_dir / "guidance_manifest.json", manifest)
    (run_dir / "narration_script.txt").write_text("\n\n".join(f"[{item['title']}]\n{item['narration']}" for item in enriched), encoding="utf-8")
    (run_dir / "guidance_subtitles.srt").write_text("\n".join(subtitles), encoding="utf-8")
    return {
        "visual_assets": visual_assets,
        "manifest": manifest,
        "trace": traced(state, "video_production_agent", {"visual_reused": visual["reused"], "segment_count": len(enriched), "full_3d_rerender": False}),
    }


def composition_agent(state: StoryState) -> Dict[str, Any]:
    run_dir = Path(state["run_dir"])
    manifest_path = run_dir / "guidance_manifest.json"
    if state["mode"] == "plan":
        trace = traced(state, "composition_agent", {"mode": "plan", "rendered": False})
        write_json(run_dir / "workflow_final_state.json", {"status": "planned", "run_id": state["run_id"], "final_video": None, "trace": trace})
        return {"final_video": "", "trace": trace}
    started = perf_counter()
    runtime_utils.run_logged(
        [str(blender_binary()), "--background", "--python", str(FINAL_COMPOSER), "--", "--manifest", str(manifest_path)],
        ROOT, run_dir / "logs" / "final_composition.log",
    )
    video = Path(state["manifest"]["output_video"])
    if not video.is_file() or video.stat().st_size < 100_000 or b"ftyp" not in video.read_bytes()[:32]:
        raise RuntimeError("V23 final guidance MP4 is missing or invalid")
    trace = traced(state, "composition_agent", {"mode": state["mode"], "rendered": True, "elapsed_seconds": round(perf_counter() - started, 3), "full_3d_rerender": False})
    write_json(run_dir / "workflow_final_state.json", {"status": "completed", "run_id": state["run_id"], "final_video": str(video), "video_bytes": video.stat().st_size, "trace": trace})
    return {"final_video": str(video), "trace": trace}


def build_graph():
    builder = StateGraph(StoryState)
    for name, function in [
        ("script_agent", script_agent),
        ("tts_agent", tts_agent),
        ("video_production_agent", video_production_agent),
        ("composition_agent", composition_agent),
    ]:
        builder.add_node(name, function)
    builder.add_edge(START, "script_agent")
    builder.add_edge("script_agent", "tts_agent")
    builder.add_edge("tts_agent", "video_production_agent")
    builder.add_edge("video_production_agent", "composition_agent")
    builder.add_edge("composition_agent", END)
    return builder.compile()


async def run_workflow_event(event: Dict[str, Any], mode: str, output_root: Path, event_path: Path | None = None) -> Dict[str, Any]:
    event = validate_event(event)
    field = FieldRegistry.load().resolve_event(event)
    run_id = safe_run_id(event)
    run_dir = output_root.resolve() / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    graph = build_graph()
    (run_dir / "langgraph_structure.mmd").write_text(graph.get_graph().draw_mermaid(), encoding="utf-8")
    result = await graph.ainvoke({"run_id": run_id, "mode": mode, "event_path": str(event_path) if event_path else None, "event": event, "field": field, "run_dir": str(run_dir), "trace": []})
    return {
        "status": "planned" if mode == "plan" else "completed",
        "run_id": run_id,
        "event_id": event["event_id"],
        "field_id": field["field_id"],
        "final_video": result.get("final_video") or None,
        "manifest": str(run_dir / "guidance_manifest.json"),
        "trace_nodes": [item["node"] for item in result["trace"]],
        "tts_meta": result["tts_meta"],
    }


async def run_workflow(event_path: Path, mode: str, output_root: Path) -> Dict[str, Any]:
    event_path = event_path.resolve()
    return await run_workflow_event(load_and_validate_event(event_path), mode, output_root, event_path=event_path)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--event", type=Path, default=DEFAULT_EVENT)
    parser.add_argument("--mode", choices=["plan", "staging", "production"], default="staging")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    return parser.parse_args()


async def main():
    args = parse_args()
    load_dotenv(ROOT / ".env")
    result = await run_workflow(args.event, args.mode, args.output_root)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
