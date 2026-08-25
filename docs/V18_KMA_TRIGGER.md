# V18 통합 입력 스키마와 기상청 트리거

V18은 기상청 단기예보를 하루 전 영상 생성의 주 트리거로 사용하고, 환경부 홍수위험지도와 등록 농경지의 공간 중첩을 필지 조건으로 사용한다. 한강홍수통제소 수위는 현재 상태 확인용이며 하루 뒤 범람을 예측하는 입력으로 사용하지 않는다.

공식 API: [공공데이터포털 기상청 단기예보 조회서비스](https://www.data.go.kr/data/15084084/openapi.do)

기상청 단기예보는 일 8회 발표되지만 본 MVP는 농업인의 사전 조치 시간을 확보하기 위해 매일 05시 발표분만 사용한다.

## 판정식

```text
05시 발표 단기예보의 다음 날 PCP 24개가 모두 존재
AND 24시간 대표 누적강수량 >= 80mm
AND 공식 100년 빈도 침수범위와 필지 중첩률 >= 10%
AND 같은 필지의 최근 성공 이벤트가 48시간 이내에 없음
= 영상 생성 대상
```

80mm는 현재 사건 표본으로 정한 MVP 후보 임계값이며 기상청의 공식 특보 기준이 아니다. 필지 조건 역시 해당 강우량으로 계산한 수리해석 결과가 아니라 공식 홍수위험지도 중첩을 이용한 대체 조건이다.

## 생성 파일

- `data/runtime/kma_forecast_v18.json`: 정규화된 24시간 PCP와 누적값
- `data/runtime/guidance_context_v18.json`: 영상 제작 전체 입력과 판정 근거
- `data/runtime/v18_dispatch_history.json`: `--record-trigger` 사용 시 기록되는 48시간 쿨다운 이력

위 파일은 실행 중 재생성되는 런타임 데이터이므로 Git에 포함하지 않는다.

## 환경 변수

`.env`에 공공데이터포털에서 발급받은 기상청 단기예보 서비스 키를 추가한다.

```dotenv
KMA_SERVICE_KEY=발급받은_일반인증키
```

## 실행

실데이터 판정:

```bash
cd /Users/hyeokjae/Desktop/ICTCB/flood
PYTHONDONTWRITEBYTECODE=1 python3 scripts/run_kma_trigger_v18.py
```

판정만 수행하는 기본 실행은 쿨다운을 시작하지 않는다. 이후 영상 제작 작업이 정상 접수된 시점에만 다음 옵션을 사용한다.

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/run_kma_trigger_v18.py --record-trigger
```

테스트:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_kma_trigger_v18 -v
```

## 실패 정책

- 다음 날 PCP가 24개 미만이면 `unavailable`이며 영상을 만들지 않는다.
- 05시 예보가 설정된 신선도 한계를 넘으면 `unavailable`이다.
- KMA 키 또는 네트워크 오류가 발생하면 기존 값을 정상 예보로 간주하지 않는다.
- `PCP`가 범주형 문자열이면 대표값뿐 아니라 하한과 상한을 함께 저장한다.
- HRFCO 수위가 오래됐더라도 기상청 트리거를 정상 수위로 바꾸지 않고 별도 `unavailable`로 표시한다.
