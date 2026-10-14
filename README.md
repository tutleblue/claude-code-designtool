# 디자인 스튜디오

웹 앱 위에 편집 도구를 얹은 **연습용 복제 앱**입니다. 화면을 직접 만지고 댓글을 달아 저장하면 Claude Code가 그것을 실제 코드로 옮깁니다.

- **만지기**: 색(그라데이션 판·스포이트), 테마, 글자 크기·굵기, 간격, 모서리, 위치(끌어 옮기기), 크기(모서리 끌기), 순서, 글자.
- **단추 동작**: 누르면 일어날 일을 단계로 짜고 시연합니다. 지금 동작은 AI가 코드에서 찾아 줍니다.
- **AI 추천**: "이건 어때요?" 카드가 바뀔 곳을 반짝이며 시연합니다.
- **조합 A/B**: 여러 안을 숫자 키로 비교합니다.
- **시안**: 저장하면 Claude가 뒤에서 복사본을 고칩니다. 원래 화면과 시안을 오가며 보고 **이대로 반영 / 더 고쳐 줘 / 버리기** 중에 고릅니다.

앱 코드는 한 줄도 바꾸지 않습니다. 진짜 앱 서버 앞에 프록시로 서서 첫 화면에 도구만 끼워 넣습니다. 쓰기 요청은 설정에 적은 것 말고는 "했다 치고" 답합니다.

## 빠른 시작

```bash
pip install playwright        # 사진 찍기·시험용 (Chromium 필요)
python -m studio --app examples/hello/studio.app.json
```

브라우저가 열리면 아래 막대의 **고르기(S)**로 제목을 눌러 크기를 바꿔 보고, **댓글(C)**로 한 곳에 댓글을 단 뒤 **저장해서 Claude에게**를 누릅니다.

시안 만들기와 AI 추천은 이 컴퓨터에 [Claude Code](https://claude.com/claude-code) CLI(`claude`)가 있어야 합니다. 경로가 다르면 `STUDIO_CLAUDE`로 알려 줍니다.

## 내 앱에 붙이기

앱마다 설정 파일 `studio.app.json`을 하나 만듭니다. 자세한 칸 설명은 `studio/config.py` 맨 위에 있습니다.

```json
{
  "name": "내 앱",
  "webRoot": "public",
  "launch": ["npm", "run", "dev", "--", "--port", "{port}"],
  "context": "studio-context.md",
  "checks": ["node --check {web}/app.js"],
  "requests": { "pass": ["POST /api/preview"], "mock": { "GET /api/weather": {"ok": true} } }
}
```

```bash
python -m studio --app <설정 파일> --project <앱 저장소>
```

- `webRoot`: 화면 파일 폴더입니다. 시안은 이 폴더의 글자 파일을 복사해 고칩니다. 지금은 URL `/x`가 `webRoot/x`인 정적 화면에 맞춰져 있습니다.
- `launch` 또는 `upstream`: 스튜디오가 앱을 띄우거나(`{port}`에 빈 포트를 넣습니다), 이미 떠 있는 주소로 붙습니다.
- `requests`: `deny`(막기) · `mock`(적어 둔 답) · `pass`(앱에 넘기기). 적지 않은 쓰기 요청은 가짜 답을 받습니다.
- `context`: Claude에게 줄 앱 규칙입니다. 테마 블록 위치, 번역, 빌드처럼 앱마다 다른 것을 짧게 적습니다.
- `client`(선택): 화면 이름·테마·토큰·화면 바꾸기를 알려 주는 스크립트(`window.__STUDIO_APP__`)입니다. 없으면 `:root`의 CSS 변수를 찾아 씁니다.
- 앱 저장소의 `.gitignore`에 `.design-studio/`를 넣습니다. 저장본·시안이 여기에 쌓입니다.
- Claude Code 스킬 `skill/SKILL.md`를 앱 저장소의 `.claude/skills/design-studio/SKILL.md`로 복사하면 "저장본 반영해 줘"를 알아듣습니다.

예시: `adapters/daling/`(Daling 데스크톱 앱 — 가짜 학생 데이터, 바깥 연결 차단, 테마 4개).

## 안전장치

- **쓰기 막기**: 쓰기 요청은 기본으로 가짜 답을 받습니다. 바깥 연결 차단은 앱 런처가 앱 프로세스 안에서 합니다(예: `adapters/daling/run_demo.py`).
- **스튜디오 API 보호**:
  - `127.0.0.1`/`localhost` 호스트만 받습니다(DNS 리바인딩 차단).
  - `application/json`이 아닌 POST는 거절합니다(CSRF 차단).
  - `X-Frame-Options: SAMEORIGIN`을 붙입니다.
- **시안을 만드는 Claude**:
  - `--permission-mode dontAsk`로 띄웁니다.
  - 쓰기는 시안 폴더에만 허락합니다. 진짜 화면 폴더 쓰기는 거부 규칙으로 막습니다.
  - 셸 명령은 사진 찍기와 설정의 `checks`만, 정확히 그 글자로 허락합니다.
- **사진 찍기**:
  - 앱 설정을 인자가 아니라 스튜디오가 남긴 세션 파일에서 읽습니다.
  - 브라우저는 스튜디오 서버 밖으로 요청을 못 보냅니다.
  - 사진용 서버는 스튜디오 API 쓰기를 거절합니다.
- **반영**:
  - 3-way 병합(`git merge-file`)으로 합칩니다. 충돌이 하나라도 있으면 아무 파일도 쓰지 않습니다.
  - 반영 전 원본은 `before-apply/`에 남깁니다.
  - 버린 시안은 `_discarded/`로 옮깁니다(지우지 않습니다).

## 시험

```bash
python tests/run.py
```

예제 앱으로 띄워 확인합니다(22개 항목, `claude`는 필요 없습니다):

- 화면: 도구 뜸, 토큰 자동 찾기, 바꾸기, 댓글
- 저장과 다시 열기
- 막기: 쓰기 요청, CSRF, 호스트, 저장본 XSS
- 시안 반영: 충돌, CRLF
- 사진

## 폴더

| 경로 | 내용 |
|---|---|
| `studio/server.py` | 셸·프록시·스튜디오 API |
| `studio/config.py` | 앱 설정 읽기·요청 규칙 |
| `studio/proposals.py` | 시안 (`claude -p`, 반영, 버리기) |
| `studio/ai.py` · `claude_cli.py` | AI 추천·동작 알아보기·`claude` 띄우기 |
| `studio/snapshot.py` | 저장본 사진(now·target·proposal·after) |
| `studio/assets/` | 편집 도구(`studio.js`), 글꼴(Lora·Poppins, SIL OFL) |
| `adapters/<앱>/` | 앱별 설정·런처·규칙 |
| `skill/SKILL.md` | 앱 저장소에 넣을 Claude Code 스킬 |
| `examples/hello/` | 시험용 예제 앱 |
