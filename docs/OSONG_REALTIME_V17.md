# 오송 V17 실시간 수위 단계 연동

## 목적

V17은 한강홍수통제소 수위 관측값을 수집하고 관측소의 공식 관심·주의·경보·심각 기준을 이용해 V16의 평상시·중간·최대 시각화 중 하나를 선택한다.

| 공식 수위 위험도 | V16 시각화 |
|---|---|
| 정상 | 평상시 |
| 관심·주의 | 중간 |
| 경보·심각 | 최대 |

이 매핑은 어떤 장면을 보여줄지 선택하는 규칙이다. 실시간 수위만으로 실제 침수범위나 침수심을 계산하는 수리모형이 아니다.

## 관측소 선택

1. 관측시각이 현재로부터 30분 이내인지 확인한다.
2. 수위값과 공식 위험도가 없는 관측소는 제외한다.
3. 사용 가능한 관측소 중 공식 위험도가 가장 높은 관측소를 선택한다.
4. 위험도가 같으면 등록 농경지에 더 가까운 관측소를 선택한다.

오래되거나 누락된 데이터만 남으면 정상 단계로 간주하지 않고 `unavailable`로 종료하며 Blender 장면을 만들지 않는다. 홍수예보 항목은 결과에 기록하지만 시각화 단계를 자동 상향하는 데 사용하지 않는다.

## 한 번에 실행

```bash
cd /Users/hyeokjae/Desktop/ICTCB/flood
PYTHONDONTWRITEBYTECODE=1 python3 scripts/run_osong_realtime_v17.py
```

실행 흐름:

1. `scripts/fetch_hrfco_data.py`가 API 수위·유량·공식 임계값을 갱신한다.
2. `scripts/prepare_osong_realtime_v17.py`가 관측소와 장면 단계를 선택한다.
3. `blender/apply_osong_realtime_v17.py`가 V16 장면의 해당 객체만 표시한다.
4. 현재 상태 정지 이미지와 V17 `.blend`를 저장한다.

API 호출 없이 기존 스냅샷으로 재실행할 때는 다음 명령을 사용한다. 이 경우에도 30분 신선도 검사를 통과해야 한다.

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/run_osong_realtime_v17.py --skip-fetch
```

## 산출물

- `data/runtime/hydro_snapshot.json`: 인증키가 제거된 관측 스냅샷
- `data/runtime/osong_realtime_state_v17.json`: 선택 근거와 단계
- `blender/osong_realtime_v17.blend`: 선택 단계가 적용된 장면
- `output/realtime_v17/current_state.png`: 현재 상태 정지 이미지
- `output/realtime_v17/decision_report.json`
- `output/realtime_v17/scene_report.json`
- `output/realtime_v17/workflow_report.json`

V17은 MP4를 생성하지 않으며, API 인증키도 JSON·Blender·로그 산출물에 저장하지 않는다.
