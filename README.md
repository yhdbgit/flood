# 충북 농업인 홍수피해 예방 디지털트윈 영상 제작 MVP

## 1. 프로젝트 개요

이 프로젝트는 충북 농업인의 홍수 피해 예방을 위해 다음 정보를 하나의 맞춤형 안내 영상으로 제작하는 MVP이다.

- 특정 농경지의 위치와 형상
- 예측 강수량과 강우 시작 시각
- 실제 지형과 하천 위치
- 단계별 예상 침수 범위
- 등록 농경지의 예상 영향 범위
- 비가 오기 전 준비 행동과 비가 시작된 뒤의 안전 행동

현재 구현된 최종 버전은 **V9**이며, 강내면 파일럿 지역을 대상으로 60초 길이의 MP4 영상을 자동 생성한다.

최종 산출물:

- `output/guidance_v9/gangnae_guidance_v9_60s.mp4`: 60초 최종 안내 영상
- `blender/gangnae_story_v9_base.blend`: 지형·하천·농경지·침수·카메라가 포함된 3D 장면
- `blender/gangnae_guidance_v9.blend`: 영상·안내 이미지·TTS를 조합하는 Blender VSE 편집 파일
- `output/guidance_v9/guidance_manifest.json`: 영상 구간과 에셋 배치 정보
- `output/guidance_v9/workflow_final_state.json`: LangGraph 실행 결과
- `output/guidance_v9/saved_blend_validation.json`: 최종 영상 검증 결과

## 2. 현재 구현 범위

현재는 **입력 데이터가 준비된 이후 디지털트윈 안내 영상을 자동 제작하는 구간**까지 구현되어 있다.

```text
예보·필지·침수 결과 JSON
        ↓
LangGraph 워크플로
        ↓
대본 구성 및 안전성 검사
        ↓
Blender 3D 디지털트윈 렌더링
        ↓
OpenAI TTS 음성 생성
        ↓
안내 이미지·영상·음성 타임라인 생성
        ↓
Blender VSE 최종 합성
        ↓
60초 H.264/AAC MP4
```

아직 자동화되지 않은 범위는 다음과 같다.

- 기상청 단기예보 API를 이용한 실제 24시간 예측 강수량 수집
- 80mm 강우조건과 필지조건을 결합한 자동 트리거
- 사용자가 등록한 실제 지적 필지 연동
- 수리·수문 모형 기반 침수심 및 범람 범위 계산
- 트리거 발생 후 영상 제작 워크플로 자동 실행
- 앱, 보호자, 농업인에게 영상 자동 발송

## 3. 개발 단계

| 버전 | 구현 내용 |
|---|---|
| V1 | SRTM DEM을 이용한 강내면 실제 지형 생성 |
| V2 | 하천·소하천·수위 관측소의 초기 3D 표현 |
| V3 | 원통형 하천을 제거하고 지형에 붙는 면 형태로 개선 |
| V4 | 등록 농경지 폴리곤과 농경지 확대 카메라 구현 |
| V5 | 관심·경계·심각 단계별 침수 메시 및 농경지 영향률 계산 |
| V6 | 5초 길이의 디지털트윈 범람 애니메이션 MP4 생성 |
| V7 | LangGraph, 로컬 TTS, 안내 슬라이드, Blender 영상 합성 |
| V8 | `gpt-4o-mini` 대본 생성과 `gpt-4o-mini-tts` 음성 생성 |
| V9 | 60초 영상, 범람 반복, 농경지 확대, 마지막 정지 화면, OpenAI TTS 적용 |

## 4. 주요 기술과 사용 범위

| 기술 | 사용 여부 | 현재 역할 |
|---|---|---|
| Blender Python API (`bpy`) | 사용 | 지형·하천·침수·카메라 애니메이션 및 MP4 렌더링 |
| Blender Video Sequence Editor | 사용 | 기본 영상, 안내 이미지, TTS 음성 최종 합성 |
| LangGraph | 사용 | 역할별 에이전트의 실행 순서와 상태 전달 |
| 멀티에이전트 구조 | 역할 분리형으로 사용 | 입력·대본·검증·시각자료·TTS·렌더·합성 담당 분리 |
| LangChain | 미사용 | 현재 코드에 LangChain Chain 또는 Runnable 구조 없음 |
| OpenAI `gpt-4o-mini-tts` | 사용 | 한국어 안내 음성 생성 |
| OpenAI `gpt-4o-mini` | V8에서만 사용 | 구조화된 대본 생성 실험 |
| Pillow | 사용 | 투명 안내 오버레이와 마지막 정보 화면 생성 |
| VWorld 하천 데이터 | 사용 | 국가하천·소하천 관리구역 위치 표현 |
| 한강홍수통제소 OpenAPI | 일부 연동 | 수위·유량·위험 기준·추세를 스냅샷으로 저장 |

현재 V9은 여러 LLM이 서로 토론하는 자율형 멀티에이전트가 아니다. 역할별 Python 함수를 에이전트 노드로 구분하고 LangGraph가 이를 직렬 실행하는 **에이전트형 제작 워크플로**이다.

## 5. 디렉터리 구조

```text
flood/
├── agents/
│   ├── guidance_v7_workflow.py
│   ├── guidance_v8_workflow.py
│   └── guidance_v9_workflow.py
├── blender/
│   ├── build_gangnae_terrain.py
│   ├── build_gangnae_hydro_v2.py
│   ├── build_gangnae_hydro_v3.py
│   ├── build_gangnae_farmland_v4.py
│   ├── build_gangnae_inundation_v5.py
│   ├── build_gangnae_video_v6.py
│   ├── build_gangnae_story_v9.py
│   ├── compose_guidance_video_v9.py
│   └── validate_guidance_video_v9.py
├── config/
│   ├── guidance_demo_input.json
│   ├── hydro_stations.json
│   ├── mvp_farmland.json
│   └── mvp_inundation_scenarios.json
├── data/
│   ├── terrain/N36E127.hgt
│   ├── source/hydro/UJ201/
│   ├── source/hydro/UJ301/
│   ├── processed/gangnae_hydro_geometry.json
│   └── runtime/hydro_snapshot.json
├── scripts/
│   ├── prepare_gangnae_hydro.py
│   └── fetch_hrfco_data.py
└── output/
    ├── inundation_v5_field_result.json
    └── guidance_v9/
```

## 6. 공간 데이터 구성

### 6.1 지형

`data/terrain/N36E127.hgt` SRTM DEM을 사용한다.

`blender/build_gangnae_terrain.py`는 다음 작업을 수행한다.

1. DEM에서 파일럿 범위를 추출한다.
2. WGS84 위도·경도를 장면 중심 기준 로컬 미터 좌표로 변환한다.
3. 165×115 격자의 3D 지형 메시를 생성한다.
4. DEM 고도를 Z축 높이에 적용한다.
5. 지형 가독성을 위해 고도 차이를 2배 강조한다.
6. 카메라, 태양광, 재질과 렌더 설정을 구성한다.

현재 지형 범위는 약 4.9km × 3.4km이며 DEM 고도는 약 7~145m이다.

### 6.2 하천

하천 데이터는 다음 자료를 결합한다.

- VWorld UJ201 국가하천·하천구역 폴리곤
- VWorld UJ301 소하천구역 폴리곤
- OpenStreetMap 미호강·태성천 중심선

`scripts/prepare_gangnae_hydro.py`는 VWorld 원본 좌표계 EPSG:5174를 WGS84로 변환하고, 다시 Blender 로컬 미터 좌표로 변환한다. 처리 결과는 `data/processed/gangnae_hydro_geometry.json`에 저장된다.

각 데이터의 의미는 다르다.

- VWorld 폴리곤: 하천의 법적·관리 구역
- OSM 중심선 리본: 화면에서 실제 수면처럼 보이도록 만든 시각적 하천
- UJ201/UJ301 폴리곤 자체는 실제로 물이 차 있는 수면 경계가 아님

### 6.3 등록 농경지

현재 MVP 필지는 `config/mvp_farmland.json`에 저장되어 있다.

- 필지 ID: `GANGNAE-DEMO-001`
- 면적: 약 7,640㎡
- 미호강 중심선과 거리: 약 450.68m
- DEM 고도: 약 27m

현재 필지는 OSM 농경지 영역 내부에서 작성한 데모 후보 필지이며 지적도 기반 확정 필지는 아니다.

### 6.4 한강홍수통제소 수위 정보

`scripts/fetch_hrfco_data.py`는 한강홍수통제소 OpenAPI에서 다음 정보를 수집한다.

- 관측소 명칭과 위치
- 10분 단위 수위
- 유량
- 관심·주의·경보·심각 기준 수위
- 최근 수위 상승·하강 추세
- 홍수예보 발표 여부

결과는 `data/runtime/hydro_snapshot.json`에 저장된다. API 키는 `.env`에서 읽으며 JSON 또는 Blender 파일에 기록하지 않는다.

현재 V9에서 수위 정보는 장면과 판단의 참고 정보로 보존되지만, 이 수위로 침수 폴리곤을 직접 계산하지는 않는다.

## 7. 현재 침수 범위 계산

V5의 침수 범위는 물리 유체 해석이나 2차원 수리 모형이 아니라 DEM과 하천 거리를 이용한 MVP 휴리스틱이다.

각 지형 격자에 다음 조건을 적용한다.

```text
미호강 중심선까지의 거리 ≤ 단계별 최대 거리
그리고
DEM 고도 ≤ 단계별 최대 고도
```

| 단계 | 최대 하천 거리 | 최대 DEM 고도 | 현재 필지 영향률 |
|---|---:|---:|---:|
| 관심 | 220m | 25m | 0% |
| 경계 | 470m | 29m | 62.5% |
| 심각 | 650m | 33m | 100% |

결과는 `output/inundation_v5_field_result.json`에 저장된다. Blender 장면에는 다음 세 침수 메시가 미리 생성되어 있다.

```text
Inundation_attention
Inundation_warning
Inundation_serious
```

영상에서는 이 세 메시의 표시 여부를 프레임별로 전환하여 물이 점차 확산되는 모습을 표현한다.

## 8. V9 LangGraph 워크플로

워크플로 진입점은 `agents/guidance_v9_workflow.py`이다.

```text
START
  → context_agent
  → script_agent
  → safety_agent
  → visual_asset_agent
  → base_render_agent
  → tts_agent
  → manifest_agent
  → composition_agent
  → final_report_agent
  → END
```

### 8.1 공용 상태

각 에이전트는 `StoryState`를 통해 결과를 전달한다.

```text
run_id
input_data
field_result
segments
safety_review
visual_assets
tts_assets
tts_meta
manifest
final_video
trace
```

### 8.2 에이전트 역할

#### `context_agent`

- `config/guidance_demo_input.json` 로드
- `output/inundation_v5_field_result.json` 로드
- V5 Blender 장면과 V9 스크립트 존재 여부 검사
- 필지 계산 결과가 정상인지 검사

#### `script_agent`

- 60초 영상을 7개 구간으로 분할
- 구간별 제목, 부제목, TTS 대본, 시작·종료 프레임 설정
- 현재 V9에서는 LLM이 아니라 검증된 고정 대본 사용
- 실행 이력에는 `editorial_locked`로 기록

V8에서는 `gpt-4o-mini` Responses API와 JSON Schema를 이용해 대본을 생성했지만, V9에서는 영상 길이와 행동요령을 일정하게 유지하기 위해 대본을 고정했다.

#### `safety_agent`

다음 항목을 자동 검사한다.

- 예측 강수량 80mm 포함
- 농경지 영향률 62.5%, 100% 포함
- 배수로, 농기계, 비닐하우스 행동 포함
- 논둑이나 물꼬 접근 금지 포함
- 긴급상황 119 안내 포함
- 금지 문구 미포함
- 1~1440 프레임의 연속성
- 첫 프레임부터 TTS가 시작되는지 확인

#### `visual_asset_agent`

Pillow를 이용해 960×540 크기의 다음 이미지를 생성한다.

- 디지털트윈 위에 표시할 투명 오버레이 6장
- 마지막 행동요령 정보 화면 1장

#### `base_render_agent`

Blender를 백그라운드 모드로 실행한다.

```text
/Applications/Blender.app/Contents/MacOS/Blender \
  --background blender/gangnae_inundation_v5.blend \
  --python blender/build_gangnae_story_v9.py
```

정상적인 52초 기본 영상과 렌더 보고서가 이미 있으면 캐시를 재사용한다.

#### `tts_agent`

- `.env`에서 OpenAI API 설정 로드
- 7개 구간의 음성을 각각 MP3로 생성
- 생성된 음성 길이를 `afinfo`로 측정
- 음성이 구간보다 길면 재생 속도를 높여 다시 생성
- OpenAI 호출 실패 시 macOS `say`로 대체

현재 최종 V9 실행 결과는 OpenAI TTS 7개, 로컬 대체 음성 0개이다.

#### `manifest_agent`

- 영상 구간별 프레임·이미지·음성 경로 통합
- `guidance_manifest.json` 생성
- `narration_script.txt` 생성
- `guidance_subtitles.srt` 생성

#### `composition_agent`

두 번째 Blender 프로세스를 실행해 기본 영상, 오버레이, TTS를 합성한다.

#### `final_report_agent`

영상 경로, 파일 크기, TTS 제공자, 안전성 검사와 실행 이력을 `workflow_final_state.json`에 저장한다.

## 9. 60초 영상 타임라인

최종 영상은 24fps, 총 1,440프레임이다.

| 시간 | 프레임 | 장면 |
|---|---:|---|
| 0~10초 | 1~240 | 전체 화면에서 1차 범람 |
| 10~14초 | 241~336 | 범람 이전으로 초기화한 뒤 농경지 확대 |
| 14~24초 | 337~576 | 확대된 농경지에서 1차 범람 |
| 24~34초 | 577~816 | 전체 화면으로 초기화한 뒤 2차 범람 |
| 34~38초 | 817~912 | 다시 초기화한 뒤 농경지 확대 |
| 38~48초 | 913~1152 | 확대된 농경지에서 2차 범람 |
| 48~52초 | 1153~1248 | 심각 단계 침수 화면 정지 |
| 52~60초 | 1249~1440 | 최종 행동요령 화면 |

TTS는 1프레임부터 시작하며 각 구간 시작 프레임에 맞춰 새 음성이 배치된다.

## 10. Blender 3D 영상 제작 방식

### 10.1 장면 초기화

`blender/build_gangnae_story_v9.py`는 `gangnae_inundation_v5.blend`에서 다음 요소를 가져온다.

- DEM 지형
- 하천과 소하천
- 등록 농경지
- 관심·경계·심각 침수 메시
- 농경지 재질
- 기본 카메라

### 10.2 카메라 애니메이션

기존 카메라의 다음 시점을 샘플링한다.

- 전체 시점: 기존 1프레임
- 중간 시점: 기존 65프레임
- 농경지 확대 시점: 기존 120프레임

기존 애니메이션을 지우고 V9 타임라인에 맞춰 전체 → 중간 → 확대 카메라 키프레임을 다시 삽입한다.

### 10.3 범람 애니메이션

각 10초 범람 구간은 대략 다음 상태로 진행된다.

```text
정상
  → 관심 침수 메시 표시
  → 경계 침수 메시 표시
  → 심각 침수 메시 표시
  → 심각 상태 유지
```

동시에 농경지 재질도 녹색 → 주황색 → 빨간색으로 바뀐다.

V6의 5초 범람을 V9에서 10초로 늘렸으므로 현재 재생 속도 계수는 `0.5`이다.

### 10.4 기본 영상 렌더링

Blender는 다음 설정으로 3D 기본 영상을 생성한다.

- 프레임: 1~1248
- FPS: 24
- 길이: 52초
- 해상도: 960×540
- 포맷: MPEG-4
- 코덱: H.264
- 출력: `output/guidance_v9/gangnae_story_v9_base.mp4`

렌더 직전 `scene.frame_set(1)`을 호출하고 `bpy.ops.render.render(animation=True)`로 전체 프레임을 렌더링한다.

이 과정은 Blender 화면을 녹화하는 것이 아니다. 활성 카메라를 기준으로 각 프레임을 렌더링하고 FFmpeg가 프레임을 MP4로 인코딩한다. 따라서 Blender GUI가 화면에 보이지 않아도 실행되며 마우스 커서나 UI가 영상에 포함되지 않는다.

## 11. OpenAI TTS

V9은 OpenAI `gpt-4o-mini-tts`를 사용한다.

- 모델: `OPENAI_TTS_MODEL`, 기본값 `gpt-4o-mini-tts`
- 음성: `OPENAI_TTS_VOICE`, 기본값 `alloy`
- 기본 속도: `OPENAI_TTS_SPEED_V9`, 기본값 `1.15`
- API: `/v1/audio/speech`

공식 모델 문서: <https://developers.openai.com/api/docs/models/gpt-4o-mini-tts>

`.env` 예시:

```dotenv
OPENAI_API_KEY=발급받은_API_키
OPENAI_TTS_MODEL=gpt-4o-mini-tts
OPENAI_TTS_VOICE=alloy
OPENAI_TTS_SPEED_V9=1.15
```

실제 `.env`는 Git에 포함하지 않으며 API 키를 README, JSON, Blender 파일 또는 로그에 기록하지 않는다.

## 12. 최종 영상 합성

`blender/compose_guidance_video_v9.py`는 새 Blender 장면과 Video Sequence Editor를 생성한다.

```text
채널 1: 52초 디지털트윈 기본 영상 1개
채널 2: 투명 안내 오버레이 6개 + 마지막 화면 1개
채널 4: TTS 음성 7개
```

최종 합성 설정:

- 프레임: 1~1440
- FPS: 24
- 길이: 60초
- 해상도: 960×540
- 영상 코덱: H.264
- 음성 코덱: AAC 192kbps
- 출력: `output/guidance_v9/gangnae_guidance_v9_60s.mp4`

전체 Blender 작업은 다음 두 단계로 분리된다.

```text
1차 Blender 렌더
3D 장면 → 52초 무음 디지털트윈 MP4

2차 Blender 렌더
디지털트윈 MP4 + 오버레이 이미지 + TTS
→ 60초 최종 안내 MP4
```

`gangnae_story_v9_base.blend`는 3D 장면을 검토할 때 사용하고, `gangnae_guidance_v9.blend`는 최종 영상 편집 타임라인을 검토할 때 사용한다.

## 13. 실행 방법

### 13.1 환경 조건

- macOS
- Blender 5.2 LTS 설치 경로: `/Applications/Blender.app`
- Python 가상환경: `/Users/hyeokjae/Desktop/ICTCB/.venv`
- 주요 Python 패키지: `langgraph`, `openai`, `python-dotenv`, `Pillow`
- 공간 데이터 전처리 패키지: `pyshp`, `shapely`, `pyproj`

### 13.2 최종 V9 워크플로 실행

```bash
cd /Users/hyeokjae/Desktop/ICTCB/flood
/Users/hyeokjae/Desktop/ICTCB/.venv/bin/python agents/guidance_v9_workflow.py
```

실행 시 정상적인 52초 기본 영상이 이미 존재하면 다시 3D 렌더링하지 않고 캐시를 재사용한다. 대본, 안내 이미지, TTS, 매니페스트와 최종 합성 영상은 V9 출력 폴더에 생성된다.

### 13.3 한강홍수통제소 데이터 갱신

```bash
cd /Users/hyeokjae/Desktop/ICTCB/flood
/Users/hyeokjae/Desktop/ICTCB/.venv/bin/python scripts/fetch_hrfco_data.py
```

이 명령은 `.env`의 `HRFCO_API_KEY`를 읽어 `data/runtime/hydro_snapshot.json`을 갱신한다.

## 14. 검증 결과

`blender/validate_guidance_video_v9.py`와 `output/guidance_v9/saved_blend_validation.json` 기준으로 다음 항목이 통과했다.

- 최종 장면 이름 정상
- MOVIE 스트립 1개
- IMAGE 스트립 7개
- SOUND 스트립 7개
- 1~1440 프레임
- 24fps, 정확히 60초
- H.264 영상 및 AAC 음성
- 최종 MP4 파일 정상 생성
- Blender 장면 내부 API 키 흔적 없음

## 15. 현재 MVP의 한계

현재 결과를 실제 운영 수준으로 해석하면 안 되는 부분은 다음과 같다.

1. `guidance_demo_input.json`의 80mm 강수량은 실시간 기상청 예보가 아닌 데모 입력이다.
2. 현재 농경지는 지적도 기반 확정 필지가 아니다.
3. 침수 범위는 수리 모형이 아니라 DEM 고도와 하천 거리 기반 휴리스틱이다.
4. 표시 침수심은 시각화를 위한 단계별 값이며 실제 계산 침수심이 아니다.
5. 한강홍수통제소 관측값은 현재 침수 폴리곤을 직접 생성하지 않는다.
6. VWorld UJ201/UJ301은 관리구역 데이터이며 실제 수면 경계와 동일하지 않다.
7. 영상 제작은 자동화됐지만 기상 트리거와 사용자 발송은 아직 연결되지 않았다.

## 16. 운영형 구조로 전환하기 위한 다음 단계

```text
기상청 단기예보 수집
        ↓
필지별 24시간 누적 강수량 판정
        ↓
필지별 침수심 또는 침수확률 계산
        ↓
발송 대상 필지 선별
        ↓
LangGraph V9 영상 제작 실행
        ↓
앱 알림·보호자 알림·영상 다운로드 제공
```

우선순위는 다음과 같다.

1. 기상청 단기예보 API와 80mm 트리거 연결
2. 실제 지적 필지 등록 및 공간 교차 판정
3. 홍수위험지도 또는 수리해석 결과를 V5 침수 메시로 변환
4. 예보·수위·필지 결과를 `guidance_demo_input.json` 대신 자동 주입
5. 영상 제작 작업 큐와 실패 재시도 구현
6. 농업인 및 보호자 앱 발송 기능 연결

