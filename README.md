# 디자인 스튜디오 for Claude Code

지금 Claude Code로 만들고 있는 웹 앱 위에 **연습용 복제 앱 편집 도구**를 얹습니다. 화면을 직접 만지고 댓글을 달아 저장하면 Claude가 실제 코드로 옮기고 다듬습니다.

- **만지기**: 색(그라데이션 판·스포이트), 테마, 글자 크기·굵기, 간격, 모서리, 위치(끌어 옮기기), 크기, 순서, 글자
- **단추 동작**: 누를 때 일어날 단계를 짜고 시연합니다. 지금 동작은 AI가 코드에서 찾아 줍니다.
- **AI 추천**: "이건 어때요?" 카드가 바뀔 곳을 반짝이며 시연합니다.
- **시안**: 저장하면 Claude가 뒤에서 복사본을 고칩니다. 원래 화면과 시안을 오가며 보고 **이대로 반영 / 더 고쳐 줘 / 버리기** 중에 고릅니다.

앱은 실제로 아무것도 하지 않습니다. 쓰기 요청은 "했다 치고" 답하고, 연습 모드는 지어낸 데이터를 쓰고 바깥 연결을 막습니다.

## 시작하기 — 앱을 만들던 세션에 이렇게 말하세요

> 디자인 스튜디오 써 줘. https://github.com/tutleblue/claude-code-designtool 의 `skill/design-studio/SKILL.md` 를 따라 줘.

Claude가 하는 일:
1. 도구를 `~/.claude/design-studio/tool`로 받습니다.
2. `skill/GUIDE.md`를 따라 **이 앱을 분석해 개인화합니다.** 결과는 앱 저장소의 `.claude/design-studio/`에 생깁니다.
   - 앱을 띄우는 법
   - 화면·테마·색 토큰
   - 막을 요청
   - 가짜 데이터
   - 앱 디자인 규칙
3. `doctor` 점검이 통과하면 여는 명령을 알려 줍니다.

그다음부터는 같은 세션이나 같은 프로젝트에서 "스튜디오 열어 줘", "저장본 반영해 줘", "시안 반영해 줘"라고 말하면 됩니다.

### 모든 프로젝트에서 `/design-studio`로 쓰기 (선택)

```bash
# macOS · Linux
git clone --depth 1 https://github.com/tutleblue/claude-code-designtool ~/.claude/design-studio/tool
sh ~/.claude/design-studio/tool/install.sh
```
```powershell
# Windows
git clone --depth 1 https://github.com/tutleblue/claude-code-designtool "$env:USERPROFILE\.claude\design-studio\tool"
powershell -ExecutionPolicy Bypass -File "$env:USERPROFILE\.claude\design-studio\tool\install.ps1"
```

시작 스킬은 짧습니다. 도구를 받고(이미 있으면 새로 받고) 도구 안의 안내서를 따르게만 합니다. 그래서 도구가 좋아지면 스킬도 따라옵니다.

## 직접 쓰는 명령

```bash
python <도구>/run_studio.py init   --project <앱>   # 앱 분석 → 개인화 초안 + analysis.md
python <도구>/run_studio.py doctor --project <앱>   # 개인화 점검 (띄우기·도구·토큰·테마·화면 이동·쓰기 막기·콘솔 오류)
python <도구>/run_studio.py        --project <앱>   # 스튜디오 열기 (--mode real: 내 데이터, 쓰기 막음)
python <도구>/run_studio.py snapshot <저장본>       # (앱 폴더에서) 지금 / 요청한 모습 사진
```

시안 만들기와 AI 추천에는 [Claude Code](https://claude.com/claude-code) CLI(`claude`)가 필요합니다. 사진과 점검에는 Playwright(Chromium)가 필요합니다.

## 개인화 — 앱마다 다른 것

`<앱>/.claude/design-studio/`에 둡니다. 개인화 설정은 커밋하고, `<앱>/.design-studio/`(저장본·시안)는 git에서 뺍니다.

| 파일 | 내용 |
|---|---|
| `studio.app.json` | 띄우기(`launch` / `upstream` / `"serve": "static"`), 화면 폴더, 모드(demo·real), 요청 규칙(`pass`·`mock`·`deny`), 확인 명령. 칸 설명은 `studio/config.py` 맨 위 |
| `studio.app.js` | `window.__STUDIO_APP__`: 화면 이름·테마·토큰, 화면 이동·테마 바꾸기를 앱 함수로 |
| `context.md` | Claude가 시안·추천에 쓰는 앱 규칙(디자인 말투, 테마 블록, 반영 뒤 할 일) |
| `run_demo.py` 등 | 필요한 앱만: 임시 데이터, 바깥 연결 차단, 지어낸 데이터로 앱 서버 띄우기(`templates/launcher_python.py`) |

`init`이 확실한 것을 채웁니다. 판단이 필요한 것(어떤 쓰기를 통과시킬지, 가짜 데이터, 화면 이동 함수)은 Claude가 앱 코드를 읽고 채웁니다. 예: [Daling의 개인화](https://github.com/tutleblue/dgist-lms-autosaver/tree/claude/blissful-allen-amzdjp/.claude/design-studio)

지금은 **URL `/x`가 화면 폴더의 `x` 파일인 앱**(정적 화면, 파이썬·Node 서버가 화면 폴더를 그대로 주는 앱)이 시안까지 됩니다. Vite 같은 번들러 앱은 열기·만지기·댓글·저장·반영은 되지만, 시안은 꺼집니다(`"proposals": false`).

## 안전장치

- **쓰기 막기**: 쓰기 요청은 기본으로 가짜 답을 받습니다. 바깥 연결 차단·가짜 데이터는 앱 프로세스 안의 런처가 맡습니다.
- **스튜디오 API 보호**: 루프백 호스트만 받습니다. JSON이 아닌 POST는 거절합니다(CSRF). `X-Frame-Options: SAMEORIGIN`을 붙입니다.
- **저장본 검사**: 저장본과 AI 추천 값은 화면에 넣기 전에 거릅니다(XSS·CSS 주입).
- **시안을 만드는 Claude**:
  - `dontAsk`로 띄웁니다.
  - 쓰기는 시안 폴더에만 허락합니다. 진짜 화면 폴더 쓰기는 거부 규칙으로 막습니다.
  - 셸 명령은 사진 찍기와 확인 명령만, 정확한 글자로 허락합니다.
- **사진 찍기**: 앱 설정을 세션 파일에서 읽습니다(인자로 바꿀 수 없음). 브라우저는 스튜디오 밖으로 요청을 못 보냅니다.
- **반영**: 3-way 병합으로 합칩니다. 충돌이 하나라도 있으면 아무 파일도 쓰지 않습니다. 원본은 `before-apply/`에, 버린 시안은 `_discarded/`에 남깁니다.

## 시험

```bash
python tests/run.py   # 예제 앱(examples/hello)으로 24개 항목
```

## 폴더

| 경로 | 내용 |
|---|---|
| `skill/design-studio/SKILL.md` | 시작 스킬 (세션에 넣거나 `~/.claude/skills`에 설치) |
| `skill/GUIDE.md` | Claude용 안내서: 개인화·열기·저장본 반영·시안 모드·업데이트 |
| `run_studio.py` | 어디서든 부르는 입구 |
| `studio/` | `server.py`(셸·프록시·API), `config.py`, `init.py`(앱 분석), `doctor.py`(점검), `proposals.py`(시안), `ai.py`, `snapshot.py`, `assets/`(편집 도구·글꼴 OFL) |
| `templates/` | 런처 틀 |
| `examples/hello/` | 시험용 예제 앱 |
