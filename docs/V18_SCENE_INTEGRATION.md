# V18 디지털트윈 장면 통합

## 목적

V18 기상청 트리거가 생성한 `guidance_context_v18.json`을 V16 공식 홍수위험지도 기반 Blender 장면에 연결한다. 이 단계는 예보와 공식 위험범위를 함께 설명하는 정지 이미지 3장을 만들며 MP4는 렌더링하지 않는다.

## 데이터 해석 원칙

- 기상청 24시간 강수예보는 영상 생성 여부를 결정하는 사전 트리거다.
- 환경부 100년 빈도 홍수위험범위는 등록 농경지의 구조적 취약성을 보여주는 참고 범위다.
- 80 mm 예보로 100년 빈도 범위가 그대로 발생한다고 주장하지 않는다.
- V18은 강우 조건별 수리·수문 침수예측이 아니며 `hydraulic_event_forecast=false`를 유지한다.
- 한강홍수통제소 수위는 현재 상태 확인용이며 전날 트리거에는 사용하지 않는다.

## 입력과 장면 계약

입력 파일:

- `data/runtime/guidance_context_v18.json`
- `blender/osong_inundation_v16.blend`

장면 정책:

1. `status=ready`이고 `trigger.should_generate_video=true`인 컨텍스트만 허용한다.
2. 평상시 전체 화면은 V16 침수 객체를 모두 숨긴다.
3. 위험범위 화면은 `maximum` 객체를 표시하되 화면에 `환경부 100년 빈도 홍수위험범위 참고`를 명시한다.
4. 농경지 근접 화면은 별도 카메라와 42 mm 렌즈로 대상 필지를 넓게 보여준다.
5. 안내문은 Blender 3D 조명에 포함하지 않고 후속 합성 계층에서 화면 고정 패널로 추가한다.

## 생성 순서

개발용 80 mm fixture 컨텍스트:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/run_kma_trigger_v18.py \
  --fixture tests/fixtures/kma_vilage_fcst_80mm.json \
  --base-date 20260825 \
  --base-time 0500 \
  --now 2026-08-25T06:00:00+09:00
```

Blender 장면과 원본 프레임:

```bash
/Applications/Blender.app/Contents/MacOS/Blender \
  --background blender/osong_inundation_v16.blend \
  --python blender/apply_guidance_context_v18.py
```

안내문 합성과 자동 검증:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/compose_v18_previews.py
PYTHONDONTWRITEBYTECODE=1 python3 scripts/validate_v18_previews.py
```

실제 운영에서는 fixture 인자를 제거하고 `.env`의 `KMA_SERVICE_KEY`를 사용한다. `--record-trigger`는 후속 영상 작업이 실제로 접수된 뒤에만 사용한다.

## 산출물

- 재사용 장면: `blender/osong_guidance_v18.blend`
- 평상시 전체: `output/guidance_v18_preview/01_normal_overview.png`
- 공식 위험범위 전체: `output/guidance_v18_preview/02_hazard_overview.png`
- 농경지 근접: `output/guidance_v18_preview/03_field_close.png`
- 원본 Blender 프레임: `output/guidance_v18_preview/raw/`
- 장면·검증 보고서: `output/guidance_v18_preview/scene_report.json`

보고서가 `validated_ready_for_workflow_integration`이고 `visual_review=automated_pass`일 때 다음 워크플로 연결이 가능하다.

## 다음 LangGraph 연결 경계

다음 단계는 준비된 V18 컨텍스트를 기존 4개 에이전트 구조에 전달하는 것이다.

```text
START
  -> 대본 생성 Agent (guidance_context_v18.json)
  -> TTS 생성 Agent (구간별 비동기 병렬)
  -> 영상 제작 Agent (V18 장면 또는 재사용 렌더)
  -> 합성 Agent (TTS·자막·정보 패널)
  -> END
```

장면 통합 단계는 대본을 생성하거나 TTS를 호출하지 않는다. 영상 제작 Agent는 `context_id`, 예보 기준시각, 출처 모드, 공식 위험범위 참조 여부를 캐시 키에 포함해야 fixture·과거 예보·실제 예보가 섞이지 않는다.
