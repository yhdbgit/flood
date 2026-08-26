# V23 백엔드 연동

## 책임 경계

팀 백엔드는 예보·수위 수집, 임계값, 쿨다운, 발송 결정을 담당한다. V23은 `flood_guidance_requested` 이벤트를 받아 농경지 소유권을 확인하고 MP4를 생성한다.

## 요청 예시

```json
{
  "schema_version": "1.0",
  "event_type": "flood_guidance_requested",
  "event_id": "FLOOD-2026-08-27-OSONG-001",
  "user_id": "USER-DEMO-001",
  "field_id": "OSONG-FIELD-DEMO-001",
  "scenario_id": "caution",
  "triggered_at": "2026-08-26T06:00:00+09:00",
  "requested_at": "2026-08-26T06:00:02+09:00",
  "source": {"system_id": "team-trigger-service", "trigger_version": "v1"},
  "forecast_summary": {
    "rain_24h_mm": 80,
    "expected_start_at": "2026-08-27T05:00:00+09:00",
    "summary_text": "내일 새벽부터 강한 비가 예상됩니다."
  },
  "hydrology_summary": {
    "station_id": "3011685",
    "observed_at": "2026-08-26T05:50:00+09:00",
    "water_level_m": 1.42,
    "alert_level": "normal"
  }
}
```

`should_generate_video`, `rain_threshold_mm`, `cooldown_hours`는 V23 요청에 넣지 않는다. 이 값들은 팀 트리거 서비스 내부 책임이다.

## Python 비동기 호출

```python
from agents.v23_service import generate_guidance

result = await generate_guidance(event, mode="production")
```

반환 핵심 필드:

```json
{
  "status": "completed",
  "run_id": "V23-...",
  "event_id": "FLOOD-...",
  "field_id": "OSONG-FIELD-DEMO-001",
  "final_video": "/.../output/guidance_v23/...mp4"
}
```

백엔드는 `final_video`를 S3 또는 서비스 파일 저장소에 업로드하고 사용자 접근 URL로 변환한다.

## 비 Python 백엔드

작업 큐 워커에서 다음 프로세스를 실행하고 표준 출력 JSON을 읽는다.

```text
python agents/guidance_v23_workflow.py --event <event.json> --mode production
```

권장 작업 상태는 `queued -> processing -> completed | failed`다. `event_id`를 멱등성 키로 사용하고 동일 이벤트가 처리 중이거나 완료됐다면 중복 실행하지 않는다.

## 현재 제약

- 등록된 세 데모 농경지와 `caution` 시나리오만 캐시가 준비되어 있다.
- 새 농경지 등록은 별도의 사전 자산 생성 절차가 필요하다.
- API 서버와 작업 큐 구현은 팀 백엔드 소유다.
