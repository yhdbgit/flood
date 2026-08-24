# 강내면 고품질 GIS 배경 장면 V10

## 구현 범위

V10은 기존 V9 영상과 장면을 수정하지 않고 별도로 만든 1km × 1km GIS 배경 장면이다.

1. 등록 농경지 중심 AOI와 EPSG:32652 좌표 원점을 고정했다.
2. SRTM 지형에 Esri World Imagery 항공영상을 UV 텍스처로 적용했다.
3. OpenStreetMap 도로·교량·수계와 VWorld 하천관리구역 경계, 등록 농경지를 같은 좌표계로 배치했다.

## 결과 파일

- Blender 장면: `blender/gangnae_hq_v10.blend`
- 데이터 준비 스크립트: `scripts/prepare_gangnae_hq_v10.py`
- 장면 생성기: `blender/build_gangnae_hq_v10.py`
- 최종 시각 보정 실행기: `blender/build_gangnae_hq_v10_refined.py`
- 저장 장면 검증기: `blender/validate_gangnae_hq_v10.py`
- 정합 데이터: `data/processed/gangnae_hq_v10_context.json`
- 항공영상 캐시: `data/gis/gangnae_hq_v10/esri_world_imagery_z18.jpg`
- 검증 결과: `output/hq_v10/saved_blend_validation.json`

## 재생성 방법

온라인 자료를 새로 받을 때만 다음 명령을 실행한다.

```bash
cd /Users/hyeokjae/Desktop/ICTCB/flood
/Users/hyeokjae/Desktop/ICTCB/.venv/bin/python scripts/prepare_gangnae_hq_v10.py --refresh
```

캐시된 데이터로 Blender 장면과 QA 렌더를 생성한다.

```bash
/Applications/Blender.app/Contents/MacOS/Blender \
  --background --factory-startup \
  --python blender/build_gangnae_hq_v10_refined.py
```

저장된 장면을 새 프로세스로 검증한다.

```bash
/Applications/Blender.app/Contents/MacOS/Blender \
  --background blender/gangnae_hq_v10.blend \
  --python blender/validate_gangnae_hq_v10.py
```

## 검증 결과

- AOI: 1,000m × 1,000m
- 지형 정점: 16,641개
- 항공영상: 2,048 × 2,129px
- 도로: 41개
- 교량: 2개
- 수면·수로: 3개
- VWorld 공식 하천구역 경계: 1개
- 카메라: 3개
- 저장 장면 재개방 검사: 통과

## 데이터 해석 경계

- 현재 등록 농경지는 지적 필지가 아니라 기존 OSM 농경지 관계 내부에 만든 데모 경계다. 항공영상에서는 고속도로 교차로 내부 녹지와 일부 겹치므로, 실제 서비스 전에는 농업인이 등록한 필지 또는 지적도 경계로 교체해야 한다.
- 해당 1km AOI의 현재 OSM 응답에는 건물 윤곽이 없었다. 실제 자료가 없는 상태에서 임의 건물을 생성하지 않았다.
- 지형은 약 30m급 SRTM이므로 항공영상의 세부 도로·제방 높이를 재현하지 못한다. 1~5m급 국가 DEM/DSM으로 교체하면 개선된다.
- VWorld UJ201/UJ301은 하천관리구역 참고 경계이며 현재 물이 흐르는 면이 아니다. 화면의 수면은 OSM 수계 형상을 사용한다.
- V10은 공간 배경 품질 개선 단계다. 홍수 범람 범위의 정확도를 보장하는 수리해석 결과가 아니다.

## 출처

- 항공영상: Esri World Imagery
- 벡터 공간정보: OpenStreetMap contributors, ODbL
- 공식 하천관리구역: VWorld UJ201/UJ301
- 지형: SRTM N36E127 1 arc-second

