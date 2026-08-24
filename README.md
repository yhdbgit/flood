# 충북 농업인 홍수피해 예방 디지털트윈 영상 제작 MVP

## 1. 프로젝트 개요

이 프로젝트는 충북 농업인의 홍수 피해 예방을 위해 다음 정보를 하나의 맞춤형 안내 영상으로 제작하는 MVP이다.

- 특정 농경지의 위치와 형상
- 예측 강수량과 강우 시작 시각
- 실제 지형과 하천 위치
- 단계별 예상 침수 범위
- 등록 농경지의 예상 영향 범위
- 비가 오기 전 준비 행동과 비가 시작된 뒤의 안전 행동

현재 저장소 기준으로 **영상 자동 제작 워크플로는 V13**, **디지털트윈 장면은 V17**까지 구현됐다. V14는 3km × 3km 배경 영역, V15는 연속 하천 수면, V16은 환경부 홍수위험지도 기반 침수 단계, V17은 한강홍수통제소 실시간 수위 단계 연동을 담당한다.

버전 관리 정책:

- `output/`의 MP4·음성·정지 이미지·실행 리포트는 재생성 가능한 산출물이므로 Git에 포함하지 않는다.
- 재현에 필요한 Python 소스, 설정, 가공 공간 데이터와 `.blend` 장면은 버전 관리한다.
- V13 영상 워크플로 산출물은 실행 시 `output/guidance_v13/`에 다시 생성된다.
- V17 실시간 정지 화면과 실행 리포트는 `scripts/run_osong_realtime_v17.py` 실행 시 `output/realtime_v17/`에 다시 생성된다.

## 2. 현재 구현 범위

현재는 **입력 데이터가 준비된 이후 디지털트윈 안내 영상을 자동 제작하는 구간**까지 구현되어 있다.

```text
예보·필지·공식 침수 결과 JSON
        ↓
대본 생성 에이전트
        ↓
TTS 생성 에이전트: 구간별 음성 비동기 병렬 호출
        ↓
영상제작 에이전트: 오버레이·경로 지도·자막·매니페스트 생성
        ↓
합성 에이전트: 사전 렌더링 본편 + 이미지 + 음성 합성
        ↓
64초 MP4
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
| V10~V12 | 고품질 지형·오송 파일럿·공식 침수자료·대피 경로 반영 |
| V13 | 4개 LangGraph 에이전트, TTS 5건 비동기 병렬 생성, 사전 렌더링 본편 필수 재사용 |
| V14 | 기존 1km 정밀 영역을 유지하고 3km × 3km 배경 지형·위성영상·공간 데이터 준비 |
| V15 | OSM 수면 경계를 이용한 연속 하천 수면과 하천 아래 지형 마스킹 |
| V16 | 환경부 홍수위험지도 기반 평상시·중간·최대 침수 단계와 필지 영향 표시 |
| V17 | 한강홍수통제소 실시간 수위 위험도를 V16 시각 단계에 연결하고 오래된 데이터 차단 |

## 4. 주요 기술과 사용 범위

| 기술 | 사용 여부 | 현재 역할 |
|---|---|---|
| Blender Python API (`bpy`) | 사용 | 지형·하천·침수·카메라 애니메이션 및 MP4 렌더링 |
| Blender Video Sequence Editor | 사용 | 기본 영상, 안내 이미지, TTS 음성 최종 합성 |
| LangGraph | 사용 | 역할별 에이전트의 실행 순서와 상태 전달 |
| 멀티에이전트 구조 | 역할 분리형으로 사용 | 대본·병렬 TTS·영상제작·합성의 4개 노드 |
| LangChain | 미사용 | 현재 코드에 LangChain Chain 또는 Runnable 구조 없음 |
| OpenAI `gpt-4o-mini-tts` | 사용 | 한국어 안내 음성 생성 |
| OpenAI `gpt-4o-mini` | V8에서만 사용 | 구조화된 대본 생성 실험 |
| Pillow | 사용 | 투명 안내 오버레이와 마지막 정보 화면 생성 |
| VWorld 하천 데이터 | 사용 | 국가하천·소하천 관리구역 위치 표현 |
| 한강홍수통제소 OpenAPI | 일부 연동 | 수위·유량·위험 기준·추세를 스냅샷으로 저장 |

현재 V13은 여러 LLM이 토론하는 자율형 멀티에이전트가 아니다. 역할별 Python 함수를 4개 에이전트 노드로 구분하고 LangGraph가 상태를 전달하는 **에이전트형 제작 워크플로**이다. TTS 에이전트 내부의 5개 음성 요청만 `asyncio.gather`로 병렬 실행한다.

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
└── output/                 # 실행 시 생성되며 Git에서는 제외
    └── .gitkeep
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

## 7. 초기 V5 침수 범위 계산 이력

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

## 8. V13 LangGraph 워크플로

워크플로 진입점은 `agents/guidance_v13_workflow.py`이다. START와 END를 제외한 에이전트는 정확히 4개다.

```text
START
  → script_agent
  → tts_agent
  → video_production_agent
  → composition_agent
  → END
```

### 8.1 공용 상태

각 에이전트는 `StoryState`로 다음 핵심 결과를 전달한다.

```text
run_id
input_data
field_result
segments
visual_assets
tts_assets
tts_meta
manifest
final_video
trace
```

### 8.2 에이전트 역할

#### `script_agent`

- 안내 입력과 환경부 공식 침수 결과를 직접 로드한다.
- 64초 타임라인을 5개 구간으로 나눈다.
- 구간별 시작·종료 프레임, 제목, 부제목, 대본과 시각자료 종류를 생성한다.

#### `tts_agent`

- `AsyncOpenAI`를 사용한다.
- 5개 구간 음성을 `asyncio.gather`로 동시에 요청한다.
- 한 요청이 실패하면 해당 구간만 macOS `say`로 비동기 대체한다.
- 음성 길이 검사, 재생속도 재생성, 별도 TTS 검증 노드는 사용하지 않는다.

#### `video_production_agent`

- Pillow로 구간별 오버레이와 실제 대피 경로 지도를 만든다.
- TTS 경로와 시각자료 경로를 프레임 타임라인에 결합한다.
- `guidance_manifest.json`, `narration_script.txt`, `guidance_subtitles.srt`를 생성한다.
- 매니페스트는 영상 파일이 아니라 합성 에이전트가 읽는 **영상 제작 명세**다.

#### `composition_agent`

- `output/guidance_v13/osong_story_v13_base.mp4`가 이미 존재한다고 전제한다.
- 기본 본편을 새로 렌더링하거나 캐시 여부를 판정하는 에이전트는 없다.
- Blender VSE에서 사전 렌더링 본편, 오버레이, TTS를 합성해 최종 MP4를 만든다.
- 실행 결과와 에이전트별 소요 시간을 `workflow_final_state.json`에 기록한다.

## 9. 64초 영상 타임라인

최종 영상은 24fps, 총 1,536프레임이다.

| 시간 | 프레임 | 장면 |
|---|---:|---|
| 0~20초 | 1~480 | 전체 시점에서 공식 침수예상 범위 확산 |
| 20~24초 | 481~576 | 등록 농경지 확대 |
| 24~44초 | 577~1056 | 확대 시점에서 농경지 침수 영향 표시 |
| 44~47초 | 1057~1128 | 침수된 농경지 화면 정지와 접근 금지 안내 |
| 47~64초 | 1129~1536 | 실제 재해구호시설과 비 오기 전 이동 경로 안내 |

TTS는 첫 프레임부터 시작하고 각 구간 시작 프레임에 맞춰 배치된다.

## 10. Blender 3D 본편 정책

V13의 사전 렌더링 본편은 실행 시 `output/guidance_v13/osong_story_v13_base.mp4`에 생성된다. 이 파일은 저장소에는 포함하지 않는다. 지형, 하천, 등록 농경지, 공식 침수예상 범위, 카메라 이동과 범람 시퀀스가 이 파일에 포함된다.

- 원본 제작 스크립트: `blender/build_osong_story_v13.py`
- 해상도: 960×540
- FPS: 24
- 워크플로 정책: 본편 파일이 준비돼 있다고 가정하고 렌더링 노드를 실행하지 않음
- 최종 실행에서 수행하는 Blender 작업: VSE 합성만 수행

본편을 새로 만들 필요가 있을 때만 제작 스크립트를 별도로 실행한다. 일반적인 대본·음성 변경은 3D 본편을 다시 렌더링하지 않는다.

## 11. OpenAI TTS

V13은 OpenAI `gpt-4o-mini-tts`와 비동기 클라이언트를 사용한다.

- 모델: `OPENAI_TTS_MODEL`, 기본값 `gpt-4o-mini-tts`
- 음성: `OPENAI_TTS_VOICE`, 기본값 `alloy`
- 기본 속도: `OPENAI_TTS_SPEED_V13`, 기본값 `1.08`
- 생성 방식: 5개 구간을 `asyncio.gather`로 병렬 요청
- API: `/v1/audio/speech`
- 구간별 실패 대체: macOS `say`

`.env` 예시:

```dotenv
OPENAI_API_KEY=발급받은_API_키
OPENAI_TTS_MODEL=gpt-4o-mini-tts
OPENAI_TTS_VOICE=alloy
OPENAI_TTS_SPEED_V13=1.08
```

실제 `.env`는 Git에 포함하지 않으며 API 키를 README, JSON, Blender 파일 또는 로그에 기록하지 않는다.

## 12. 최종 영상 합성

`blender/compose_guidance_video_v13.py`는 `guidance_manifest.json`을 읽어 Blender VSE 타임라인을 구성한다.

```text
사전 렌더링 디지털트윈 본편 1개
+ 구간별 오버레이 또는 대피 경로 이미지 5개
+ 병렬 생성된 TTS 음성 5개
→ 64초 최종 안내 MP4
```

최종 출력은 실행 시 `output/guidance_v13/osong_guidance_v13_64s.mp4`에 생성된다. 이 단계는 3D 지형을 다시 렌더링하지 않고 기존 MP4에 이미지와 음성을 합성한다.

## 13. 실행 방법

### 13.1 환경 조건

- macOS
- Blender 5.2 LTS 설치 경로: `/Applications/Blender.app`
- Python 가상환경: `/Users/hyeokjae/Desktop/ICTCB/.venv`
- 주요 Python 패키지: `langgraph`, `openai`, `python-dotenv`, `Pillow`
- 공간 데이터 전처리 패키지: `pyshp`, `shapely`, `pyproj`

### 13.2 최종 V13 워크플로 실행

```bash
cd /Users/hyeokjae/Desktop/ICTCB/flood
PYTHONDONTWRITEBYTECODE=1 python3 agents/guidance_v13_workflow.py
```

실행 시 64초 사전 렌더링 본편이 이미 존재한다고 전제한다. 본편 렌더링 단계 없이 대본, 5개 병렬 TTS, 안내 이미지, 매니페스트와 최종 합성 영상만 V13 출력 폴더에 생성한다.

### 13.3 한강홍수통제소 데이터 갱신

```bash
cd /Users/hyeokjae/Desktop/ICTCB/flood
/Users/hyeokjae/Desktop/ICTCB/.venv/bin/python scripts/fetch_hrfco_data.py
```

이 명령은 `.env`의 `HRFCO_API_KEY`를 읽어 `data/runtime/hydro_snapshot.json`을 갱신한다.

## 14. 검증 결과

과거 V9 산출물 생성 당시 `blender/validate_guidance_video_v9.py` 검증에서 다음 항목이 통과했다. 산출물 JSON과 MP4 자체는 현재 Git에서 제외한다.

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
LangGraph V13 영상 제작 실행
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

