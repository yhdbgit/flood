# V23 Runtime Asset Release

V23은 트리거 시 전체 3D 장면을 렌더링하지 않는다. GitHub Release의 사전 렌더링 자산 12개를 한 번 설치하고 이후 요청에서 재사용한다.

## Release

- Tag: `v23-assets-1.0.0`
- `v23-assets-core.zip`
- `v23-assets-flood-a.zip`
- `v23-assets-flood-b.zip`

파일 크기와 SHA-256은 `config/runtime_asset_bundles_v23.json`에 기록한다. 개별 영상의 크기와 SHA-256은 `config/runtime_assets_v23.json`에 기록한다.

## 최초 게시 절차

이 작업은 자산 버전마다 담당자 한 명이 한 번만 수행한다.

1. `hyeokjae` 브랜치의 전달 커밋을 GitHub에 푸시한다.
2. GitHub 저장소의 **Releases → Draft a new release**로 이동한다.
3. 새 태그 `v23-assets-1.0.0`을 만들고 대상 브랜치를 `hyeokjae`로 지정한다.
4. 로컬 `release/v23-assets-1.0.0/`의 ZIP 세 개를 모두 첨부한다.
5. Release를 게시한 뒤 깨끗한 클론에서 `python scripts/setup_v23.py`를 실행한다.

`release/` 폴더와 ZIP은 Git 커밋 대상이 아니다. 게시 후 팀원은 ZIP을 직접 복사할 필요 없이 설치기가 Release URL에서 내려받는다.

## 자동 설치

```bash
python scripts/setup_v23.py
```

설치 위치는 기본적으로 `runtime_assets/v23`이다. 서버 공용 디스크를 사용하려면 `.env`의 `V23_ASSET_ROOT`를 설정한다.

## 무결성 및 Windows 디코더 확인

```bash
python scripts/verify_v23_installation.py --decode-media
```

이 검사는 파일 크기와 SHA-256을 확인하고 Blender의 번들 FFmpeg가 MP4와 QTRLE 알파 MOV를 열 수 있는지 검사한다.

## Git 포함 정책

대용량 영상 자체는 Git에 포함하지 않는다. 저장소에는 카탈로그, 설치기, 검증기와 빈 `runtime_assets/v23/README.md`만 포함한다.
