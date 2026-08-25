"""V18 context-gated four-agent flood guidance video workflow."""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
from time import perf_counter
from typing import Any, Dict, List

from dotenv import load_dotenv
from langgraph.graph import END, START, StateGraph
from openai import AsyncOpenAI
from PIL import Image, ImageDraw, ImageFont
from typing_extensions import TypedDict


ROOT = Path("/Users/hyeokjae/Desktop/ICTCB/flood")
DEFAULT_CONTEXT_PATH = ROOT / "data" / "runtime" / "guidance_context_v18.json"
DEFAULT_OUTPUT_ROOT = ROOT / "output" / "guidance_v18"
PREVIEW_OUT = ROOT / "output" / "guidance_v18_preview"
PREVIEW_REPORT = PREVIEW_OUT / "scene_report.json"
BLENDER = Path("/Applications/Blender.app/Contents/MacOS/Blender")
SCENE_SOURCE = ROOT / "blender" / "osong_inundation_v16.blend"
SCENE_APPLIER = ROOT / "blender" / "apply_guidance_context_v18.py"
PREVIEW_COMPOSER = ROOT / "scripts" / "compose_v18_previews.py"
PREVIEW_VALIDATOR = ROOT / "scripts" / "validate_v18_previews.py"
VIDEO_COMPOSER = ROOT / "blender" / "compose_guidance_video_v18.py"
FONT_PATH = Path("/System/Library/Fonts/Supplemental/AppleGothic.ttf")
FPS = 24
FRAME_END = 1440
MIN_DURATION_SECONDS = 60
MAX_DURATION_SECONDS = 120
TTS_PADDING_SECONDS = 1.0


class StoryState(TypedDict, total=False):
    run_id: str
    mode: str
    context_path: str
    context: Dict[str, Any]
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


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def traced(state: StoryState, node: str, detail: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [*state.get("trace", []), {"node": node, "status": "ok", **detail}]


def safe_run_id(context: Dict[str, Any]) -> str:
    identity = f"{context['context_id']}:{context['forecast']['source'].get('mode')}"
    suffix = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:10]
    target = context.get("trigger", {}).get("target_date") or "unknown-date"
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", f"V18-{target}-{suffix}")


def gate_decision(context: Dict[str, Any], mode: str) -> Dict[str, Any]:
    reasons = []
    if context.get("schema_version") != "1.0":
        reasons.append("UNSUPPORTED_CONTEXT_SCHEMA")
    if context.get("status") != "ready":
        reasons.extend(context.get("trigger", {}).get("reason_codes") or ["CONTEXT_NOT_READY"])
    if not context.get("trigger", {}).get("should_generate_video"):
        reasons.append("VIDEO_TRIGGER_FALSE")
    source_mode = context.get("forecast", {}).get("source", {}).get("mode")
    if mode == "production" and source_mode != "live":
        reasons.append("FIXTURE_NOT_ALLOWED_IN_PRODUCTION")
    if context.get("inundation", {}).get("hydraulic_event_forecast") is not False:
        reasons.append("UNSUPPORTED_HYDRAULIC_FORECAST_CLAIM")
    reasons = list(dict.fromkeys(reasons))
    return {
        "accepted": not reasons,
        "status": "accepted" if not reasons else "skipped",
        "mode": mode,
        "context_id": context.get("context_id"),
        "source_mode": source_mode,
        "reason_codes": reasons,
    }


def korean_datetime_label(value: str | None, fallback: str) -> str:
    if not value:
        return fallback
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return fallback
    return f"{parsed.month}월 {parsed.day}일 {parsed.hour}시"


def segment(
    identifier: str,
    start_frame: int,
    end_frame: int,
    title: str,
    subtitle: str,
    narration: str,
    visual_key: str,
) -> Dict[str, Any]:
    return {
        "id": identifier,
        "start_frame": start_frame,
        "end_frame": end_frame,
        "duration_seconds": (end_frame - start_frame + 1) / FPS,
        "title": title,
        "subtitle": subtitle,
        "narration": narration,
        "visual_key": visual_key,
        "visual_type": "full_frame",
    }


def build_segments(context: Dict[str, Any]) -> List[Dict[str, Any]]:
    forecast = context["forecast"]
    trigger = context["trigger"]
    rain = float(trigger["rain_condition"]["value_mm"])
    affected = float(context["inundation"]["field_affected_percent"])
    field = context["field"]
    shelter = context.get("shelter", {})
    route = context.get("route", {})
    before = context.get("actions", {}).get("before_rain", [])
    during = context.get("actions", {}).get("during_rain", [])
    base_label = korean_datetime_label(forecast.get("base_datetime"), "오늘 아침")
    rain_label = korean_datetime_label(forecast.get("rain_24h", {}).get("first_rain_at"), "내일")
    before_text = " ".join(before[:3])
    during_text = " ".join(during[:2])
    shelter_name = shelter.get("name", "지자체 지정 재해구호시설")
    route_km = float(route.get("route_length_m") or 0.0) / 1000.0
    return [
        segment(
            "forecast_overview", 1, 240,
            "내일 호우 대비 안내",
            f"{base_label} 발표 · 24시간 예상 강수 {rain:.0f}mm",
            f"기상청 단기예보에 따르면 오송읍의 내일 예상 강수량은 {rain:.0f} 밀리미터입니다. 등록 농경지 주변을 확인하겠습니다.",
            "normal_overview",
        ),
        segment(
            "official_hazard_overview", 241, 480,
            "환경부 공식 홍수위험범위",
            "100년 빈도 위험범위 참고",
            "환경부 백 년 빈도 홍수위험지도에서 미호강 주변과 등록 농경지가 위험범위에 포함됩니다.",
            "hazard_overview",
        ),
        segment(
            "registered_field_close", 481, 960,
            "등록 농경지 위험범위 중첩",
            f"등록 농경지 약 {affected:.1f}%",
            f"등록 농경지의 약 {affected:.1f} 퍼센트가 공식 위험범위와 겹칩니다. 비가 오기 전에 배수로를 확인하고 시설물을 고정한 뒤 농기계를 안전한 곳으로 옮기십시오.",
            "field_close",
        ),
        segment(
            "during_rain_actions", 961, 1200,
            "비가 시작되면 접근 금지",
            f"예상 강수 시작 {rain_label}",
            "비가 시작되면 논둑이나 물꼬를 확인하러 나가지 말고, 하천변과 침수 도로에 접근하지 마십시오.",
            "action_card",
        ),
        segment(
            "shelter_guidance", 1201, 1440,
            "사전 이동과 공식 안내 확인",
            f"{shelter_name} · 표시 경로 약 {route_km:.1f}km",
            f"대피가 필요하면 비가 오기 전에 {shelter_name}으로 이동하십시오. 개방 여부를 확인하고 긴급상황은 일일구에 신고하십시오.",
            "shelter_card",
        ),
    ]



def retime_segments_for_audio(
    segments: List[Dict[str, Any]],
    assets: Dict[str, Dict[str, Any]],
) -> tuple[List[Dict[str, Any]], float]:
    """Extend the base storyboard to fit TTS while keeping a 60-120 second runtime."""
    cursor = 1
    retimed = []
    for item in segments:
        identifier = item["id"]
        asset = assets.get(identifier)
        if asset is None or "source_duration_seconds" not in asset:
            raise RuntimeError(f"TTS duration is missing for segment: {identifier}")
        source_duration = float(asset["source_duration_seconds"])
        assigned_seconds = max(
            float(item["duration_seconds"]),
            math.ceil(source_duration + TTS_PADDING_SECONDS),
        )
        frame_count = math.ceil(assigned_seconds * FPS)
        duration_seconds = frame_count / FPS
        end_frame = cursor + frame_count - 1
        retimed.append({
            **item,
            "start_frame": cursor,
            "end_frame": end_frame,
            "duration_seconds": duration_seconds,
        })
        asset["assigned_duration_seconds"] = duration_seconds
        asset["cropped_seconds"] = round(max(0.0, source_duration - duration_seconds), 3)
        cursor = end_frame + 1

    timeline_seconds = (cursor - 1) / FPS
    if timeline_seconds < MIN_DURATION_SECONDS:
        raise RuntimeError(f"V18 timeline is shorter than {MIN_DURATION_SECONDS} seconds")
    if timeline_seconds > MAX_DURATION_SECONDS:
        raise RuntimeError(
            f"TTS timeline exceeds {MAX_DURATION_SECONDS} seconds: {timeline_seconds:.3f}"
        )
    return retimed, timeline_seconds


def script_agent(state: StoryState) -> Dict[str, Any]:
    context = state["context"]
    segments = build_segments(context)
    return {
        "segments": segments,
        "trace": traced(state, "script_agent", {
            "provider": "v18_policy_template",
            "context_id": context["context_id"],
            "source_mode": context["forecast"]["source"].get("mode"),
            "segment_count": len(segments),
        }),
    }


async def write_openai_audio(client, model, voice, text, speed, path):
    path.unlink(missing_ok=True)
    response = await client.audio.speech.create(
        model=model,
        voice=voice,
        input=text,
        instructions="고령 농업인이 이해하기 쉽도록 침착하고 또렷한 한국어로 읽으세요. 숫자와 시간은 정확하게 읽으세요.",
        response_format="mp3",
        speed=speed,
        timeout=90.0,
    )
    await asyncio.to_thread(response.write_to_file, path)


async def write_local_audio(text, path):
    path.unlink(missing_ok=True)
    process = await asyncio.create_subprocess_exec(
        "/usr/bin/say", "-v", "Yuna", "-r", "190", "-o", str(path), text,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    if process.returncode != 0:
        raise RuntimeError(stderr.decode("utf-8", errors="replace")[:500])


async def generate_tts_segment(client, model, voice, speed, audio_dir, index, item):
    provider = "openai"
    fallback_reason = None
    try:
        if client is None:
            raise RuntimeError("OPENAI_API_KEY is missing")
        path = audio_dir / f"{index:02d}_{item['id']}.mp3"
        await write_openai_audio(client, model, voice, item["narration"], speed, path)
    except Exception as exc:
        provider = "macos_say"
        fallback_reason = type(exc).__name__
        path = audio_dir / f"{index:02d}_{item['id']}.aiff"
        await write_local_audio(item["narration"], path)
    return item["id"], {
        "path": str(path),
        "bytes": path.stat().st_size,
        "provider": provider,
        "assigned_duration_seconds": item["duration_seconds"],
    }, fallback_reason


def read_audio_duration_seconds(path: Path) -> float:
    result = subprocess.run(["/usr/bin/afinfo", str(path)], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Could not inspect TTS audio duration: {path}")
    match = re.search(r"estimated duration:\s+([0-9.]+) sec", result.stdout)
    if not match:
        raise RuntimeError(f"TTS audio duration was not reported: {path}")
    return float(match.group(1))


async def tts_agent(state: StoryState) -> Dict[str, Any]:
    if state["mode"] == "plan":
        assets = {
            item["id"]: {
                "path": None,
                "bytes": 0,
                "provider": "planned",
                "assigned_duration_seconds": item["duration_seconds"],
            }
            for item in state["segments"]
        }
        meta = {"generation_mode": "plan_only", "request_count": 0, "provider_counts": {"planned": len(assets)}}
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
            generate_tts_segment(client, model, voice, speed, audio_dir, index, item)
            for index, item in enumerate(state["segments"], start=1)
        ])
    finally:
        if client is not None:
            await client.close()
    assets = {}
    counts = {"openai": 0, "macos_say": 0}
    fallbacks = {}
    for identifier, asset, fallback in results:
        assets[identifier] = asset
        counts[asset["provider"]] += 1
        if fallback:
            fallbacks[identifier] = fallback
    total_audio_seconds = 0.0
    for identifier, asset in assets.items():
        source_duration = read_audio_duration_seconds(Path(asset["path"]))
        total_audio_seconds += source_duration
        asset["source_duration_seconds"] = round(source_duration, 3)
    retimed_segments, timeline_seconds = retime_segments_for_audio(state["segments"], assets)
    meta = {
        "model": model,
        "source_audio_total_seconds": round(total_audio_seconds, 3),
        "timeline_duration_seconds": round(timeline_seconds, 3),
        "timeline_policy": "minimum_60_dynamic_up_to_120",
        "segment_padding_seconds": TTS_PADDING_SECONDS,
        "voice": voice,
        "generation_mode": "async_parallel",
        "request_count": len(results),
        "provider_counts": counts,
        "fallback_types": fallbacks,
        "elapsed_seconds": round(perf_counter() - started, 3),
    }
    return {
        "segments": retimed_segments,
        "tts_assets": assets,
        "tts_meta": meta,
        "trace": traced(state, "tts_agent", meta),
    }


def font(size: int, bold=False):
    return ImageFont.truetype(str(FONT_PATH), size=size)


def information_card(path: Path, title: str, subtitle: str, lines: List[str], accent: str) -> None:
    image = Image.new("RGB", (960, 540), "#071522")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((28, 26, 932, 514), radius=26, fill="#10283A", outline=accent, width=3)
    draw.text((60, 58), title, font=font(36, True), fill="#FFFFFF")
    draw.text((62, 112), subtitle, font=font(23), fill=accent)
    y = 190
    for line in lines:
        draw.rounded_rectangle((60, y - 10, 900, y + 52), radius=14, fill="#18384B")
        draw.text((82, y + 5), line, font=font(22), fill="#FFFFFF")
        y += 82
    image.save(path)


def run_logged(command: List[str], cwd: Path, log_path: Path) -> None:
    result = subprocess.run(command, cwd=str(cwd), capture_output=True, text=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(result.stdout + "\n" + result.stderr, encoding="utf-8")
    if result.returncode != 0:
        raise RuntimeError(f"Command failed; inspect {log_path}")


def ensure_context_previews(context: Dict[str, Any], run_dir: Path) -> Dict[str, Any]:
    if PREVIEW_REPORT.is_file():
        report = read_json(PREVIEW_REPORT)
        if (
            report.get("status") == "validated_ready_for_workflow_integration"
            and report.get("context_id") == context["context_id"]
            and report.get("source_mode") == context["forecast"]["source"].get("mode")
        ):
            return {"policy": "reused_matching_context", "report": report}
    if Path(context.get("_context_path", "")).resolve() != DEFAULT_CONTEXT_PATH.resolve():
        raise RuntimeError("Production scene generation requires the canonical V18 runtime context path")
    run_logged(
        [str(BLENDER), "--background", str(SCENE_SOURCE), "--python", str(SCENE_APPLIER)],
        ROOT,
        run_dir / "logs" / "scene_apply.log",
    )
    run_logged(
        [os.environ.get("PYTHON", "python3"), str(PREVIEW_COMPOSER)],
        ROOT,
        run_dir / "logs" / "preview_compose.log",
    )
    run_logged(
        [os.environ.get("PYTHON", "python3"), str(PREVIEW_VALIDATOR)],
        ROOT,
        run_dir / "logs" / "preview_validate.log",
    )
    report = read_json(PREVIEW_REPORT)
    if report.get("status") != "validated_ready_for_workflow_integration":
        raise RuntimeError("V18 preview validation did not pass")
    return {"policy": "rendered_for_context", "report": report}


def srt_time(seconds: float) -> str:
    milliseconds = round(seconds * 1000)
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    seconds, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"


def video_production_agent(state: StoryState) -> Dict[str, Any]:
    run_dir = Path(state["run_dir"])
    visuals_dir = run_dir / "visuals"
    visuals_dir.mkdir(parents=True, exist_ok=True)
    context = state["context"]
    if state["mode"] in {"production", "staging"}:
        preview_meta = ensure_context_previews(context, run_dir)
    else:
        preview_meta = {"policy": "planned", "report": None}

    actions = context.get("actions", {})
    shelter = context.get("shelter", {})
    route = context.get("route", {})
    action_card = visuals_dir / "action_card.png"
    shelter_card = visuals_dir / "shelter_card.png"
    if state["mode"] in {"production", "staging"}:
        information_card(
            action_card,
            "비가 시작되면 농경지에 가지 마십시오",
            "기상청·지자체 공식 안내를 우선 확인하십시오",
            actions.get("during_rain", [])[:3],
            "#FFB84D",
        )
        information_card(
            shelter_card,
            "비 오기 전 사전 이동 안내",
            shelter.get("name", "지자체 지정 재해구호시설"),
            [
                shelter.get("address", "시설 주소는 지자체 안내에서 확인"),
                f"표시 경로 약 {float(route.get('route_length_m') or 0) / 1000:.1f}km",
                "시설 개방과 도로 통제 여부를 먼저 확인하십시오",
            ],
            "#58D2FF",
        )
    visual_assets = {
        "normal_overview": str(PREVIEW_OUT / "01_normal_overview.png"),
        "hazard_overview": str(PREVIEW_OUT / "02_hazard_overview.png"),
        "field_close": str(PREVIEW_OUT / "03_field_close.png"),
        "action_card": str(action_card),
        "shelter_card": str(shelter_card),
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
    frame_end = state["segments"][-1]["end_frame"]
    duration_seconds = frame_end / FPS
    manifest = {
        "schema_version": "5.0",
        "workflow_version": "V18",
        "run_id": state["run_id"],
        "mode": state["mode"],
        "context_id": context["context_id"],
        "context_source_mode": context["forecast"]["source"].get("mode"),
        "context_path": state["context_path"],
        "fps": FPS,
        "resolution": [960, 540],
        "frame_start": 1,
        "frame_end": frame_end,
        "duration_seconds": duration_seconds,
        "visual_mode": "context_specific_stage_slideshow",
        "hydraulic_event_forecast": False,
        "preview_cache_policy": preview_meta["policy"],
        "segments": enriched,
        "tts_meta": state["tts_meta"],
        "output_video": str(run_dir / "osong_guidance_v18.mp4"),
        "output_blend": str(run_dir / "osong_guidance_v18_composition.blend"),
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
            "preview_cache_policy": preview_meta["policy"],
            "segment_count": len(enriched),
        }),
    }


def composition_agent(state: StoryState) -> Dict[str, Any]:
    run_dir = Path(state["run_dir"])
    if state["mode"] == "plan":
        final_trace = traced(state, "composition_agent", {"mode": "plan", "rendered": False})
        report = {
            "status": "planned",
            "run_id": state["run_id"],
            "context_id": state["context"]["context_id"],
            "final_video": None,
            "manifest": str(run_dir / "guidance_manifest.json"),
            "trace": final_trace,
        }
        write_json(run_dir / "workflow_final_state.json", report)
        return {"final_video": "", "trace": final_trace}

    manifest_path = run_dir / "guidance_manifest.json"
    run_logged(
        [str(BLENDER), "--background", "--python", str(VIDEO_COMPOSER), "--", "--manifest", str(manifest_path)],
        ROOT,
        run_dir / "logs" / "video_composition.log",
    )
    video = Path(state["manifest"]["output_video"])
    if not video.is_file() or video.stat().st_size < 100_000 or b"ftyp" not in video.read_bytes()[:32]:
        raise RuntimeError("V18 final MP4 is missing or invalid")
    final_trace = traced(state, "composition_agent", {"mode": state["mode"], "rendered": True})
    report = {
        "status": "completed",
        "run_id": state["run_id"],
        "context_id": state["context"]["context_id"],
        "final_video": str(video),
        "video_bytes": video.stat().st_size,
        "manifest": str(manifest_path),
        "trace": final_trace,
    }
    write_json(run_dir / "workflow_final_state.json", report)
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


async def run_workflow(context_path: Path, mode: str, output_root: Path) -> Dict[str, Any]:
    context_path = context_path.resolve()
    output_root = output_root.resolve()
    context = read_json(context_path)
    context["_context_path"] = str(context_path.resolve())
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
        "context_path": str(context_path.resolve()),
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
