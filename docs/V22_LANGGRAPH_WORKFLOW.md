# V22 동적 디지털트윈 LangGraph 영상 제작

## 결과

승인된 Blender 장면을 1280×720, 16fps, 60초 무음 본편으로 한 번만 렌더링했다. 이후 LangGraph 실행은 본편을 다시 렌더링하지 않고 TTS와 2개의 정보 카드만 합성한다.

- 재사용 본편: output/visual_v22/osong_visual_v22_60s.mp4
- 최종 스테이징 영상: output/guidance_v22_staging/V22-2026-08-26-6716025caa/osong_guidance_v22.mp4
- 최종 길이: 80초
- 본편: 60초
- 행동요령 카드: 10초
- 공식정보 카드: 10초

## 장면 흐름

1. 전체 지역과 1차 범람
2. 범람 이전으로 초기화
3. 등록 농경지 확대
4. 농경지 근접 2차 범람
5. 침수 상태에서 전체 줌아웃
6. 오송읍복지회관 위치 표시와 줌인
7. 비가 오기 전 행동요령 카드
8. 공식 재난안내 확인 카드

환경부 100년 빈도 위험지도의 색상 등급이나 농경지 중첩률은 화면과 대본에서 제거했다. 범람면은 V21에서 제작한 공식 최대 위험범위 내부의 시각적 진행 장면이며 특정 강우량의 수리해석 시간예측으로 표현하지 않는다.

## 4개 에이전트

START → script_agent → tts_agent → video_production_agent → composition_agent → END

- 대본 생성 Agent: V18 통합 컨텍스트에서 강수량, 농경지, 행동요령, 대피시설을 읽어 6개 구간 대본을 만든다.
- TTS 생성 Agent: 6개 음성을 OpenAI TTS로 비동기 병렬 생성한다. 각 음성은 배정 구간 끝에서 강제로 잘라 다음 음성과 겹치지 않게 한다.
- 영상 제작 Agent: 승인된 60초 V22 본편을 재사용하고 행동요령·공식정보 카드만 생성한다. Blender 지형 렌더링을 호출하지 않는다.
- 합성 Agent: Blender VSE에서 본편, 카드, TTS를 80초 MP4로 합성한다.

## 실행

계획 모드:

PYTHONDONTWRITEBYTECODE=1 python3 agents/guidance_v22_workflow.py --context data/staging/guidance_context_v18_80mm.json --mode plan --output-root /private/tmp/flood-v22-plan

스테이징 전체 제작:

PYTHONDONTWRITEBYTECODE=1 python3 agents/guidance_v22_workflow.py --context data/staging/guidance_context_v18_80mm.json --mode staging --output-root output/guidance_v22_staging

구조 테스트:

PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_guidance_v22_workflow -v

## 검증

- V22 무음 본편: 960프레임, 16fps, 60초
- 최종 영상: 1280프레임, 16fps, 80초
- OpenAI TTS: 6개 모두 성공, 병렬 생성
- 음성 스트립: 6개 비중첩
- 본편 재렌더링: 없음
- 정보 카드: 2개
