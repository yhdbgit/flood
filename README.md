# V23 농경지 맞춤형 홍수 안내 영상 제작기

팀 백엔드가 홍수 안내 발송을 결정한 뒤 전달한 이벤트를 받아, 등록 농경지에 맞는 약 80초 MP4를 생성하는 서비스다. V23은 트리거 기준을 다시 계산하지 않는다. `field_id`의 소유권과 입력 형식만 확인하고, 사전 렌더링된 디지털트윈 자산을 재사용해 대본, TTS, 개인화 영상, 최종 합성을 수행한다.

## 처리 구조

```text
팀 트리거 서비스
  -> V23 이벤트 검증 및 농경지 조회
  -> script_agent
  -> tts_agent (OpenAI TTS 병렬 호출)
  -> video_production_agent (캐시 영상만 조합)
  -> composition_agent (음성·정보화면 합성)
  -> 개인화 MP4
```

트리거 시 Blender 3D 장면을 다시 렌더링하지 않는다. 등록 농경지별 배경, 농경지 강조, 범람, 공용 대피소 영상을 GitHub Release에서 한 번 설치한 뒤 계속 재사용한다.

## 현재 지원 범위

- 농경지: `OSONG-FIELD-DEMO-001`, `002`, `003`
- 시나리오: `caution`
- 해상도: 1280x720
- 시각 구간: 60초
- 최종 안내 영상: 80초
- 대피소: 오송읍복지회관
- 트리거 판단: 팀 백엔드 소유

예제 농경지는 OSM 농업용지 폴리곤이며 실제 소유권 지적 필지가 아니다.

## 요구 환경

- Python 3.11 이상
- Blender 5.x
- OpenAI API 키와 `gpt-4o-mini-tts` 사용 권한
- V23 Runtime Asset Release 약 3.3GB

macOS와 Windows 모두 지원하도록 프로젝트·Blender·글꼴·출력 경로를 자동 탐색한다. 기본 경로가 아닌 경우 `.env`에서 지정할 수 있다.

## 설치

### Windows PowerShell

```powershell
git clone -b hyeokjae https://github.com/yhdbgit/flood.git
cd flood
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python scripts/setup_v23.py
python scripts/verify_v23_installation.py --decode-media
```

### macOS

```bash
git clone -b hyeokjae https://github.com/yhdbgit/flood.git
cd flood
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
python scripts/setup_v23.py
python scripts/verify_v23_installation.py --decode-media
```

`setup_v23.py`는 GitHub Release `v23-assets-1.0.0`의 ZIP 세 개를 내려받고 SHA-256을 확인한 뒤 `runtime_assets/v23`에 설치한다. 이미 검증된 자산이 있으면 재다운로드하지 않는다.

인터넷 없이 전달받은 ZIP을 설치할 수도 있다.

```bash
python scripts/setup_v23.py --archive-dir /path/to/v23-assets-1.0.0
```

## 환경변수

`.env.example`을 `.env`로 복사하고 API 키를 입력한다.

```env
OPENAI_API_KEY=...
OPENAI_TTS_MODEL=gpt-4o-mini-tts
OPENAI_TTS_VOICE=alloy
OPENAI_TTS_SPEED_V23=1.12
```

선택 설정:

```env
BLENDER_BIN=C:\Program Files\Blender Foundation\Blender 5.0\blender.exe
V23_ASSET_ROOT=D:\flood-assets\v23
V23_OUTPUT_ROOT=D:\flood-output
V23_FONT_PATH=C:\Windows\Fonts\malgun.ttf
```

저장소에는 OFL 라이선스의 Noto Sans KR 글꼴이 포함되어 있어 `V23_FONT_PATH`는 보통 비워둔다.

## 실행

### macOS/Linux

```bash
./run_v23.sh data/v23/events/valid_forecast_and_hydrology.json
```

### Windows

```bat
run_v23.bat data\v23\events\valid_forecast_and_hydrology.json
```

직접 실행:

```bash
python agents/guidance_v23_workflow.py \
  --event data/v23/events/valid_forecast_and_hydrology.json \
  --mode production
```

결과는 기본적으로 `output/guidance_v23/<run_id>/`에 저장된다. 표준 출력 JSON의 `final_video`가 완성 MP4 경로다.

## 백엔드 연결

Python 백엔드는 검증된 이벤트 객체를 직접 전달할 수 있다.

```python
from agents.v23_service import generate_guidance

result = await generate_guidance(trigger_event)
video_path = result["final_video"]
```

Python이 아닌 백엔드는 `guidance_v23_workflow.py`를 별도 작업 프로세스로 실행하고 표준 출력 JSON을 읽으면 된다. 상세 계약은 [백엔드 연동 문서](docs/BACKEND_INTEGRATION.md)를 참고한다.

## 테스트

```bash
python -m unittest discover -s tests -p "test*v23*.py"
python agents/guidance_v23_workflow.py --mode plan
```

실제 MP4 생성 전 설치 검증:

```bash
python scripts/verify_v23_installation.py --require-openai --decode-media
```

## 보안 및 운영 주의

- `.env`, API 키, 생성 영상과 TTS는 Git에 포함하지 않는다.
- 동일 `event_id`는 동일 `run_id`로 계산된다. 백엔드 작업 큐에서도 중복 요청을 차단해야 한다.
- V23은 팀 백엔드가 선택한 시나리오를 소비할 뿐 강우·수위 임계값을 다시 판단하지 않는다.
- 완성 MP4는 로컬 경로이므로 팀 백엔드가 객체 저장소에 업로드한 뒤 URL을 사용자에게 제공해야 한다.
- Windows 배포 전 `--decode-media` 검사를 실행해 Blender의 QTRLE 알파 MOV 디코딩을 확인한다.

## 주요 문서

- [백엔드 연동](docs/BACKEND_INTEGRATION.md)
- [자산 설치 및 Release 구성](docs/ASSET_SETUP.md)
- [V23 구조](docs/V23_ARCHITECTURE.md)
