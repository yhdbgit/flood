# 강내면 파일럿 디지털 트윈 데이터

## 파일럿 범위

- 충청북도 청주시 흥덕구 강내면 일대
- 대상 하천 시나리오: 농송천 주변
- 모자이크 범위: WGS84 경도 127.33154297–127.38647461, 위도 36.58465761–36.61552763

## 확보 자료

| 파일 | 용도 | 상태 |
|---|---|---|
| `N36E127.hgt` | 공개 30m급 SRTM 지형 고도자료. Blender 지형 메시 생성용 | 확보 |
| `floodmap_50yr_z16_mosaic.png` | 공식 홍수위험지도 금강권 지방하천 50년 빈도 시나리오의 투명 타일 모자이크 | 확보 |
| `floodmap_50yr_z16_mosaic.json` | 타일 좌표, 원본 URL, 지리적 범위 메타데이터 | 확보 |
| `gangnae_farmland_osm_demo.geojson` | OpenStreetMap의 농경지 멀티폴리곤. 시연용 농경지 후보 | 확보 |
| `gangnae_farmland_osm_raw.json` | 위 GeoJSON의 원본 OSM 응답 | 확보 |
| `gangnae_osm_context.geojson` | 파일럿 주변 하천·수로·접근도로를 선별한 시연용 공간정보 | 확보 |
| `gangnae_osm_map.osm` | 위 공간정보의 OSM 원본 범위 응답 | 확보 |
| `layer_region_river.kml` | 홍수위험지도 포털의 공식 지방하천 전체 KML 레이어 | 확보 |
| `gangnae_underpass_roads_050.json` | 공식 포털의 50년 빈도 침수 우려 도로 시설 중 파일럿 범위 결과 | 조회 결과 0건 |
| `floodmap_50yr_z16_tiles/` | 공식 범람지도 원본 PNG 타일 | 확보 |

## 중요한 데이터 경계

- 범람 PNG는 공식 홍수위험지도에서 제공하는 시나리오 레이어다. 특정 강우예보가 시간에 따라 변하는 실시간 예측값이 아니다. 1차 Blender 검증에서는 이 레이어를 `침수 시작/확대/최대` 장면의 기준 마스크로 사용한다.
- `gangnae_farmland_osm_demo.geojson`은 지적도상의 농업인 소유 필지 경계가 아니다. 실제 서비스의 필지 조건 트리거에는 지적 필지 또는 사용자가 직접 등록한 경계 좌표가 추가로 필요하다.
- `N36E127.hgt`는 공식 국가 DEM이 아닌 공개 SRTM 대체자료다. 제안서·시연에서는 “1차 시각화용 지형자료”로 표기하고, 정밀 검증 단계에서 국토교통부/국가공간정보 플랫폼 DEM으로 교체한다.

## Blender 1차 검증 순서

1. `N36E127.hgt`에서 강내면 범위만 잘라 지형 메시를 만든다.
2. GeoJSON의 농경지 후보 2개를 지형 위에 배치하고 빨간 외곽선으로 표시한다.
3. `floodmap_50yr_z16_mosaic.png`를 지형 위에 좌표 보정해 투명 오버레이한다.
4. 카메라를 전체 지역 → 하천 → 농경지 순으로 이동시킨다.
5. 프레임 1–80에서 침수 마스크 불투명도를 0→1로 키워 침수 범위가 확대되는 장면을 만든다.
6. 농경지 외곽선이 침수 마스크에 포함되는 순간부터 강조색·라벨·경고 아이콘을 표시한다.
7. Blender `Render Animation`으로 MP4가 자동 생성되는지 확인한다.

## 출처

- 홍수위험지도: https://www.floodmap.go.kr/ 및 https://data.floodmap.go.kr/
- 지형자료 타일: https://s3.amazonaws.com/elevation-tiles-prod/skadi/N36/N36E127.hgt.gz
- 농경지 후보: OpenStreetMap Overpass API 및 OSM 데이터베이스
