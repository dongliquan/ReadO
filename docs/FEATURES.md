# ReadO 기능 정리 및 에디터 갭 분석

<input type="radio" name="xall" id="xo" checked style="display:none">
<input type="radio" name="xall" id="xc" style="display:none">
<style>
/* ═══ 1. 제목 위계 ═══════════════════════════════════════
   좌측 막대는 h2 전용. 챕터(h1)는 옅은 밴드 + 번호 배지(.num), 소제목(h3)은 옅은 배지(.n3), 문서 제목은 밑줄.
   <a id> 앵커는 <p>로 감싸져 "a + h1" 이 안 걸리므로 :first-of-type 로 구분. */
h1 { font-size: 1.3em; font-weight: 800; color: #2f3640; background: #eef1f4;
     border-radius: 6px; padding: 9px 13px 9px 10px; margin: 2.2em 0 1em }
/* 챕터 번호 배지 — 제목 앞 <span class="num">N</span> (부록은 A) */
.num { display: inline-block; min-width: 1.55em; text-align: center; background: #3f4650; color: #fff;
       border-radius: 6px; padding: 2px 8px; margin-right: 10px; font-size: .9em; line-height: 1.35; vertical-align: 2px }
h1:first-of-type { font-size: 1.5em; color: #212529; background: none; border-radius: 0;
     border-bottom: 3px solid #343a40; padding: 0 0 7px; margin: 1.8em 0 .8em }
h2 { font-size: 1.2em; font-weight: 700; color: #343a40;
     border-left: 6px solid #343a40; padding: 2px 0 2px 11px; margin: 1.5em 0 .6em }
h2:first-of-type { border-left: 0; padding-left: 0 }                          /* 목차 */
details h2:first-of-type { border-left: 6px solid #343a40; padding-left: 11px } /* 부록 A.1 */
h3 { font-size: 1.02em; font-weight: 700; color: #343a40; margin: 1.9em 0 .8em }   /* 항목 안 단락 경계 — 막대 없이 번호 배지로 */
.n3 { display: inline-block; background: #f1f3f5; color: #5b6168; border: 1px solid #dfe3e7;   /* 소제목 배지 N.M.k — 항목 배지보다 한 단 옅게 */
      border-radius: 4px; padding: 0 6px; margin-right: 8px; font-size: .82em; font-weight: 800; vertical-align: 1px }
/* 본문 문단 간격 — 소제목→문단(.8em)보다 문단↔문단(.5em)이 작아야 "소제목이 문단을 거느린다"로 읽힌다. 넓으면 빈 줄이 들어간 듯 보인다(실제 지적) */
.ib p { margin: .3em 0 .5em }
h4 { font-size: .96em; font-weight: 700; color: #6c757d; margin: 1.5em 0 .5em }
h4::before { content: "▸ "; color: #adb5bd }
/* 제목 줄 우측 컨트롤 (float 이라 .hctl 이 든 heading 에만 걸린다) */
.hctl { float: right; font-weight: 400; white-space: nowrap; margin-left: 14px }
h1 .hctl { font-size: .6em; padding-top: .35em }
h1 .hctl a { color: #0969da }
h2 .hctl { font-size: .72em; padding-top: .18em }
/* 부록 헤더(summary.apx) — 챕터 밴드와 같은 모양, 펼침 삼각형 없이 */
summary.apx { list-style: none; cursor: pointer; font-size: 1.3em; font-weight: 800; color: #2f3640;
     background: #eef1f4; border-radius: 6px; padding: 9px 13px 9px 10px; margin: 2.2em 0 1em }
summary.apx::-webkit-details-marker { display: none }  summary.apx::marker { content: "" }
summary.apx .hctl { font-size: .6em; padding-top: .35em }
summary.apx .hctl a { color: #0969da }
/* ═══ 2. 접히는 항목(.it) — 체크박스 방식 ══════════════════
   native details 는 닫힌 내용을 shadow slot에서 숨겨 CSS로 못 되살린다
   → '전체 접기' 뒤 개별 펼치기가 불가. 그래서 체크박스로 상태를 직접 가진다.
   (CSS 주석에 꺾쇠 태그 리터럴을 쓰지 말 것 — 태그 균형 검사에 잡힌다)
   모드별 체크박스 2개(.ca 펼침모드 / .cb 접기모드) → 모드 전환 시 반전 없음.
   ★ .it 는 라디오의 직계 형제 → 모든 규칙에 "~ .it" 와 "~ * .it" 를 함께 쓴다. */
.it { margin: 1.1em 0 1.5em }
.it + .it { border-top: 1px dashed #e3e7ea; padding-top: .9em }   /* 항목 "사이"에만 점선 → 마지막 항목엔 선 없음 */
.it > .ib { padding-left: 14px }                                    /* 본문 들여쓰기 — 헤더와 왼쪽 선이 같으면 소속이 안 보임 */
.it > .ih { display: block; font-size: 1.02em; font-weight: 700; color: #2f3640;
     padding: 4px 0; margin-bottom: .9em; cursor: pointer; user-select: none }
.it > .ih:hover { color: #0969da }
.it > .ih::after { content: "▼"; float: right; color: #adb5bd; font-size: .85em; padding-top: 2px }  /* 펼침 표시 = 우측 */
.ih .n { display: inline-block; background: #e9edf1; color: #3f4650; border-radius: 5px;             /* 옅은 번호 배지 */
         padding: 1px 7px; margin-right: 9px; font-size: .86em; font-weight: 800; vertical-align: 1px }
.ih .sub { color: #6c757d; font-weight: 500; margin-left: 6px; font-size: .92em }                    /* 회색 부제 */
/* 모드에 맞는 라벨 하나만 */
#xo:checked ~ .it > .lb, #xo:checked ~ * .it > .lb,
#xc:checked ~ .it > .la, #xc:checked ~ * .it > .la { display: none }
/* 펼침 모드: 체크 = 사용자가 닫음 */
#xo:checked ~ .it > .ca:checked ~ .ib,        #xo:checked ~ * .it > .ca:checked ~ .ib { display: none }
#xo:checked ~ .it > .ca:checked ~ .la::after,  #xo:checked ~ * .it > .ca:checked ~ .la::after  { content: "▶" }
/* 접기 모드: 체크 = 사용자가 열음 */
#xc:checked ~ .it > .cb:not(:checked) ~ .ib,        #xc:checked ~ * .it > .cb:not(:checked) ~ .ib { display: none }
#xc:checked ~ .it > .cb:not(:checked) ~ .lb::after,  #xc:checked ~ * .it > .cb:not(:checked) ~ .lb::after  { content: "▶" }
/* 목차의 전체 펼치기/접기 라벨 — 현재 모드를 굵게 */
#xo:checked ~ * label[for="xo"], #xc:checked ~ * label[for="xc"] { font-weight: 700 }
/* ═══ 3. 콜아웃 — 막대 없이 둥근 박스 + 라벨 ═════════════════ */
blockquote, .warn, .tip { border: 1px solid; border-radius: 7px;
     margin: .9em 0 1.4em; padding: 9px 12px; color: #333 }
blockquote { border-color: #cfe2f7; background: #f5f9fe }
blockquote > p:first-child { margin-top: 0 }  blockquote > p:last-child { margin-bottom: 0 }
h1 + blockquote, h2 + blockquote, h3 + blockquote { border: 0; background: none; border-radius: 0;   /* 제목 직후 > = 도입문(박스 아님) */
     padding: 0 0 0 2px; margin: -.2em 0 1.3em; font-size: 1.02em; color: #5b6168 }
.warn { border-color: #f0d9ac; background: #fffaf2 }
.warn::before { content: "⚠️ 주의"; display: inline-block; font-weight: 800; font-size: .82em;
     color: #a35d00; background: #fbeccc; border-radius: 20px; padding: 1px 9px; margin-right: 7px }
.tip { border-color: #b9e5c9; background: #f2fbf5 }
.tip::before { content: "💡 쉽게 말하면"; display: inline-block; font-weight: 800; font-size: .82em;
     color: #0b6b39; background: #d8f2e2; border-radius: 20px; padding: 1px 9px; margin-right: 7px }
/* ═══ 4. 표 · 코드 · 구분선 ════════════════════════════════
   표는 좁은 화면에서 표 안에서만 가로 스크롤. th 배경 없으면 본문 zebra보다 약해 보임. */
table { margin: .5em 0 1.5em !important; display: block; width: max-content;
        max-width: 100%; overflow-x: auto; border-collapse: collapse }
th, td { border: 1px solid #e4e7eb; padding: 6px 10px; text-align: left; vertical-align: top }
th { background: #e9edf1; color: #2f3640; font-weight: 700; text-align: center;   /* 배경으로 구분 → 테두리 없이 · 가운데 정렬 (실제 지적) */
     border: 0; white-space: nowrap }
pre { margin: .6em 0 1.5em !important; overflow-x: auto }
code { background: #f1f3f5; padding: 1px 5px; border-radius: 3px; font-size: .92em }
.cap { font-size: .86em; color: #868e96; margin: .3em 0 1.5em; padding-left: 2px }
table + .cap, pre + .cap { margin-top: -1.1em }        /* 표·코드 아래 캡션만 붙인다 — 도표 뒤에 음수면 겹친다(실제 사례) */
div[style*="Noto Sans KR"] { margin: .7em 0 1.5em }      /* 카드 흐름도 컨테이너 하단 여백 */
ul, ol { margin: .6em 0 1em }
hr { border: 0; margin: 2.2em 0 }   /* 선 없이 여백만 — 챕터 구분은 h1 밴드가 함 */
/* ═══ 5. 흐름 카드 — nowrap + 가로 스크롤 (wrap이면 좁은 화면에서 세로로 쌓임) ═══ */
.lay { display: flex; flex-wrap: nowrap; gap: 8px; margin: .7em 0 1.6em;
       align-items: stretch; overflow-x: auto; padding-bottom: 6px }
.cd { flex: 0 0 200px; border: 1px solid #e4e7eb; border-top-width: 4px; border-radius: 7px;
      padding: 8px 10px; background: #fff; font-size: 12px; line-height: 1.5 }
.cd > b { display: block; font-size: 12.5px; margin-bottom: 2px }
.cd .k { font-family: ui-monospace, Consolas, monospace; font-size: 11px; color: #495057 }
.cd .s { display: block; margin-top: 4px; color: #6c757d; font-size: 11px }
.ar { align-self: center; color: #adb5bd; font-weight: 800; font-size: 16px; flex: 0 0 auto }
.tg { display: inline-block; font-size: 10.5px; font-weight: 700; border-radius: 20px;
      padding: 1px 8px; margin-right: 4px }
/* ═══ 6. 번호 배지(.cn) — 원문자(circled digits) 대체 ═══════════════════
   U+2460~2473 은 폰트 대체(fallback)로 2·3·5·6 등 일부 글리프 모양이 달라진다(실제 지적).
   본문·표·캡션의 번호는 항상 <span class="cn">N</span> 으로 쓴다. 코드/SQL 안은 (1)(2) 로. */
.cn { display: inline-block; min-width: 1.55em; height: 1.55em; padding: 0 .2em; border-radius: 50%;
      border: 1.5px solid #3f4650; color: #2f3640; background: #fff; text-align: center;
      line-height: 1.45em; font-weight: 800; font-size: .82em; font-family: ui-monospace, Consolas, monospace;
      vertical-align: .08em; margin: 0 .12em }
/* 순서·단계 번호(1→2→3)는 .st(사각), 분류·종류 번호(상품종류 ①~⑥ 등)는 .cn(원형) — 같은 문서에서 두 뜻이 섞이면 모양으로 구분한다 */
.st { display: inline-block; min-width: 1.4em; height: 1.4em; padding: 0 .25em; border-radius: 3px;              /* 순서·단계 번호 — 분류 배지(.cn)와 모양을 가른다 */
      background: #e9edf1; color: #3f4650; text-align: center; line-height: 1.4em; font-weight: 700; font-size: .8em;
      font-family: ui-monospace, Consolas, monospace; vertical-align: .08em; margin: 0 .12em }
</style>

**대상**: `reado.py` · `server.py` · `source.html` · `config.json` · `build.bat` · `fetch-vendor.py` (커밋 `aebd051` + 미커밋 `reado.py` 변경)  
**기준**: 가벼운 에디터(VS Code lite / Notepad++ 수준)  
**범위**: §1은 분석 시점 기준이고, 이후 바뀐 부분(2단계 B, 설계 재점검 A–D)은 §2 표의 비고·§2.3·§2.9와 §3의 상태 열에 반영했다.

<div class="warn">2단계 B 반영: 편집·저장, 작업 폴더 밖 파일 열기, 상태 복원, 외부 변경 감지가 들어갔다. 해결 여부는 §3 표의 "상태" 열을 본다.</div>

<a id="toc"></a>

## 목차

- [**1. 구조 한눈에**](#cat-1)
- [**2. 현재 기능 목록**](#cat-2) (51개 · 8개 카테고리)
- [**3. 갭 리스트**](#cat-3) (상 8 · 중 10 · 하 7)
- [**4. 불필요·중복·죽은 코드**](#cat-4) (13건)
- [**5. 권장 착수 순서**](#cat-5)

---

<a id="cat-1"></a>

# <span class="num">1</span> 구조 한눈에 <span class="hctl"><a href="#toc">↑ 목차로</a></span>

> 데스크톱 창은 껍데기일 뿐이고, 기능은 전부 로컬 HTTP 서버와 단일 HTML 페이지에 들어 있다.

<div class="lay">
 <div class="cd" style="border-top-color:#6c8ebf"><b>reado.py</b><span class="k">pywebview 6.x · WebView2</span><span class="s">서버 스레드 기동 → 준비될 때까지 폴링 → 창 생성. JS API는 <code>pick_dir</code> 하나뿐. config는 %APPDATA%\ReadO</span></div>
 <div class="ar">→</div>
 <div class="cd" style="border-top-color:#82b366"><b>server.py</b><span class="k">http.server · 127.0.0.1:8766</span><span class="s">트리·파일·검색·심볼·설정 API와 /vendor 정적 서빙. ripgrep이 있으면 rg, 없으면 Python 병렬 검색</span></div>
 <div class="ar">→</div>
 <div class="cd" style="border-top-color:#d6b656"><b>source.html</b><span class="k">Monaco 0.45 · marked 12</span><span class="s">SPA 하나(1,768줄). 트리·탭·분할·Quick Open·FIF·설정 모달·테마</span></div>
 <div class="ar">→</div>
 <div class="cd" style="border-top-color:#b85450"><b>build.bat</b><span class="k">PyInstaller onefile</span><span class="s">vendor가 없으면 fetch-vendor.py를 먼저 실행 → dist\reado.exe(오프라인)</span></div>
</div>

---

<a id="cat-2"></a>

# <span class="num">2</span> 현재 기능 목록 <span class="hctl"><a href="#toc">↑ 목차로</a></span>

> 8개 카테고리에 51개 기능. "비고"에는 동작은 하지만 제약이 있는 부분을 적었다.

## 2.1 파일 열기 / 탐색 (9)

| ID | 기능 | 비고 |
|---|---|---|
| N1 | 파일 트리 지연 로딩: 폴더를 클릭하면 1단계씩 `/api/tree` 호출 | 폴더 먼저, 대소문자 무시 정렬. 새로고침 버튼 없음 |
| N2 | 무시 패턴 필터: 정확 일치와 `* ? []` 글롭 | 기본 `.git .svn .hg node_modules __pycache__ .venv venv`만 숨김(dot 파일은 보임). `build dist target out bin obj coverage`는 트리에 보이고 검색·Quick Open·심볼에서만 제외 |
| N3 | 텍스트 판별: 내용(NUL·제어문자 30%·BOM 없는 UTF-16) + 바이너리 확장자 차단 목록. 폴더 안/밖 같은 규칙 | `.txt .sh .toml .log`, `Dockerfile`, `.env` 등이 보이고 열리고 저장됨. 바이너리는 흐리게 표시되고 열기 거부(415 + 안내) |
| N4 | Go to File (`Ctrl+P`·`Ctrl+Shift+N`): 부분 문자열, `*` 와일드카드, 점수 정렬, 매치 하이라이트 | 50개 단위 스크롤 페이징. 퍼지 매칭은 아님 |
| N5 | Go to Line (`Ctrl+G`): Quick Open의 `:` 모드 | |
| N6 | Go to Symbol in File (`Ctrl+Shift+O`, Quick Open `@`) + 사이드바 outline 탭 | ctags(편집 중 버퍼 기준), 없으면 정규식 폴백(언어 15종) |
| N7 | Go to Definition(`F12`·`Ctrl+B`·Ctrl+클릭), 피크(`Alt+F12`), 사용처(`Shift+F12`·`Alt+F7`) — Monaco 기본 UI | ctags 인덱스 우선, 없으면 검색 + 언어별 선언 패턴(호출부 제외)·순위. 여러 건이면 피크 목록, `Alt+←/→` |
| N8 | 트리 자동 펼침(auto-reveal) + 활성 노드 강조, 브레드크럼 | |
| N9 | 사이드바 폭 드래그(180–600px) | 폭 저장됨 |

## 2.2 뷰어 (12)

| ID | 기능 | 비고 |
|---|---|---|
| V1 | Monaco 에디터 엔진(읽기 전용), 줄 번호·폴딩·선택 영역 공백 표시 | 미니맵 꺼짐 고정 |
| V2 | 확장자 → 언어 매핑 약 40종(`langFor`) | `.vue`는 html, `.toml`은 plaintext로 처리 |
| V3 | Atom One Light/Dark 테마(Monaco 테마 2종 직접 정의) + 🌙 토글 | 서버 `state.json`에 저장, 첫 화면부터 적용 |
| V4 | D2Coding(코드)·Pretendard(UI) 웹폰트 번들 | 13px 고정 |
| V5 | 창(pane)별 탭, 탭마다 viewState(스크롤·커서) 보존 | |
| V6 | 탭 조작: 가운데 클릭/× 닫기, `Ctrl+W`, `Ctrl+Tab`/`Ctrl+Shift+Tab` | 드래그·고정·컨텍스트 메뉴 없음 |
| V7 | 분할 최대 4창: ▥ 메뉴의 프리셋(1 / 좌우 2 / 좌우 3 / 상하 2 / 2×2), 오른쪽·아래로 분할(`Ctrl+\`·`Ctrl+Alt+\`), 경계 드래그로 크기 조절, 창 닫으면 나머지가 공간 차지. 창마다 탭 따로(번호 표시), `Ctrl+1~4`·`Ctrl+Alt+방향키`로 창 이동, `Ctrl+Alt+PgDn/PgUp`·탭 드래그(Ctrl: 복제)·탭 우클릭(분할·이동·복제)으로 탭 옮기기. 레이아웃·크기는 재시작 시 복원 | 같은 파일은 모든 창이 모델 하나를 공유(수정 표시·저장도 하나). `Ctrl+Alt+↑/↓`는 그 방향에 창이 없으면 Monaco 커서 추가 |
| V8 | 인코딩 자동 판별 BOM(utf-8/utf-16) → utf-8 → cp949 → latin-1 | 상태 표시줄에 표시, 저장 시 원래 인코딩·BOM·EOL 유지 |
| V9 | `max_file_bytes`(기본 2MB) 초과 시 앞부분만 읽고 토스트 표시 | 읽기 전용(서버도 저장 거부) |
| V10 | 검색 결과에서 열면 해당 줄의 매치를 선택하고 나머지 매치는 강조 | 검색 옵션(대소문자·단어·정규식)을 그대로 적용 |
| V11 | 파일 내 찾기 `Ctrl+F`·바꾸기 `Ctrl+H`(Monaco 기본 기능) | 바꾸기는 편집 모드에서 |
| V12 | 토스트 알림(오류·진행 상태) | |
| V15 | 툴바 정리: 파일(새 파일·열기) / 검색(파일에서 찾기) / 보기(편집 모드·레이아웃·줄바꿈) / 설정(테마·설정) 그룹, 구분선, 같은 크기·같은 활성 표시, 툴팁에 이름+단축키(명령 레지스트리), 좁은 창에서는 라벨→그룹 순으로 접고 ⋯ 메뉴로 | "파일로 이동" 버튼은 타이틀바 검색 상자(Ctrl+P)와 중복이라 제거. 2026-10-16: 파일에서 찾기 버튼은 타이틀바 검색으로 옮겼다(`%` 모드). 설정(톱니)은 왼쪽 도구 스트립 맨 아래로 옮겼다. Git 그룹은 브랜치·↑↓·Pull·Commit/Push(AgentO 요청)로 구성된다(GIT-DESIGN §14). 2026-10-21: 브랜치 칩을 누르면 브랜치 팝업(검색, Local/Remote, 고르면 checkout, Pull·Fetch)이 열린다(§14.4). 브레드크럼에서는 저장소 폴더를 칩으로 표시한다 |
| V16 | 파일 종류별 배지 아이콘(트리·탭, 약 45종, 인라인 문자 배지) · 선언 위에 마우스를 올리면 사용처 수 표시 | |
| V13 | AgentO와 같은 타이틀바: 앱 아이콘·제목, 메뉴(File/Edit/View/Go/Window/Help, 하위 메뉴·체크 표시·단축키 표시), 가운데 검색 상자, 최소화/최대화/닫기(Windows 11 모양). Windows 기본 캡션은 숨기되 크기 조절 프레임·캡션 스타일은 유지 → 드래그 이동·Aero Snap·Win+방향키·더블클릭 최대화·가장자리/모서리 크기 조절·최소화/최대화 애니메이션·그림자 그대로 | `WM_NCCALCSIZE`로 비클라이언트 영역 제거, 이동·크기 조절은 페이지가 `WM_NCLBUTTONDOWN`(HTCAPTION/HTLEFT…)으로 Windows 루프를 시작. 닫기 버튼도 미저장 확인 창을 거침. 테마 색은 페이지 CSS 변수로 자동 일치 |
| V14 | 명령 레지스트리 하나로 메뉴·명령 팔레트·단축키 공유. `Ctrl+Shift+P` 명령 팔레트(퍼지 검색, 최근 실행 우선, 단축키 표시), `Ctrl+P` 파일 찾기(퍼지, 최근 파일 우선, `>` 명령·`#` 전체 심볼·`@` 파일 심볼·`:` 줄) | 브라우저 기본 키(F5·Ctrl+R 새로고침, Ctrl+P 인쇄, Ctrl+U·Ctrl+Shift+I 등)는 막음 |

## 2.3 에디터 (13)

| ID | 기능 | 비고 |
|---|---|---|
| E1 | 편집 가능이 기본(실행할 때마다 ON, 예전 `state.json`의 값은 무시). `Ctrl+Shift+E`·✎ 버튼으로 그 실행 동안만 끄고 켬 | 2MB 초과·바이너리·허용 안 된 확장자·무시 경로는 항상 읽기 전용(사유를 상태 표시줄에 표시) |
| E2 | 탭별 수정 표시(•), 창 제목 ●, 실행 취소로 원상태면 수정 표시 해제 | 분할 창은 같은 파일의 모델을 공유 |
| E3 | `Ctrl+S` 저장: `POST /api/save`(`@write_api` + `resolve_write_path` + `atomic_write`) | `mtime_ns`(문자열) 불일치 시 409 → 덮어쓰기 / 다시 불러오기 / 취소 |
| E4 | 닫을 때 확인: 탭(저장/저장 안 함/취소), 창 닫기(Win32 확인 창), 분할 닫기는 수정된 탭을 남은 창으로 옮김 | |
| E5 | 작업 폴더 밖 파일: 열기 대화상자(`Ctrl+O`), 실행 인자, 드래그앤드롭, 이미 실행 중이면 두 번째 실행이 파일을 넘김 | reado.py의 네이티브 경로로 사용자가 고른 파일만 서버가 허가(`grant_external`, `state.json`에 보관). 페이지는 임의 절대 경로를 읽거나 쓸 수 없음 |
| E6 | 외부 변경 감지: 2.5초 폴링(`POST /api/stat`) + 창 포커스 시 | 수정 없는 탭은 다시 불러오고, 수정된 탭은 표시만 하고 저장 시 충돌 처리. 펼친 트리 폴더도 갱신 |
| E7 | 상태 복원: 열린 탭·분할·커서, 테마, 편집 모드, 줄바꿈, 글꼴 크기, 사이드바 폭, 최근 검색, 최근 파일(`Ctrl+E`) | 서버 `state.json`(config.json 옆) |
| E8 | 상태 표시줄: 줄:열·선택 길이, 들여쓰기, 인코딩(클릭해 저장 인코딩 변경), EOL(클릭해 전환), 언어, 줄바꿈 | |
| E9 | 보기: 줄바꿈 `Alt+Z`, 글꼴 `Ctrl+=`/`-`/`0` | |
| E10 | 새 파일: `Alt+Insert`·`Ctrl+N`·new 버튼·트리 우클릭(폴더 미리 채움) → `POST /api/create` | `resolve_write_path` 경유, `O_EXCL`로 이미 있으면 거부(409), 상위 폴더가 있어야 함 |
| E11 | 여러 파일 일괄 바꾸기: FIF의 replace 입력 → 미리보기(파일별 건수·`-`/`+` 샘플, 체크로 선택) → 확인 창 → 적용 | 미저장 탭의 파일은 제외, 미리보기 뒤 디스크가 바뀐 파일은 건너뜀(`mtime_ns`), 원래 인코딩·BOM·EOL 유지, 정규식은 `$1`·`$&` |
| E12 | Windows "연결 프로그램" 등록/해제(설정 ⚙). HKCU `Software\Classes`의 `ReadO.File` + 각 확장자 `OpenWithProgids` | 관리자 권한 불필요, 기본 프로그램은 바꾸지 않음, 해제 시 추가한 항목만 제거 |
| E13 | 포트 자동 선택: 8766이 사용 중이면 빈 포트. 실행 중인 인스턴스는 `instance.json`의 포트로 찾아 파일을 넘기고 창을 앞으로 | |

## 2.9 컴포넌트 찾아가기 · 시작 화면 (설계 재점검 반영)

| ID | 기능 | 비고 |
|---|---|---|
| K1 | Universal Ctags 심볼 인덱스(`vendor/ctags`, 버전·SHA-256 고정): 백그라운드 전체 생성, ReadO 저장 파일은 즉시·외부 변경은 5분마다 증분 | 2만 3천 파일·47만 심볼 기준 생성 76–130초, 메모리 약 +145MB, 질의 6–22ms |
| K2 | 폴더 전체 심볼 검색 `Ctrl+T`·`Ctrl+Alt+Shift+N`(Quick Open `#`): 접두사·CamelHumps(`FrA`, `osi`)·부분 일치, 종류 필터 | 상태 표시줄에 심볼 수·색인 중 표시 |
| K3 | Monaco provider: 정의·사용처·문서 심볼, 다른 파일 위치는 임시 모델(최대 60개)로 피크 | 다른 파일로 점프하면 ReadO 탭으로 열림 |
| K4 | 시작 화면: 폴더/파일 열기, 최근 폴더·파일, 직접 경로 입력. 상단 📁 버튼으로 폴더 전환 | 폴더 미설정 시 아무 경로도 서비스하지 않음 |
| K6 | 링크 이동(import·include·정의): import 경로 문자열 클릭(어디를 눌러도) → 파일, import한 이름(가져오는 줄·사용처) → 원본 파일의 export 위치(named·default·`export … from`·`export *` 2~3단계 추적), `obj.member()` → 그 파일의 멤버. 일반 클릭은 import 줄에서만, Ctrl+클릭·F12는 어디서나. Ctrl 없이 마우스만 올려도 해석되는 대상(태그·import 경로/이름·색인에 선언이 있는 심볼)만 밑줄+손가락 커서+`파일:줄` 툴팁, 클릭하면 옆 pane에 열림(Alt+클릭=커서만 이동, 더블클릭=단어 선택, 드래그=텍스트 선택, 설정 'Ctrl 없이 링크 열기' 기본 켜짐, 선언 위치 자신·해석 불가 단어는 링크 아님), 패키지·없는 파일은 토스트, 후보 여럿이면 선택 목록. 언어: JS/TS/Vue/Svelte, CSS(@import·url), Java/Kotlin(import·와일드카드·같은 패키지), Python(상대·절대 import), Go(go.mod 모듈 경로), C/C++ `#include`, PHP(require·PSR-4 use), Rust(mod·use crate::), C# using, Ruby require_relative. 다른 파일로의 모든 이동은 다음 pane에 열림(Ctrl+Alt: 같은 pane) | 서버 `/api/link`가 편집 중인 버퍼 기준으로 해석(저장 안 한 import도 반영). 호버·클릭 시에만 계산, 타이핑 중 요청 없음. tsconfig·vite·package.json 별칭은 파일 변경 시각으로 캐시. node_modules·표준 라이브러리는 열지 않음 |
| K5 | 컴포넌트 태그 이동: `.vue .jsx .tsx .svelte .astro`에서 `<ItemTop>`·`</ItemTop>`·`<item-top>`을 F12·Ctrl+B·Ctrl+클릭하거나 그냥 클릭하면 반대쪽 분할 창에 엶(분할 자동 생성, 이미 열려 있으면 활성화). 그냥 클릭은 커서·포커스를 그대로 둠(설정에서 끔). 피크 목록에서 고른 경우도 포함해 컴포넌트 이동은 항상 현재 창의 반대쪽에 열림(설정 '옆 창에 열기', 기본 켜짐). `Ctrl+Alt`+클릭·`Ctrl+Alt+F12`는 같은 창에 엶. `Ctrl+P`·`Ctrl+T`에서 `Ctrl+Enter`는 옆 창에 엶 | 해석: 현재 파일 import(상대 경로, tsconfig/jsconfig `paths`, vite alias, `@/` `~/` 추정) → 파일명(PascalCase·kebab·`Name/index.vue`·Nuxt `components/` 접두) → 근접도 순. 여러 개면 피크/선택 목록, 없으면 토스트. HTML·내장 태그(`router-view` 등)와 제네릭 `ref<Foo>`는 제외 |

## 2.4 검색 — Find in Files (11)

| ID | 기능 | 비고 |
|---|---|---|
| S1 | FIF 모달(`Ctrl+Shift+F`): 결과 목록 + 미리보기 패널 | |
| S2 | 옵션: 대소문자(Aa), 단어 단위(W), 정규식(.*) | |
| S3 | "files to include" glob 입력(`*.java, src/**`) | 비우면 모든 텍스트 파일 |
| S4 | 프로젝트 범위: base_dir 바로 아래 폴더 드롭다운(`/api/projects`) | |
| S5 | 컨텍스트 줄 수 0–10 | |
| S6 | 키보드 탐색(↑↓/Enter/Esc) | |
| S7 | 최근 검색 15개(datalist) | 서버 `state.json`에 저장 |
| S8 | 진행 중 요청 Abort + 늦게 도착한 응답 무시 | |
| S9 | ripgrep 우선 사용(`--json`, 파일당 100건, 5MB 상한, 타임아웃 60s) | PATH에 rg가 있을 때만 |
| S10 | Python 폴백: 32 스레드 병렬 + 콘텐츠 캐시(mtime 기준, 5,000개) | |
| S11 | 파일 인덱스 캐시(60s 또는 base_dir 변경 시 재구축), Quick Open·심볼·폴백 공용 | |

## 2.5 렌더링 (2)

| ID | 기능 | 비고 |
|---|---|---|
| R1 | `.md` 파일은 marked로 HTML 미리보기(Pretendard 본문 스타일) | 소스 ⇄ 미리보기 전환, allowlist sanitize, 상대 링크는 파일로 열기 |
| R2 | 미리보기 테마가 라이트/다크를 따라감 | 코드 블록 하이라이트·상대 경로 이미지·mermaid 없음 |

## 2.6 서버 API (9)

| ID | 엔드포인트 | 역할 |
|---|---|---|
| A1 | `GET /`, `/source.html` | SPA 서빙 |
| A2 | `GET /api/settings` | 설정 + `first_run` + `base_dir_exists` |
| A3 | `POST /api/settings` | 저장 후 인덱스 캐시 무효화 |
| A4 | `GET /api/tree?path=` | 1단계 목록, `_safe_join`으로 경로 이탈 차단 |
| A5 | `GET /api/file?path=` | 본문 + size·truncated·encoding |
| A6 | `GET /api/search?q&case&regex&word&scope&glob&ctx` | FIF |
| A7 | `GET /api/goto?symbol&scope` | 선언 후보(선언 먼저, 최대 200건 스캔) |
| A8 | `GET /api/files?q&offset&limit` / `GET /api/projects` | Quick Open / 범위 목록 |
| A9 | `GET /vendor/*` | MIME 화이트리스트, 경로 이탈 차단, immutable 캐시 |

## 2.7 설정 (5)

| ID | 기능 | 비고 |
|---|---|---|
| C1 | config.json 위치: exe는 `%APPDATA%\ReadO`, 소스 실행은 repo 폴더 | 미커밋 변경 |
| C2 | 예전 exe 옆 config.json을 1회 마이그레이션 | 미커밋 변경 |
| C3 | 첫 실행이거나 base_dir가 없으면 설정 모달 자동 열림, 기본값 파일 생성 | |
| C4 | 설정 모달: base_dir(📁 폴더 선택 대화상자), ignored, extensions, 단축키 표 | `max_file_bytes`·`search_max_results`는 파일로만 수정 가능 |
| C5 | 저장하면 트리·프로젝트 목록 다시 로드 | |

## 2.8 빌드 / 배포 (3)

| ID | 기능 | 비고 |
|---|---|---|
| B1 | `build.bat`: PyInstaller `--onefile --windowed`, 아이콘, 매번 build·dist·spec 정리 | |
| B2 | `fetch-vendor.py`: Monaco 0.45.0 / marked 12.0.0 / Pretendard v1.3.9 / D2Coding 버전 고정, stdlib만 사용 | vendor는 커밋하지 않음 |
| B3 | 완전 오프라인 실행(CDN 의존 없음) | |

---

<a id="cat-3"></a>

# <span class="num">3</span> 갭 리스트 <span class="hctl"><a href="#toc">↑ 목차로</a></span>

> 우선순위는 상/중/하, 난이도는 하(반나절 이하)·중(1–3일)·상(3일 이상). 파일명은 `r`=reado.py, `s`=server.py, `h`=source.html로 줄여 썼다.

## 3.1 우선순위 상

| ID | 갭 | 구분 | 난이도 | 영향 파일 | 상태 |
|---|---|---|---|---|---|
| G1 | **편집·저장 불가**: readOnly 해제, `POST /api/file`(mtime 충돌 검사·원래 인코딩/EOL 유지), 수정 표시(●), `Ctrl+S`, 닫을 때 저장 확인 | 누락 | 중 | h, s | 해결 |
| G2 | **base_dir 밖 파일을 열 수 없음**: 파일 열기 대화상자·CLI 인자(`reado.exe file.txt`)·드래그앤드롭·탐색기 연결 프로그램 등록 없음. Notepad++ 대체의 전제 조건 | 누락 | 중 | r, s, h, build.bat | 해결 |
| G3 | **FIF 확장자 칩 하드코딩 버그**: 칩 5개가 기본 체크라 `.kt .py .md .sql .yml .xml .properties` 등이 기본 검색에서 **빠진다**. 설정의 extensions와 연동해야 함 | 버그 | 하 | h | 해결 |
| G4 | **상태가 유지되지 않음**: pywebview는 `private_mode` 기본값이 True라 재시작하면 localStorage(테마·최근 검색)가 지워짐(pywebview 6.2.1 소스로 확인. 기본값은 그대로 두고 상태를 서버 `state.json`에 저장). 열린 탭·분할·사이드바 폭 복원과 최근 파일 목록도 없음 | 버그+누락 | 하–중 | r(`storage_path`/`private_mode=False`), h | 해결 |
| G5 | **외부 변경 미반영**: 트리 새로고침 없음, 열린 탭이 갱신되지 않음(편집을 넣으면 덮어쓰기 위험) | 누락 | 중 | s, h | 해결 |
| G6 | **상태 표시줄 없음**: 줄:열, 선택 길이, 인코딩, EOL, 언어, 들여쓰기 | 누락 | 하 | h | 해결 |
| G7 | **보기 옵션 토글 없음**: 줄바꿈(`Alt+Z`), 미니맵, 글꼴 크기 확대(`Ctrl+±`/휠), 공백 표시 | 누락 | 하 | h | 해결 — 줄바꿈·글꼴 크기·미니맵·공백 표시 토글(보기 메뉴·팔레트) |
| G8 | **내비게이션 히스토리 없음**: 정의로 이동한 뒤 뒤로/앞으로(`Alt+←/→`) 불가 | 누락 | 하 | h | 해결 |

## 3.2 우선순위 중

| ID | 갭 | 구분 | 난이도 | 영향 파일 | 상태 |
|---|---|---|---|---|---|
| G9 | 찾아 바꾸기: 파일 내(G1 전제), 여러 파일 일괄 바꾸기 + 미리보기 | 누락 | 중–상 | h, s | 해결 |
| G10 | 파일 조작: 새 파일·폴더, 이름 변경, 삭제, 경로 복사, 탐색기에서 열기(트리 컨텍스트 메뉴) | 누락 | 중 | s, h, r | 해결 — 트리 우클릭/F2/Delete: 새 파일·폴더, 이름 변경(열린 탭 따라감), 삭제(휴지통 우선·확인), 경로 복사, 탐색기에서 보기 |
| G11 | Markdown: 소스↔미리보기 토글 또는 나란히 보기, 코드 블록 하이라이트, 상대 경로 이미지·링크(이미지 서빙 API 필요), **HTML sanitize** | 불완전 | 중 | h, s | 해결 — 코드 블록 하이라이트(Monaco colorize), 상대 경로 이미지(`/api/image`, 연 폴더 안만), sanitize 유지 |
| G12 | 검색 엔진 결과 불일치: rg는 `.gitignore`를 따르고 utf-8만 읽으며 확장자 없는 파일을 빼지만, 폴백은 반대. 요약의 `files`도 rg는 "매치된 파일 수", 폴백은 "스캔한 파일 수" | 버그 | 하 | s | 해결 — rg·폴백 같은 규칙 + 선택 옵션 ".gitignore 반영"(트리·Quick Open·심볼·검색 공통) |
| G13 | `goto_symbol` 성능: 매번 인덱스 전체 파일을 Python으로 읽음(rg 미사용) → 큰 모노레포에서 느림 | 불완전 | 하 | s | 해결(2단계 A) |
| G14 | 로컬 서버 보안: Host·Origin 검사 없음. POST가 Content-Type을 확인하지 않아 CSRF로 base_dir 변경 가능, DNS rebinding으로 소스 읽기 가능. 쓰기 API(G1)를 넣기 전에 필수 | 위험 | 하–중 | s | 해결(2단계 A) |
| G15 | 포트 8766 고정: 다른 프로세스가 쓰고 있으면 실패하거나 기존 인스턴스에 붙음. 동적 포트 또는 단일 인스턴스 처리 필요 | 불완전 | 하 | r | 해결 |
| G16 | 설정 UI 누락 항목: `max_file_bytes`, `search_max_results`, 글꼴·크기, 탭 크기. 절단 토스트의 "2 MB" 문구가 하드코딩 | 불완전 | 하 | h | 해결 — 파일 크기 상한(MB)·검색 결과 수 설정 추가 |
| G17 | Quick Open이 퍼지(약어 `UsrCtl`) 매칭이 아님. 단축키 표의 "fuzzy" 표기와 다름. 최근 연 파일 우선 순위도 없음 | 불완전 | 하 | s, h | 해결 — 퍼지 매칭 + 최근 파일 우선 |
| G18 | 커맨드 팔레트(`Ctrl+Shift+P`)·단축키 사용자 정의 없음. 기존 단축키는 document keydown에 하드코딩 | 누락 | 중 | h | 해결 — 명령 팔레트(Ctrl+Shift+P) + 키맵 프리셋(VS Code / IntelliJ, 충돌 검사) |
## 3.3 우선순위 하

| ID | 갭 | 구분 | 난이도 | 영향 파일 | 상태 |
|---|---|---|---|---|---|
| G19 | 탭 UX: 드래그 정렬, 고정, 미리보기 탭, "다른 탭/모두 닫기" 메뉴, 반대쪽 창으로 이동 | 누락 | 중 | h | 대부분 해결 — 드래그 정렬·다른 창으로 이동/복제·다른 탭/오른쪽/모두 닫기. 탭 고정·미리보기 탭은 미구현 |
| G20 | 분할 확장: 3창 이상, 세로 분할, 두 파일 diff 보기 | 누락 | 중 | h | 해결 — 최대 4창·프리셋, diff(저장본/Git HEAD/다른 파일과 비교) |
| G21 | 멀티 루트 워크스페이스(base_dir 여러 개) | 누락 | 중 | s, h | 미해결 — 구조 변경이 커서 보류(폴더 전환·최근 폴더로 대체) |
| G22 | 인코딩·EOL 수동 선택/다른 인코딩으로 다시 열기, BOM 처리 | 누락 | 하 | s, h | 해결 — 다른 인코딩으로 다시 열기(UTF-8·CP949·UTF-16LE·Latin-1) + 저장 인코딩 변경 |
| G23 | 트리 내 필터·접기 전체·파일 아이콘 다양화 | 누락 | 하 | h | 대부분 해결 — 파일 종류 배지 아이콘, 모두 접기. 트리 내 필터 입력은 미구현(Quick Open으로 대체) |
| G24 | Git 연동(변경 표시, blame, diff) | 누락 | 상 | s, h | 해결(보기 전용) — Git 도구창(Local Changes·Log 그래프/필터/브랜치 트리·History·Stash·Console), blame, 거터·트리 색·상태바, diff. 커밋·푸시 등 쓰기는 AgentO 지시문으로 넘김(`docs/GIT-DESIGN.md`) |
| G25 | 품질 기반: 테스트·버전 표기·CI·코드 서명/설치본 없음 | 누락 | 중 | 신규 | 일부 — 버전 표기(정보 창), 헤드리스·exe 스모크 테스트. CI·코드 서명·설치본은 미구현 |
---

<a id="cat-4"></a>

# <span class="num">4</span> 불필요·중복·죽은 코드 <span class="hctl"><a href="#toc">↑ 목차로</a></span>

> 동작에는 영향이 없지만 정리할 대상이다. 행동이 달라지는 항목(G3·G12)은 갭 리스트에 넣었다.

| # | 위치 | 내용 | 분류 |
|---|---|---|---|
| D1 | `server.py:read_file` | latin-1은 디코딩이 실패하지 않으므로 마지막 `errors="replace"` 분기와 `"encoding": "replace"`에 도달할 수 없음 | 죽은 코드 |
| D2 | `source.html` `let _activeMatch` | 선언만 있고 쓰이지 않음 | 죽은 코드 |
| D3 | `source.html` `.search-bar` CSS(약 15줄, 다크 테마 포함) | 해당 요소가 없음. 예전 인라인 검색바의 흔적 | 죽은 코드 |
| D4 | `source.html` `switchTab()` | "older callers"용 별칭인데 호출하는 곳이 없음(`closeTab`은 `Ctrl+W`가 사용) | 죽은 코드 |
| D5 | `requirements.txt` `Pillow` | 저장소 안에 PIL을 쓰는 코드가 없음(아이콘 생성 스크립트도 없음) | 불필요 |
| D6 | `reado.spec`(로컬) | `*.spec`은 gitignore 대상이고 build.bat이 매번 지우고 다시 만듦 | 불필요 |
| D7 | `reado.py:serve` ↔ `server.py:serve` | 같은 기동 코드가 두 곳에 있음 | 중복 |
| D8 | `server.py` 모듈 로드 시 `SETTINGS`·`_first_run` | import할 때 repo 경로 기준으로 한 번 계산하고, reado.py가 다시 계산해서 덮어씀 | 중복 |
| D9 | 선언 탐지 정규식 | 서버 `goto_symbol.decl_pat`과 클라이언트 `symbolPatterns()`가 비슷한 규칙을 따로 유지 | 중복 |
| D10 | `goto_symbol` ↔ `find_in_files` | scope prefix 계산과 인덱스 순회 코드가 같음 | 중복 |
| D11 | `DEFAULT_SETTINGS.base_dir = c:\Projects` | 특정 PC 경로가 기본값. 빈 값 + 첫 실행 모달이 맞음 | 부적절 |
| D12 | `server.py` 중간 import(`fnmatch`, `ThreadPoolExecutor`, `shutil`) | 파일 상단으로 모아야 함 | 정리 |
| D13 | `README.md` | config 위치 설명이 "exe 옆"으로 남아 있음(C1과 다름). 상단의 doc-standard `<style>`·radio는 GitHub에서 렌더링되지 않음 | 문서 |

---

<a id="cat-5"></a>

# <span class="num">5</span> 권장 착수 순서 <span class="hctl"><a href="#toc">↑ 목차로</a></span>

> 버그와 작은 작업을 먼저 끝내고, 편집 기능은 보안 보강 다음에 넣는다.

<div class="lay">
 <div class="cd" style="border-top-color:#82b366"><b><span class="st">1</span> 빠른 수정</b><span class="s">G3 확장자 칩, G4 저장소 유지, G12 검색 일관성, G6·G7 상태줄·보기 토글, D1–D5 정리</span></div>
 <div class="ar">→</div>
 <div class="cd" style="border-top-color:#d6b656"><b><span class="st">2</span> 보안·기반</b><span class="s">G14 Host/Origin·CSRF, G15 포트, G5 변경 감지, G8 내비게이션 히스토리</span></div>
 <div class="ar">→</div>
 <div class="cd" style="border-top-color:#b85450"><b><span class="st">3</span> 에디터화</b><span class="s">G1 편집·저장, G2 외부 파일 열기, G9 찾아 바꾸기, G10 파일 조작</span></div>
 <div class="ar">→</div>
 <div class="cd" style="border-top-color:#6c8ebf"><b><span class="st">4</span> 편의</b><span class="s">G11 Markdown, G18 커맨드 팔레트, G16·G17, 탭·분할 확장</span></div>
</div>
