"""V22 four-agent workflow using the approved reusable dynamic digital-twin base."""
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

import guidance_v18_workflow as v18


ROOT = Path("/Users/hyeokjae/Desktop/ICTCB/flood")
DEFAULT_CONTEXT_PATH = ROOT / "data" / "runtime" / "guidance_context_v18.json"
DEFAULT_OUTPUT_ROOT = ROOT / "output" / "guidance_v22"
SILENT_BASE = ROOT / "output" / "visual_v22" / "osong_visual_v22_60s.mp4"
VISUAL_REPORT = ROOT / "output" / "visual_v22" / "scene_report.json"
VIDEO_COMPOSER = ROOT / "blender" / "compose_guidance_video_v22.py"
BLENDER = Path("/Applications/Blender.app/Contents/MacOS/Blender")
FONT_PATH = Path("/System/Library/Fonts/Supplemental/AppleGothic.ttf")
FPS = 16
DYNAMIC_END = 960
FRAME_END = 1280
MIN_DURATION_SECONDS = 60
MAX_DURATION_SECONDS = 120

StoryState = v18.StoryState
read_json = v18.read_json
write_json = v18.write_json
traced = v18.traced
gate_decision = v18.gate_decision
srt_time = v18.srt_time


def safe_run_id(context: Dict[str, Any]) -> str:
    identity = f"V22:{context['context_id']}:{context['forecast']['source'].get('mode')}"
    suffix = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:10]
    target = context.get("trigger", {}).get("target_date") or "unknown-date"
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", f"V22-{target}-{suffix}")


def segment(identifier, start_frame, end_frame, title, subtitle, narration, visual_key):
    return {
        "id": identifier,
        "start_frame": start_frame,
        "end_frame": end_frame,
        "duration_seconds": (end_frame - start_frame + 1) / FPS,
        "title": title,
        "subtitle": subtitle,
        "narration": narration,
        "visual_key": visual_key,
        "visual_type": "dynamic_video" if end_frame <= DYNAMIC_END else "information_card",
    }


def build_segments(context: Dict[str, Any]) -> List[Dict[str, Any]]:
    rain = float(context["trigger"]["rain_condition"]["value_mm"])
    shelter = context.get("shelter", {})
    actions = context.get("actions", {})
    shelter_name = shelter.get("name", "지자체 지정 재해구호시설")
    before = actions.get("before_rain", [])
    during = actions.get("during_rain", [])
    before_line = " ".join(before[:3]) or "배수로를 확인하고 시설물을 고정하며 농기계를 안전한 곳으로 옮기십시오."
    during_line = " ".join(during[:2]) or "비가 시작되면 논밭과 하천변에 접근하지 마십시오."
    return [
        segment(
            "regional_first_flood", 1, 240,
            "내일 호우 대비 안내",
            f"24시간 예상 강수 {rain:.0f}mm",
            f"기상청 단기예보에 따르면 내일 예상 강수량은 {rain:.0f} 밀리미터입니다. 예상 강수와 공식 위험자료를 바탕으로 등록 농경지 주변의 범람 위험을 보여드립니다.",
            "dynamic_base",
        ),
        segment(
            "field_reset_and_focus", 241, 400,
            "등록 농경지 확인",
            "범람 이전 상태에서 농경지로 이동",
            "화면이 범람 이전 상태로 돌아간 뒤 등록된 농경지를 확대합니다. 하천과 가까운 저지대부터 물이 접근할 가능성이 있으므로 오늘 안에 대비하십시오.",
            "dynamic_base",
        ),
        segment(
            "field_second_flood", 401, 640,
            "농경지 침수 위험",
            "비가 오기 전에 조치",
            f"물이 농경지 방향으로 확대되는 구간입니다. {before_line}",
            "dynamic_base",
        ),
        segment(
            "zoom_out_and_shelter", 641, 960,
            "침수 상태와 대피시설 위치",
            shelter_name,
            f"{during_line} 화면에 표시되는 시설은 {shelter_name}입니다. 이동이 필요하면 비가 오기 전에 시설 개방 여부와 도로 통제 상황을 확인하십시오.",
            "dynamic_base",
        ),
        segment(
            "action_card", 961, 1120,
            "비가 오기 전 행동요령",
            "안전조치는 비가 시작되기 전에 완료",
            "배수로 확인, 농기계 이동, 시설물 고정은 비가 오기 전에 마치십시오. 비가 시작된 뒤에는 논둑이나 물꼬를 확인하러 나가지 마십시오.",
            "action_card",
        ),
        segment(
            "official_information", 1121, 1280,
            "공식 안내 확인",
            "안전디딤돌·기상청·119",
            "기상청과 지자체의 재난 안내를 계속 확인하십시오. 도로가 침수됐거나 긴급한 상황이면 이동하지 말고 일일구에 신고하십시오.",
            "source_card",
        ),
    ]


def script_agent(state: StoryState) -> Dict[str, Any]:
    segments = build_segments(state["context"])
    return {
        "segments": segments,
        "trace": traced(state, "script_agent", {
            "provider": "v22_dynamic_policy_template",
            "segment_count": len(segments),
            "duration_seconds": FRAME_END / FPS,
        }),
    }


async def tts_agent(state: StoryState) -> Dict[str, Any]:
    if state["mode"] == "plan":
        assets = {
            item["id"]: {
                "path": None,
                "bytes": 0,
                "provider": "planned",
                "assigned_duration_seconds": item["duration_seconds"],
                "source_duration_seconds": 0.0,
                "cropped_seconds": 0.0,
            }
            for item in state["segments"]
        }
        meta = {
            "generation_mode": "plan_only",
            "request_count": 0,
            "provider_counts": {"planned": len(assets)},
            "timeline_duration_seconds": FRAME_END / FPS,
            "audio_crop_policy": "forced_to_segment_end_frame",
        }
        return {"tts_assets": assets, "tts_meta": meta, "trace": traced(state, "tts_agent", meta)}
    audio_dir = Path(state["run_dir"]) / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    model = os.getenv("OPENAI_TTS_MODEL", "gpt-4o-mini-tts")
    voice = os.getenv("OPENAI_TTS_VOICE", "alloy")
    speed = float(os.getenv("OPENAI_TTS_SPEED_V18", "1.12"))
    client = AsyncOpenAI(timeout=90.0, max_retries=0) if os.getenv("OPENAI_API_KEY") else None
    started = perf_counter()
    try:
        results = await asyncio.gather(*[
            v18.generate_tts_segment(client, model, voice, speed, audio_dir, index, item)
            for index, item in enumerate(state["segments"], start=1)
        ])
    finally:
        if client is not None:
            await client.close()
    assets = {}
    counts = {"openai": 0, "macos_say": 0}
    fallbacks = {}
    total_audio_seconds = 0.0
    for identifier, asset, fallback in results:
        source_duration = v18.read_audio_duration_seconds(Path(asset["path"]))
        assigned = float(asset["assigned_duration_seconds"])
        asset["source_duration_seconds"] = round(source_duration, 3)
        asset["cropped_seconds"] = round(max(0.0, source_duration - assigned), 3)
        total_audio_seconds += source_duration
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
        "source_audio_total_seconds": round(total_audio_seconds, 3),
        "timeline_duration_seconds": FRAME_END / FPS,
        "audio_crop_policy": "forced_to_segment_end_frame",
        "elapsed_seconds": round(perf_counter() - started, 3),
    }
    return {"tts_assets": assets, "tts_meta": meta, "trace": traced(state, "tts_agent", meta)}


def font(size: int):
    return ImageFont.truetype(str(FONT_PATH), size=size)


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


def validate_reusable_base() -> Dict[str, Any]:
    if not SILENT_BASE.is_file() or SILENT_BASE.stat().st_size < 100_000:
        raise RuntimeError("Approved V22 reusable silent base is missing")
    report = read_json(VISUAL_REPORT)
    if report.get("status") != "approved_silent_base_rendered":
        raise RuntimeError("V22 reusable base has not completed approval rendering")
    if float(report.get("video_duration_seconds", 0.0)) != 60.0:
        raise RuntimeError("V22 reusable base must be exactly 60 seconds")
    if report.get("reuse_policy") != "render_once_and_reuse_for_all_v22_guidance_compositions":
        raise RuntimeError("V22 base reuse policy is missing")
    return report


def video_production_agent(state: StoryState) -> Dict[str, Any]:
    run_dir = Path(state["run_dir"])
    visuals_dir = run_dir / "visuals"
    visuals_dir.mkdir(parents=True, exist_ok=True)
    if state["mode"] in {"production", "staging"}:
        base_report = validate_reusable_base()
    else:
        base_report = {"status": "planned"}
    action_card = visuals_dir / "action_card.png"
    source_card = visuals_dir / "source_card.png"
    if state["mode"] in {"production", "staging"}:
        information_card(
            action_card,
            "비가 오기 전에 마치십시오",
            "배수로·농기계·시설물 사전 점검",
            ["배수로와 물길을 확인합니다", "농기계를 높은 곳으로 옮깁니다", "비닐하우스와 시설물을 고정합니다"],
            "#FFB84D",
        )
        information_card(
            source_card,
            "공식 재난 안내를 확인하십시오",
            "안전디딤돌 · 기상청 · 지자체 · 119",
            ["비가 시작되면 논밭과 하천변에 가지 않습니다", "침수 도로를 건너지 않습니다", "긴급상황은 119에 신고합니다"],
            "#58D2FF",
        )
    visual_assets = {
        "dynamic_base": str(SILENT_BASE),
        "action_card": str(action_card),
        "source_card": str(source_card),
    }
    enriched = []
    subtitles = []
    for index, item in enumerate(state["segments"], start=1):
        audio = state["tts_assets"][item["id"]]
        enriched.append({
            **item,
            "visual_path": visual_assets[item["visual_key"]],
            "audio_path": audio["path"],
            "audio_provider": audio["provider"],
        })
        subtitles.extend([
            str(index),
            f"{srt_time((item['start_frame'] - 1) / FPS)} --> {srt_time(item['end_frame'] / FPS)}",
            item["narration"],
            "",
        ])
    manifest = {
        "schema_version": "6.0",
        "workflow_version": "V22",
        "run_id": state["run_id"],
        "mode": state["mode"],
        "context_id": state["context"]["context_id"],
        "context_source_mode": state["context"]["forecast"]["source"].get("mode"),
        "context_path": state["context_path"],
        "fps": FPS,
        "resolution": [1280, 720],
        "frame_start": 1,
        "frame_end": FRAME_END,
        "dynamic_base_end_frame": DYNAMIC_END,
        "duration_seconds": FRAME_END / FPS,
        "visual_mode": "approved_v22_dynamic_base_plus_information_cards",
        "hydraulic_event_forecast": False,
        "base_render_policy": "reuse_only_never_rerender_in_agent_workflow",
        "base_video": str(SILENT_BASE),
        "base_report_status": base_report["status"],
        "segments": enriched,
        "tts_meta": state["tts_meta"],
        "output_video": str(run_dir / "osong_guidance_v22.mp4"),
        "output_blend": str(run_dir / "osong_guidance_v22_composition.blend"),
    }
    write_json(run_dir / "guidance_manifest.json", manifest)
    (run_dir / "narration_script.txt").write_text(
        "\n\n".join(f"[{item['title']}]\n{item['narration']}" for item in enriched), encoding="utf-8"
    )
    (run_dir / "guidance_subtitles.srt").write_text("\n".join(subtitles), encoding="utf-8")
    return {
        "visual_assets": visual_assets,
        "manifest": manifest,
        "trace": traced(state, "video_production_agent", {
            "visual_mode": manifest["visual_mode"],
            "base_render_policy": manifest["base_render_policy"],
            "segment_count": len(enriched),
        }),
    }


def composition_agent(state: StoryState) -> Dict[str, Any]:
    run_dir = Path(state["run_dir"])
    if state["mode"] == "plan":
        final_trace = traced(state, "composition_agent", {"mode": "plan", "rendered": False})
        write_json(run_dir / "workflow_final_state.json", {
            "status": "planned",
            "run_id": state["run_id"],
            "context_id": state["context"]["context_id"],
            "final_video": None,
            "manifest": str(run_dir / "guidance_manifest.json"),
            "trace": final_trace,
        })
        return {"final_video": "", "trace": final_trace}
    manifest_path = run_dir / "guidance_manifest.json"
    v18.run_logged(
        [str(BLENDER), "--background", "--python", str(VIDEO_COMPOSER), "--", "--manifest", str(manifest_path)],
        ROOT,
        run_dir / "logs" / "video_composition.log",
    )
    video = Path(state["manifest"]["output_video"])
    if not video.is_file() or video.stat().st_size < 100_000 or b"ftyp" not in video.read_bytes()[:32]:
        raise RuntimeError("V22 final guidance MP4 is missing or invalid")
    final_trace = traced(state, "composition_agent", {
        "mode": state["mode"],
        "rendered": True,
        "base_rerendered": False,
    })
    write_json(run_dir / "workflow_final_state.json", {
        "status": "completed",
        "run_id": state["run_id"],
        "context_id": state["context"]["context_id"],
        "final_video": str(video),
        "video_bytes": video.stat().st_size,
        "manifest": str(manifest_path),
        "trace": final_trace,
    })
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
    builder.add_edge(START, "script_agent")
    builder.add_edge("script_agent", "tts_agent")
    builder.add_edge("tts_agent", "video_production_agent")
    builder.add_edge("video_production_agent", "composition_agent")
    builder.add_edge("composition_agent", END)
    return builder.compile()


async def run_workflow(context_path: Path, mode: str, output_root: Path) -> Dict[str, Any]:
    context_path = context_path.resolve()
    output_root = output_root.resolve()
    context = read_json(context_path)
    context["_context_path"] = str(context_path)
    gate = gate_decision(context, mode)
    output_root.mkdir(parents=True, exist_ok=True)
    write_json(output_root / "last_gate_result.json", gate)
    if not gate["accepted"]:
        return {
            "status": "skipped",
            "context_id": context.get("context_id"),
            "reason_codes": gate["reason_codes"],
            "trace_nodes": [],
            "final_video": None,
        }
    run_id = safe_run_id(context)
    run_dir = output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    graph = build_graph()
    (run_dir / "langgraph_structure.mmd").write_text(graph.get_graph().draw_mermaid(), encoding="utf-8")
    result = await graph.ainvoke({
        "run_id": run_id,
        "mode": mode,
        "context_path": str(context_path),
        "context": context,
        "run_dir": str(run_dir),
        "trace": [],
    })
    return {
        "status": "planned" if mode == "plan" else "completed",
        "run_id": run_id,
        "context_id": context["context_id"],
        "source_mode": context["forecast"]["source"].get("mode"),
        "final_video": result.get("final_video") or None,
        "manifest": str(run_dir / "guidance_manifest.json"),
        "trace_nodes": [item["node"] for item in result["trace"]],
        "tts_meta": result["tts_meta"],
    }


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--context", type=Path, default=DEFAULT_CONTEXT_PATH)
    parser.add_argument("--mode", choices=["plan", "staging", "production"], default="production")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    return parser.parse_args()


async def main():
    args = parse_args()
    load_dotenv(ROOT / ".env")
    result = await run_workflow(args.context, args.mode, args.output_root)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
