# 오송 V14 3km 재사용 배경 컨텍스트

## 목적

V13 영상의 전체 카메라에서 1km 지형 메시의 직사각형 경계가 노출되는 문제를 해결하기 위한 재사용 데이터다. 기존 오송 중심점과 1km 정밀 영역은 변경하지 않고, 동일 원점 주위에 3km × 3km 저해상도 배경 지형을 추가한다.

## 상세도 구조

- 외곽 배경: 3,000m × 3,000m, SRTM 129 × 129, Esri World Imagery zoom 16
- 중앙 정밀 영역: 기존 1,000m × 1,000m, SRTM 129 × 129, Esri World Imagery zoom 18
- 좌표계: EPSG:32652
- 중심점: V11/V13과 동일
- 침수 분석 범위: 확장하지 않음. 3km 외곽은 시각적 배경 전용

## 재사용 파일

- `config/pilot_area_v14_3km.json`: 3km AOI와 V11 계보
- `data/processed/osong_context_v14_3km.json`: 지형·하천·도로·건물·필지 컨텍스트
- `data/processed/osong_context_v14_3km_manifest.json`: 파일 크기·SHA-256·출처·Blender 장면 기록
- `data/gis/osong_context_v14_3km/`: 외곽 위성영상, 타일, 메타데이터, 출처
- `blender/osong_context_v14_3km.blend`: 중앙 정밀 지형과 외곽 배경이 결합된 재사용 장면
- `output/context_v14_3km/`: 준비 및 장면 생성 보고서

## 다시 생성하는 방법

```bash
cd /Users/hyeokjae/Desktop/ICTCB/flood
PYTHONDONTWRITEBYTECODE=1 python3 scripts/prepare_osong_context_v14_3km.py
/Applications/Blender.app/Contents/MacOS/Blender --background --factory-startup --python blender/build_osong_context_v14_3km.py
```

두 명령 모두 MP4를 생성하지 않는다. 첫 번째 명령은 데이터와 위성영상을 준비하고, 두 번째 명령은 재사용 가능한 `.blend` 장면만 저장한다.
