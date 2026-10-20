# 하루 한 장면 여행영어 — 인스타 자동 게시 봇

여행 상황별 영어 회화를 6장 캐러셀로 만들어 인스타그램(@ki_pacificpictures)에 매일 자동 게시한다.
모든 작업은 GitHub Actions에서 돌고, 결과는 레포에 커밋된다. (Actions 로그는 외부에서 못 읽으므로 결과·오류는 파일과 이슈 댓글로 남긴다.)

## 하루 흐름 (`.github/workflows/webtoon-bot.yml`, KST)
- 12:07 / 12:37 `generate` — 다음 편 대본+사진 생성 → `episode` 라벨 승인 이슈 열림
- 20:13 / 20:31 `publish` — 승인된 편을 20:50까지 기다렸다 게시 (21:03, 21:23 재시도)
- 매월 1일 `refresh` — 인스타 토큰 갱신
- 처리 안 된 편(대기/승인)이 있으면 새 편을 만들지 않는다.

## 이슈 댓글 명령 (`scripts/webtoon_bot.py` → `command`)
승인 이슈: `승인` · `지금 게시` · `그림 다시`(사진만) · `다시`(대본부터) · `건너뛰기` · `주제 <상황>`
관리 이슈 #1: `중단` · `시작` · `상태` · `주제 <상황>`(다음 편 지정)
모든 명령은 `checks/command_log.md` 에 기록된다.

## 수동 실행
`config/trigger.json` 을 수정해 push 하면 봇이 그 action 을 실행한다.
`{"action": "generate" | "publish" | "rerender" | "publish_now" | "dryrun", "episode": "episodes/ep001"}`
- `rerender`: raw 사진이 없는 장만 다시 받아 합성 (특정 장을 바꾸려면 `raw/cutN.jpg` 삭제 후 실행)
- `publish_now`: 해당 편 승인+즉시 게시
- `dryrun`: 게시·이슈 없이 `checks/dryrun/` 에 테스트 편 생성

## 구성
- `scripts/write_episode.py` — Gemini 텍스트로 대본 작성 (상황: `config/situations.json` 순서, 장별 Pixabay 검색어 포함)
- `scripts/render_episode.py` — Pixabay 사진 검색·다운로드 + 반투명 자막 카드 합성 (1080x1350). 사진은 **"여성 + 장소(script의 place)" 인물 사진 우선**, 없으면 장소·사물 사진으로 대체. 패션·뷰티·사무실 사진은 제외
- `scripts/publish_instagram.py` — 인스타 Graph API(Instagram 로그인 방식) 캐러셀 게시, 캡션에 Pixabay 출처 자동 추가
- `config/series.json` — 시리즈 설정 (`photo_check`: Gemini가 사진 후보를 직접 보고 고르기, 기본 false)
- `episodes/epNNN/` — script.json, credits.json, raw/, final/, issue.json, APPROVED, published.json
- `archive/` — 이전 시리즈(고양이 웹툰, 기와세 여행일기, AI 실사 유나 버전 자료)

## Secrets
`GEMINI_API_KEY`(텍스트만 사용), `PIXABAY_API_KEY`, `INSTAGRAM_ACCESS_TOKEN`, (선택) `GH_PAT`(토큰 자동 갱신 저장용)

## 알려진 주의점
- Pixabay는 GitHub 서버에서 짧은 시간에 많이 받으면 429로 막는다 → 다운로드 간격을 두고 재시도함. 테스트를 연달아 돌리지 말 것.
- Pixabay 요청엔 User-Agent 헤더가 필요(없으면 403).
- 사진에 로고·엉뚱한 사진이 섞일 수 있음 → 승인 단계에서 `그림 다시`.
- GitHub 예약 실행은 늦거나 빠질 수 있어 여러 번 시도하도록 되어 있음 (중복 실행돼도 같은 편을 두 번 올리지 않음).
- AI 이미지 생성(Gemini 이미지 모델)은 비용 문제로 중단. 다시 쓰면 캡션에 AI 생성 표기 필요.
