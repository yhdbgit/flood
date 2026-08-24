# 오송 V16 침수 단계 구현

## 구현 범위

V16은 V15의 연속 평상시 하천 수면을 유지하면서 환경부 홍수위험지도 기반 침수면을 별도 객체로 구성한다. 영상은 생성하지 않으며 다음 세 상태만 제공한다.

| 상태 | 공식 최종범위 비율 | 농경지 영향률 | 의미 |
|---|---:|---:|---|
| 평상시 | 0% | 0.0% | V15 하천 수면만 표시 |
| 중간 | 33.85% | 36.8% | 공식 최종범위 내부의 점진적 시각화 중간 단계 |
| 최대 | 100% | 85.1% | 국가하천 100년 빈도 홍수위험지도 최종 범위 |

농경지 영향률은 침수 폴리곤과 등록 농경지 폴리곤의 공간 교차 면적으로 계산한다. 농경지 전체를 위험색으로 칠하지 않고 실제 교차 영역만 중간 단계는 주황색, 최대 단계는 빨간색으로 표시한다.

## 데이터 출처와 해석 제한

- 침수범위·침수심 등급: 환경부 홍수위험지도 정보시스템, 금강권역 국가하천 100년 빈도 지도
- 농경지: OpenStreetMap `landuse=farmland` 경계이며 지적도 필지가 아니다.
- 중간 단계는 수리모형의 시간별 예측값이 아니라 공식 최종 침수범위 안에서 범위를 점진적으로 드러낸 시각화다.
- 최대 단계는 100년 빈도 위험지도 시나리오이며 다음 강우사상의 실제 예상 범위를 의미하지 않는다.
- V16에는 한강홍수통제소 실시간 수위를 적용하지 않았다.

## 재현 순서

```bash
cd /Users/hyeokjae/Desktop/ICTCB/flood
PYTHONDONTWRITEBYTECODE=1 python3 scripts/prepare_osong_inundation_v16.py
PYTHONDONTWRITEBYTECODE=1 python3 scripts/prepare_osong_inundation_mesh_v16.py
/Applications/Blender.app/Contents/MacOS/Blender --background \
  blender/osong_story_v15_water.blend \
  --python blender/build_osong_inundation_v16.py
```

## 산출물

- `data/processed/osong_inundation_v16.json`: 단계별 범위와 농경지 영향률
- `data/processed/osong_inundation_mesh_v16.json`: 지형 밀착형 범람·농경지 교차 메시
- `blender/osong_inundation_v16.blend`: 평상시 상태로 저장된 재사용 장면
- `output/inundation_v16/normal.png`
- `output/inundation_v16/intermediate.png`
- `output/inundation_v16/maximum.png`
- `output/inundation_v16/scene_report.json`

Blender 장면의 `V16_INUNDATION_STAGES` 컬렉션에서 `intermediate` 또는 `maximum` 객체의 뷰포트 표시를 켜면 단계별 범람면을 확인할 수 있다. 기본 저장 상태는 평상시이며 MP4는 생성하지 않는다.
