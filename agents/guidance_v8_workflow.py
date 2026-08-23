"""V8: OpenAI script/TTS enhancement with deterministic safety and offline fallbacks."""

import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any, Dict, List

from dotenv import load_dotenv
from langgraph.graph import END, START, StateGraph
from openai import OpenAI
from typing_extensions import TypedDict

from agents import guidance_v7_workflow as base


ROOT = Path("/Users/hyeokjae/Desktop/ICTCB/flood")
OUT = ROOT / "output" / "guidance_v8"
SLIDES = OUT / "slides"
AUDIO = OUT / "audio"
MANIFEST_PATH = OUT / "guidance_manifest.json"
STATE_PATH = OUT / "workflow_final_state.json"
SCRIPT_PATH = OUT / "narration_script.txt"
SRT_PATH = OUT / "guidance_subtitles.srt"
GRAPH_PATH = OUT / "langgraph_structure.mmd"
FINAL_VIDEO = OUT / "gangnae_guidance_v8.mp4"
COMPOSER = ROOT / "blender" / "compose_guidance_video_v8.py"

# V7의 검증된 시각화·자막·Blender 합성 기능이 V8 전용 경로를 사용하도록 설정한다.
base.OUT = OUT
base.SLIDES = SLIDES
base.AUDIO = AUDIO
base.MANIFEST_PATH = MANIFEST_PATH
base.STATE_PATH = STATE_PATH
base.SCRIPT_PATH = SCRIPT_PATH
base.SRT_PATH = SRT_PATH
base.GRAPH_PATH = GRAPH_PATH
base.FINAL_VIDEO = FINAL_VIDEO
base.COMPOSER = COMPOSER


class GuidanceState(TypedDict, total=False):
    run_id: str
    input_data: Dict[str, Any]
    policy: Dict[str, Any]
    field_result: Dict[str, Any]
    segments: List[Dict[str, Any]]
    generation_meta: Dict[str, Any]
    safety_review: Dict[str, Any]
    tts_assets: Dict[str, Dict[str, Any]]
    tts_meta: Dict[str, Any]
    timeline: List[Dict[str, Any]]
    manifest: Dict[str, Any]
    final_video: str
    trace: List[Dict[str, Any]]


SEGMENT_SPECS = [
    {"id": "intro", "max_chars": 120},
    {"id": "forecast", "max_chars": 150},
    {"id": "digital_twin", "max_chars": 190},
    {"id": "before_rain", "max_chars": 180},
    {"id": "during_rain", "max_chars": 160},
    {"id": "closing", "max_chars": 150},
]
EXPECTED_IDS = [item["id"] for item in SEGMENT_SPECS]
SCRIPT_SCHEMA = {
    "type": "object",
    "properties": {
        "segments": {
            "type": "array",
            "minItems": 6,
            "maxItems": 6,
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "enum": EXPECTED_IDS},
                    "title": {"type": "string"},
                    "headline": {"type": "string"},
                    "narration": {"type": "string"},
                },
                "required": ["id", "title", "headline", "narration"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["segments"],
    "additionalProperties": False,
}


def traced(state: GuidanceState, node: str, detail: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [*state.get("trace", []), {"node": node, "status": "ok", **detail}]


def safe_error(exc: Exception) -> str:
    message = str(exc).replace("\n", " ")[:300]
    message = re.sub(r"sk-[A-Za-z0-9_-]+", "[REDACTED]", message)
    return re.sub(r"(?i)(api[_ -]?key)[=: ]+[^ ,;]+", r"\1=[REDACTED]", message)


def rule_segments(state: GuidanceState) -> List[Dict[str, Any]]:
    """V7에서 검증된 고정 대본을 네트워크·안전 실패 시 사용한다."""
    segments = base.script_agent(state)["segments"]
    recipient = state["input_data"]["recipient_label"]
    segments[0]["narration"] = f"{recipient}, 등록 농경지 사전 안내입니다. 실제 예보가 아닌 공모전용 가상 시나리오입니다."
    segments[-1]["bullets"][-1] = "AI 생성 음성·영상 참고자료 · 공식 재난예보 우선"
    segments[-1]["narration"] = "AI 생성 음성을 사용했습니다. 이 영상은 참고자료이며 공식 재난예보를 대체하지 않습니다. 공식 안내를 확인하고 긴급상황은 일일구에 연락하십시오."
    return segments


def anonymized_payload(state: GuidanceState) -> Dict[str, Any]:
    data = state["input_data"]
    scenario = state["field_result"]["scenario_results"]
    policy = state["policy"]
    return {
        "privacy": "정확한 수신자 이름과 필지 식별자는 전송하지 않음. intro에 [수신자]만 사용",
        "location": data["location_label"],
        "forecast": {
            "mode": "실시간 예보가 아닌 공모전 시연용 가상 시나리오",
            "decision_time_label": data["forecast"]["decision_time_label"],
            "rain_start_label": data["forecast"]["rain_start_label"],
            "predicted_24h_rain_mm": data["forecast"]["predicted_24h_rain_mm"],
        },
        "field_impact": {
            "warning_inundated_percent": round(scenario["warning"]["inundated_percent"], 1),
            "serious_inundated_percent": round(scenario["serious"]["inundated_percent"], 1),
            "accuracy": "휴리스틱 MVP이며 공식 수리 모형 결과가 아님",
        },
        "allowed_before_rain_actions": policy["allowed_before_rain_actions"],
        "required_during_rain_actions": policy["required_during_rain_actions"],
        "required_phrases": [*policy["required_phrases"], "AI 생성 음성"],
        "forbidden_phrases": policy["forbidden_phrases"],
        "segment_character_limits": {item["id"]: item["max_chars"] for item in SEGMENT_SPECS},
    }


def merge_generated(raw: List[Dict[str, Any]], fixed: List[Dict[str, Any]], recipient: str) -> List[Dict[str, Any]]:
    by_id = {item.get("id"): item for item in raw}
    merged = []
    for spec, fallback in zip(SEGMENT_SPECS, fixed):
        generated = by_id.get(spec["id"], {})
        item = {
            **fallback,
            "title": str(generated.get("title", fallback["title"])).strip(),
            "headline": str(generated.get("headline", fallback["headline"])).strip(),
            "narration": str(generated.get("narration", fallback["narration"])).strip(),
        }
        if item["id"] in {"intro", "forecast", "digital_twin", "during_rain", "closing"}:
            item["narration"] = fallback["narration"]
        if item["id"] in {"digital_twin", "during_rain", "closing"}:
            item["title"] = fallback["title"]
            item["headline"] = fallback["headline"]
        replacement = recipient if item["id"] == "intro" else "어르신"
        item["headline"] = item["headline"].replace("[수신자]", replacement)
        item["narration"] = item["narration"].replace("[수신자]", replacement)
        if item["id"] == "intro" and recipient not in item["narration"]:
            item["narration"] = f"{recipient}, {item['narration']}"
        if item["id"] == "intro" and "가상 시나리오" not in item["narration"]:
            item["narration"] += " 실제 예보가 아닌 공모전용 가상 시나리오입니다."
        merged.append(item)
    return merged


def review_segments(segments: List[Dict[str, Any]], state: GuidanceState) -> Dict[str, Any]:
    policy = state["policy"]
    ids = [item.get("id") for item in segments]
    combined = " ".join(
        " ".join([
            str(item.get("title", "")),
            str(item.get("headline", "")),
            *[str(value) for value in item.get("bullets", [])],
            str(item.get("narration", "")),
        ])
        for item in segments
    )
    required_phrases = [*policy["required_phrases"], "AI 생성 음성"]
    missing = [phrase for phrase in required_phrases if phrase not in combined]
    forbidden = [phrase for phrase in policy["forbidden_phrases"] if phrase in combined]
    scenario = state["field_result"]["scenario_results"]
    required_numbers = [
        str(state["input_data"]["forecast"]["predicted_24h_rain_mm"]),
        f"{scenario['warning']['inundated_percent']:.1f}",
        f"{scenario['serious']['inundated_percent']:.1f}",
    ]
    missing_numbers = [value for value in required_numbers if value not in combined]
    overlong = {}
    if len(segments) == len(SEGMENT_SPECS):
        overlong = {
            item["id"]: len(item.get("narration", ""))
            for item, spec in zip(segments, SEGMENT_SPECS)
            if len(item.get("narration", "")) > spec["max_chars"]
        }
    else:
        overlong = {"segment_count": len(segments)}
    before_text = next((item.get("narration", "") for item in segments if item.get("id") == "before_rain"), "")
    missing_action_keywords = [word for word in ("배수로", "농기계", "비닐하우스") if word not in before_text]
    by_id = {item.get("id"): item.get("narration", "") for item in segments}
    segment_requirements = {
        "intro": ["가상 시나리오"],
        "forecast": [state["input_data"]["forecast"]["rain_start_label"], str(state["input_data"]["forecast"]["predicted_24h_rain_mm"]), "비가 오기 전에"],
        "digital_twin": [f"경계 단계는 등록 농경지의 약 {scenario['warning']['inundated_percent']:.1f} 퍼센트", f"심각 단계는 {scenario['serious']['inundated_percent']:.1f} 퍼센트", "공식 수리 모형"],
        "during_rain": ["논둑이나 물꼬를 보러 나가지 마십시오", "공식 안내"],
        "closing": ["AI 생성 음성", "공식 재난예보를 대체하지 않습니다"],
    }
    missing_segment_phrases = {
        segment_id: [phrase for phrase in phrases if phrase not in by_id.get(segment_id, "")]
        for segment_id, phrases in segment_requirements.items()
        if any(phrase not in by_id.get(segment_id, "") for phrase in phrases)
    }
    passed = (
        ids == EXPECTED_IDS
        and not missing
        and not forbidden
        and not missing_numbers
        and not overlong
        and not missing_action_keywords
        and not missing_segment_phrases
        and state["input_data"]["forecast"]["is_live"] is False
    )
    return {
        "passed": passed,
        "mode": "deterministic_rule_review_after_llm",
        "segment_order_valid": ids == EXPECTED_IDS,
        "missing_required_phrases": missing,
        "forbidden_phrases_found": forbidden,
        "missing_source_numbers": missing_numbers,
        "overlong_narrations": overlong,
        "missing_before_rain_keywords": missing_action_keywords,
        "missing_segment_phrases": missing_segment_phrases,
        "locked_narration_segments": ["intro", "forecast", "digital_twin", "during_rain", "closing"],
        "official_sources": policy["official_sources"],
        "live_forecast_claimed": False,
    }


def script_agent(state: GuidanceState) -> Dict[str, Any]:
    fallback = rule_segments(state)
    requested_model = os.getenv("OPENAI_TEXT_MODEL", "gpt-4o-mini")
    meta: Dict[str, Any] = {
        "provider": "rule_fallback",
        "model_requested": requested_model,
        "model_actual": None,
        "store": False,
        "pii_sent": False,
        "fallback_used": True,
        "locked_narration_segments": ["intro", "forecast", "digital_twin", "during_rain", "closing"],
    }
    try:
        if not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY가 설정되지 않았습니다.")
        client = OpenAI(timeout=45.0, max_retries=2)
        response = client.responses.create(
            model=requested_model,
            instructions=(
                "당신은 고령 농업인을 위한 호우 사전안내 대본 생성 에이전트입니다. "
                "입력 JSON의 사실, 수치, 허용 행동만 사용하고 새로운 사실이나 행동을 만들지 마십시오. "
                "정확한 수신자 정보는 제공되지 않으므로 intro에서만 [수신자]를 사용하십시오. "
                "segments는 intro, forecast, digital_twin, before_rain, during_rain, closing 순서로 정확히 6개를 작성하십시오. "
                "고령자가 한 번에 이해할 수 있는 짧고 침착한 한국어를 사용하십시오. "
                "모든 required_phrases를 글자 그대로 포함하고 forbidden_phrases는 사용하지 마십시오. "
                "시연용 휴리스틱과 공식 예보의 차이를 분명히 하고 각 narration 글자 수 제한을 지키십시오."
            ),
            input=json.dumps(anonymized_payload(state), ensure_ascii=False),
            text={"format": {"type": "json_schema", "name": "flood_guidance_script", "schema": SCRIPT_SCHEMA, "strict": True}},
            max_output_tokens=1800,
            store=False,
        )
        parsed = json.loads(response.output_text)
        segments = merge_generated(parsed["segments"], fallback, state["input_data"]["recipient_label"])
        precheck = review_segments(segments, state)
        if not precheck["passed"]:
            raise RuntimeError(f"LLM 대본 안전 사전검증 실패: {json.dumps(precheck, ensure_ascii=False)}")
        usage = response.usage
        meta = {
            "provider": "openai",
            "model_requested": requested_model,
            "model_actual": response.model,
            "store": False,
            "pii_sent": False,
            "fallback_used": False,
            "locked_narration_segments": ["intro", "forecast", "digital_twin", "during_rain", "closing"],
            "usage": {
                "input_tokens": getattr(usage, "input_tokens", None),
                "output_tokens": getattr(usage, "output_tokens", None),
                "total_tokens": getattr(usage, "total_tokens", None),
            },
            "safety_precheck": precheck,
        }
    except Exception as exc:
        segments = fallback
        meta["fallback_reason"] = safe_error(exc)
    return {
        "segments": segments,
        "generation_meta": meta,
        "trace": traced(state, "script_agent", {"segment_count": len(segments), "provider": meta["provider"], "fallback_used": meta["fallback_used"]}),
    }


def safety_agent(state: GuidanceState) -> Dict[str, Any]:
    review = review_segments(state["segments"], state)
    if not review["passed"]:
        raise RuntimeError(f"안전성 검토 실패: {json.dumps(review, ensure_ascii=False)}")
    return {"safety_review": review, "trace": traced(state, "safety_agent", {"passed": True})}


def audio_duration(path: Path) -> float:
    result = subprocess.run(["/usr/bin/afinfo", str(path)], check=True, capture_output=True, text=True)
    match = re.search(r"estimated duration:\s*([0-9.]+) sec", result.stdout)
    if not match:
        raise RuntimeError(f"TTS 길이를 읽을 수 없습니다: {path}")
    return float(match.group(1))


def tts_agent(state: GuidanceState) -> Dict[str, Any]:
    AUDIO.mkdir(parents=True, exist_ok=True)
    local_voice = state["input_data"]["voice"]
    requested_model = os.getenv("OPENAI_TTS_MODEL", "gpt-4o-mini-tts")
    requested_voice = os.getenv("OPENAI_TTS_VOICE", "alloy")
    speed = float(os.getenv("OPENAI_TTS_SPEED", "1.1"))
    if not 0.25 <= speed <= 4.0:
        raise ValueError(f"OPENAI_TTS_SPEED 범위 오류: {speed}")
    client = OpenAI(timeout=90.0, max_retries=2) if os.getenv("OPENAI_API_KEY") else None
    assets: Dict[str, Dict[str, Any]] = {}
    provider_counts = {"openai": 0, "macos_say": 0}
    fallback_reasons: Dict[str, str] = {}
    for index, segment in enumerate(state["segments"], start=1):
        stem = f"{index:02d}_{segment['id']}"
        provider = "openai"
        try:
            if client is None:
                raise RuntimeError("OPENAI_API_KEY가 설정되지 않았습니다.")
            path = AUDIO / f"{stem}.mp3"
            path.unlink(missing_ok=True)
            speech = client.audio.speech.create(
                model=requested_model,
                voice=requested_voice,
                input=segment["narration"],
                instructions="고령 농업인이 듣기 쉽게 침착하고 또렷한 한국어로 읽으세요. 숫자와 시간을 천천히 읽고 과장하거나 긴박하게 연기하지 마세요.",
                response_format="mp3",
                speed=speed,
                timeout=90.0,
            )
            speech.write_to_file(path)
        except Exception as exc:
            provider = "macos_say"
            fallback_reasons[segment["id"]] = safe_error(exc)
            path = AUDIO / f"{stem}.aiff"
            path.unlink(missing_ok=True)
            subprocess.run(
                ["/usr/bin/say", "-v", local_voice["name"], "-r", str(local_voice["rate"]), "-o", str(path), segment["narration"]],
                check=True,
            )
        duration = audio_duration(path)
        if duration <= 0.5 or path.stat().st_size <= 1024:
            raise RuntimeError(f"TTS 생성 실패: {path}")
        provider_counts[provider] += 1
        assets[segment["id"]] = {
            "path": str(path),
            "duration_seconds": round(duration, 3),
            "bytes": path.stat().st_size,
            "provider": provider,
            "model": requested_model if provider == "openai" else "macos_say",
            "voice": requested_voice if provider == "openai" else local_voice["name"],
        }
    tts_meta = {
        "model_requested": requested_model,
        "voice_requested": requested_voice,
        "speed": speed,
        "provider_counts": provider_counts,
        "fallback_used": provider_counts["macos_say"] > 0,
        "fallback_reasons": fallback_reasons,
        "ai_voice_disclosure": "AI 생성 음성을 사용했습니다.",
    }
    return {
        "tts_assets": assets,
        "tts_meta": tts_meta,
        "trace": traced(state, "tts_agent", {"audio_count": len(assets), "provider_counts": provider_counts}),
    }


def manifest_agent(state: GuidanceState) -> Dict[str, Any]:
    result = base.manifest_agent(state)
    manifest = result["manifest"]
    manifest["schema_version"] = "2.0"
    manifest["generation_meta"] = state["generation_meta"]
    manifest["tts_meta"] = state["tts_meta"]
    manifest["ai_voice_disclosure"] = "AI 생성 음성을 사용했습니다."
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"manifest": manifest, "trace": traced(state, "manifest_agent", {"path": str(MANIFEST_PATH), "schema_version": "2.0"})}


def final_report_agent(state: GuidanceState) -> Dict[str, Any]:
    final_state = {
        "status": "ok",
        "run_id": state["run_id"],
        "trace": state["trace"],
        "safety_review": state["safety_review"],
        "generation_meta": state["generation_meta"],
        "tts_meta": state["tts_meta"],
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
        ("context_agent", base.context_agent),
        ("script_agent", script_agent),
        ("safety_agent", safety_agent),
        ("visual_asset_agent", base.visual_asset_agent),
        ("tts_agent", tts_agent),
        ("timeline_agent", base.timeline_agent),
        ("subtitle_agent", base.subtitle_agent),
        ("manifest_agent", manifest_agent),
        ("composition_agent", base.composition_agent),
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
    load_dotenv(ROOT / ".env")
    OUT.mkdir(parents=True, exist_ok=True)
    graph = build_graph()
    GRAPH_PATH.write_text(graph.get_graph().draw_mermaid(), encoding="utf-8")
    result = graph.invoke({"run_id": "GANGNAE-GUIDANCE-V8", "trace": []})
    print(json.dumps({
        "status": "ok",
        "final_video": result["final_video"],
        "duration_seconds": result["manifest"]["duration_seconds"],
        "safety_passed": result["safety_review"]["passed"],
        "script_provider": result["generation_meta"]["provider"],
        "tts_provider_counts": result["tts_meta"]["provider_counts"],
        "trace_nodes": [item["node"] for item in result["trace"]],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
