# V23 구조

## 등록 시점

현재 전달본에는 세 데모 필지의 농경지별 배경, 강조 레이어, 범람 레이어가 준비되어 있다. 이 자산은 GitHub Release에서 설치된다.

## 트리거 시점

```text
trusted trigger event
  -> event contract validation
  -> field ownership lookup
  -> cached asset selection
  -> 6-strip personalized visual composition
  -> parallel OpenAI TTS
  -> information cards
  -> final 80-second MP4
```

개인화 시각 영상은 공통 배경, 선택 농경지 배경, 선택 농경지 범람, 선택 농경지 경계, 공용 대피소 범람, 공용 대피소 표시의 여섯 스트립으로 구성한다. 다른 농경지의 캐시는 선택되지 않는다.

## LangGraph

```text
START
  -> script_agent
  -> tts_agent
  -> video_production_agent
  -> composition_agent
  -> END
```

별도 검증 에이전트는 없다. 이벤트·소유권·파일 존재 같은 필수 검사는 각 경계에서 수행한다.
