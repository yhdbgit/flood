#!/usr/bin/env python3
"""Pure V18 policy helpers shared by Blender and unit tests."""

from __future__ import annotations


class V18ScenePolicyError(RuntimeError):
    """Raised when a guidance context is unsafe to present as a V18 scene."""


def require_renderable_context(context: dict) -> None:
    if context.get("schema_version") != "1.0":
        raise V18ScenePolicyError("Unsupported guidance context schema")
    if context.get("status") != "ready":
        raise V18ScenePolicyError("Guidance context is not ready")
    if not context.get("trigger", {}).get("should_generate_video"):
        raise V18ScenePolicyError("Trigger did not authorize video generation")
    inundation = context.get("inundation", {})
    if inundation.get("condition_role") != "official_hazard_overlap_proxy":
        raise V18ScenePolicyError("Unsupported inundation condition role")
    if inundation.get("hydraulic_event_forecast") is not False:
        raise V18ScenePolicyError("V18 must not claim a hydraulic event forecast")


def source_label(context: dict) -> str:
    mode = context.get("forecast", {}).get("source", {}).get("mode")
    return "개발용 기상청 형식 예보" if mode == "fixture" else "기상청 단기예보"


def build_preview_specs(context: dict) -> list[dict]:
    require_renderable_context(context)
    rain = float(context["trigger"]["rain_condition"]["value_mm"])
    affected = float(context["inundation"]["field_affected_percent"])
    target_date = context["trigger"].get("target_date") or context["forecast"].get("target_date")
    common = {
        "title": f"{target_date} 호우 대비 안내",
        "forecast_line": f"{source_label(context)} · 24시간 예상 강수 {rain:.0f} mm",
    }
    return [
        {
            "code": "01_normal_overview",
            "stage": "normal",
            "camera": "Camera_Osong_Context_V14_Overview",
            **common,
            "reference_line": "범람 전 등록 농경지와 미호강 주변",
            "impact_line": "비가 오기 전에 농경지 안전조치를 준비하십시오",
        },
        {
            "code": "02_hazard_overview",
            "stage": "maximum",
            "camera": "Camera_Osong_Context_V14_Overview",
            **common,
            "reference_line": "환경부 100년 빈도 홍수위험범위 참고",
            "impact_line": f"등록 농경지 위험범위 중첩 {affected:.1f}%",
        },
        {
            "code": "03_field_close",
            "stage": "maximum",
            "camera": "Camera_Osong_Context_V14_Field",
            **common,
            "reference_line": "환경부 100년 빈도 홍수위험범위 참고",
            "impact_line": f"등록 농경지 위험범위 중첩 {affected:.1f}% · 비 시작 후 접근 금지",
        },
    ]


def scene_summary(context: dict) -> dict:
    specs = build_preview_specs(context)
    return {
        "context_id": context["context_id"],
        "source_mode": context["forecast"]["source"].get("mode"),
        "target_date": context["trigger"].get("target_date"),
        "rain_24h_mm": float(context["trigger"]["rain_condition"]["value_mm"]),
        "field_affected_percent": float(context["inundation"]["field_affected_percent"]),
        "visual_reference_stage": "maximum",
        "visual_reference_claim": "official_100_year_hazard_extent_reference",
        "hydraulic_event_forecast": False,
        "previews": specs,
    }
