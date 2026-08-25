# V18 컨텍스트 기반 LangGraph 영상 제작

## 목적

`data/runtime/guidance_context_v18.json`을 영상 제작의 단일 입력으로 사용해 기상청 예보, 등록 농경지, 공식 홍수위험범위, 행동요령, 대피시설 정보를 같은 실행에 전달한다.

## 실행 경계

워크플로 앞의 게이트는 에이전트가 아니다. 다음 조건을 모두 만족할 때만 LangGraph에 진입한다.

- 컨텍스트 스키마 버전 `1.0`
- 컨텍스트 상태 `ready`
- `trigger.should_generate_video=true`
- 운영 모드에서는 `forecast.source.mode=live`
- `inundation.hydraulic_event_forecast=false`

현재 구현은 기상청 강수예보를 생성 트리거로 사용하고 환경부 홍수위험지도를 위험범위 참고자료로 사용한다. 특정 강우량에 대한 수리·수문 범람 예측으로 표현하지 않는다.

## LangGraph 구조

START와 END를 제외한 노드는 정확히 네 개다.

```text
START
  -> script_agent
  -> tts_agent
  -> video_production_agent
  -> composition_agent
  -> END
```

### 1. 대본 생성 Agent

V18 컨텍스트를 최소 60초의 5개 기본 구간으로 변환한다.

1. 기상청 24시간 예상 강수량
2. 환경부 공식 100년 빈도 홍수위험범위
3. 등록 농경지와 공식 위험범위의 중첩률
4. 비가 시작된 뒤 접근 금지 행동요령
5. 대피시설과 비 오기 전 이동 안내

### 2. TTS 생성 Agent

5개 구간을 OpenAI TTS로 비동기 병렬 생성한다. OpenAI 호출이 실패하면 macOS 한국어 음성으로 해당 구간만 대체한다. 계획 모드에서는 API를 호출하지 않는다. 실제 음성이 기본 구간보다 길면 1초의 여유를 포함해 해당 구간과 뒤 구간을 자동으로 밀어 최종 길이를 60~120초로 확장한다.

### 3. 영상 제작 Agent

같은 `context_id`와 `source_mode`로 검증된 정지 프리뷰가 있으면 재사용한다. 일치하지 않으면 운영 모드에서만 Blender를 백그라운드 실행해 V18 장면과 정지 프리뷰를 갱신한다. 행동요령과 대피시설 카드는 실행별로 생성한다.

현재 시각 방식은 `context_specific_stage_slideshow`다. 평상시 전체, 공식 위험범위 전체, 농경지 근접 정지 화면과 두 안내 카드를 사용한다. 이는 수리모형 기반 동적 범람 애니메이션이 아니다.

### 4. 합성 Agent

Blender Video Sequence Editor에서 5개 화면과 5개 음성을 60~120초 MP4로 합성한다. 각 음성에 맞춰 먼저 구간을 확장하고, 음성 스트립은 최종 배정 구간의 종료 프레임에서만 잘라 다음 음성과 겹치지 않도록 한다. 60초 초과는 오류가 아니며 전체 타임라인이 120초를 넘을 때만 제작을 중단한다.

## 실행 모드

### 실시간 운영

```bash
PYTHONDONTWRITEBYTECODE=1 python3 agents/guidance_v18_workflow.py --mode production
```

현재 실시간 예보가 기준을 넘지 않으면 다음과 같이 종료되며 TTS, Blender, MP4 작업은 실행하지 않는다.

```json
{
  "status": "skipped",
  "reason_codes": ["RAIN_BELOW_THRESHOLD", "VIDEO_TRIGGER_FALSE"],
  "trace_nodes": [],
  "final_video": null
}
```

### 스테이징 전체 제작

실시간 runtime과 쿨다운 기록을 변경하지 않고 80mm fixture로 TTS와 MP4 전체 경로를 검증한다. 위치 기반 대본은 OpenAI TTS로 전송되므로 승인된 개발 환경에서만 실행한다.

```bash
python3 scripts/prepare_v18_staging_context.py
PYTHONDONTWRITEBYTECODE=1 python3 agents/guidance_v18_workflow.py \
  --context data/staging/guidance_context_v18_80mm.json \
  --mode staging \
  --output-root output/guidance_v18_staging
```

최종 음성 검증은 Blender의 `aud` 디코더로 원본 TTS 길이와 최종 MP4의 구간별 음성 신호를 확인한다.

```bash
/Applications/Blender.app/Contents/MacOS/Blender --background \
  --python blender/validate_v18_staging_media.py -- \
  --run-dir output/guidance_v18_staging/<run-id>
```

상대경로로 인해 Blender가 TTS 파일을 잃지 않도록 합성기는 모든 자산을 프로젝트 기준 절대경로로 해석하고 `.blend` 저장 시 경로 재매핑을 금지한다.

### 구조 검증

```bash
python3 agents/guidance_v18_workflow.py \
  --context /path/to/ready_fixture_context.json \
  --mode plan \
  --output-root /private/tmp/flood-v18-plan
```

계획 모드는 준비된 fixture 컨텍스트를 허용하지만 TTS와 Blender를 호출하거나 MP4를 만들지 않는다. 스테이징 모드는 승인된 fixture의 전체 미디어 경로를 실행하며, 운영 모드는 fixture 입력을 거부한다.

## 주요 산출물

```text
output/guidance_v18/
├── last_gate_result.json
└── V18-<target-date>-<hash>/
    ├── langgraph_structure.mmd
    ├── narration_script.txt
    ├── guidance_subtitles.srt
    ├── guidance_manifest.json
    ├── workflow_final_state.json
    ├── audio/
    ├── visuals/
    ├── osong_guidance_v18_composition.blend
    └── osong_guidance_v18.mp4
```

`output/`은 재생성 가능한 실행 산출물이므로 Git에 포함하지 않는다.

## 자동 검증

`tests/test_guidance_v18_workflow.py`에서 다음을 확인한다.

- LangGraph의 에이전트 노드가 정확히 네 개인지
- 실시간 미발동 컨텍스트가 그래프 진입 전에 거절되는지
- fixture가 계획·스테이징 모드에서 허용되고 운영 모드에서는 거부되는지
- 5개 기본 구간이 1~1440 프레임을 빈틈없이 사용하고, 실제 TTS가 길면 최대 2880 프레임까지 연속 확장되는지
- 계획 모드가 네 에이전트를 모두 통과하면서 외부 미디어 호출을 하지 않는지
- 스테이징 검증에서 최종 길이가 매니페스트와 일치하고 60~120초 범위이며, 최종 MP4의 다섯 구간에 실제 음성이 존재하는지
