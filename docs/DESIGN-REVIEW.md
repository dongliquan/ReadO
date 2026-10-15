# ReadO 설계 재점검

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

**대상**: 작업 트리 현재 상태(미커밋 변경 포함). `server.py` 1,912줄 · `source.html` 2,826줄 · `reado.py` 362줄  
**의도(매니저)**: 특정 프로젝트용이 아닌 **일반 프로그램**. VS Code/IntelliJ의 필수 기능만 담은 가벼운 소스 뷰어·에디터. **가장 중요한 기능은 컴포넌트 찾아가기**. 기본은 파일 보기이고 **text 계열 파일은 바로 수정** 가능해야 한다.  
**반영 상태(2026-10-12)**: §6 권고 1–4단계를 구현했다. 각 표의 "상태" 열에 반영했고, 나머지 본문은 검토 시점 기준이다.
**범위**: 검토 당시에는 문서만 작성했다. `docs/FEATURES.md` 작성 이후 편집·저장, 외부 파일 열기, 뒤로/앞으로, 상태바, 보안 가드가 추가되었고 이 문서는 그 상태를 기준으로 했다.

<a id="toc"></a>

## 목차

- [**1. 의도 대비 적합성 평가**](#cat-1)
- [**2. 일반화 항목**](#cat-2)
- [**3. 컴포넌트 찾아가기**](#cat-3) — 현재 수준 · 방식 비교 · 로드맵
- [**4. 텍스트 파일 편집 · 첫 실행 경험**](#cat-4)
- [**5. 기능 범위 선**](#cat-5) — 가져올 것 vs 뺄 것
- [**6. 최종 권고안**](#cat-6)

---

<a id="cat-1"></a>

# <span class="num">1</span> 의도 대비 적합성 평가 <span class="hctl"><a href="#toc">↑ 목차로</a></span>

> 종합하면 **"부분 일치"**다. 뼈대(가벼운 데스크톱 + Monaco + 편집·저장)는 의도와 맞지만, 가장 중요한 축인 컴포넌트 찾아가기가 가장 약하고 기본값과 파일 판별이 특정 환경(Java/웹 모노레포, `C:\Projects`)에 묶여 있다.

| 의도 | 평가 | 근거 |
|---|---|---|
| 일반 프로그램 | <b style="color:#c0392b">미흡</b> | 기본 base_dir `c:\Projects`. 확장자 allowlist 20개가 Java/웹 중심. 무시 폴더에 `doc`·`static`·`gradle` 포함. 검색 "프로젝트 범위"가 base_dir 1단계 폴더(모노레포 가정) |
| 가볍다 | <b style="color:#27ae60">적합</b> | pywebview + stdlib 서버, 오프라인 번들(Monaco 약 13MB + rg), 설치 불필요 |
| **컴포넌트 찾아가기(최우선)** | <b style="color:#c0392b">미흡</b> | 정의 이동이 **텍스트 검색 + 범용 정규식 1개** 수준. 워크스페이스 심볼 검색·사용처 찾기·아웃라인 패널이 없다(§3) |
| 기본 동작은 파일 보기 | <b style="color:#27ae60">적합</b> | 트리·탭·분할·Quick Open·세션 복원 |
| text 계열 즉시 수정 | <b style="color:#d68910">부분</b> | 시작할 때부터 편집 모드이고 `Ctrl+S`로 저장, mtime 충돌 검사, 인코딩·EOL 유지는 된다. 하지만 **확장자 allowlist 밖 파일(.txt .sh .toml .ini .csv .log …)은 base_dir 안에서 트리에 보이지 않고 저장도 거부**된다(§4) |

### 가장 큰 어긋남 3가지

| # | 어긋남 | 영향 |
|---|---|---|
| <span class="cn">1</span> | 컴포넌트 찾아가기가 grep 수준. 정의가 2개 이상이면 FIF 검색창으로 넘어가고, 사용처 찾기와 `Ctrl+T` 심볼 검색이 없다 | 핵심 가치가 IntelliJ 대비 가장 크게 뒤처짐 |
| <span class="cn">2</span> | "텍스트 파일"을 **확장자 allowlist**로 판정한다. base_dir 안 `notes.txt`는 보이지도 저장되지도 않는데, base_dir 밖에서 `Ctrl+O`로 열면 같은 파일이 편집된다 | "txt 바로 수정" 위반, 기준이 일관되지 않음 |
| <span class="cn">3</span> | 기본값이 특정 PC·조직용이다: `C:\Projects`, `doc`·`static` 숨김, `.*` 전부 숨김(`.env`·`.gitignore`·`.github` 접근 불가) | 처음 쓰는 사용자의 폴더가 비어 보이거나 문서 폴더가 사라짐 |

---

<a id="cat-2"></a>

# <span class="num">2</span> 일반화 항목 <span class="hctl"><a href="#toc">↑ 목차로</a></span>

> 하드코딩된 값과 특정 언어 편향을 위치별로 정리했다. 파일명은 `s`=server.py, `h`=source.html, `r`=reado.py로 줄여 썼다.

| ID | 위치 | 현재 | 일반화 제안 | 우선 | 난이도 | 상태 |
|---|---|---|---|---|---|---|
| U1 | `s` `DEFAULT_SETTINGS.base_dir` | `c:\Projects` | 빈 값. 첫 실행 시 "폴더 열기" 화면(§4.2) | 상 | 하 | 해결 — 시작 화면(폴더/파일 열기, 최근 폴더), 선택 폴더 기억 |
| U2 | `s` `DEFAULT_SETTINGS.extensions` | Java/웹 중심 20개를 **허용 목록**으로 사용 | 허용 목록 대신 **내용 기반 판별 + 바이너리 확장자 차단 목록**(§4.1) | 상 | 중 | 해결 — 내용 판별 + 바이너리 확장자 차단 목록 |
| U3 | `s` `DEFAULT_SETTINGS.ignored` | `doc`, `static`, `gradle`, `bin`, `logs`, `.*` | 일반 기본값 `.git .svn .hg node_modules __pycache__ .venv venv`로 축소. 빌드 산출물(`build dist target out`)은 "검색에서만 제외"로 분리. `.gitignore` 존중 옵션 | 상 | 하 | 해결 — 기본 무시 축소, `search_ignored` 분리. 옛 기본값 config는 자동 이전. `.gitignore` 존중 옵션은 없음 |
| U4 | `s` `/api/projects`, `h` FIF 범위 | base_dir 1단계 폴더 = "프로젝트" | "현재 폴더 / 열린 파일의 폴더 / 전체" 범위, 또는 트리에서 선택한 폴더 | 중 | 하 | 해결 — 전체 / 현재 파일의 폴더 / 하위 폴더 |
| U5 | `h` `langFor()` | 확장자 약 40개 하드코딩 | `monaco.languages.getLanguages()`의 extensions·filenames로 자동 매핑(약 80개 언어) + 사용자 오버라이드 | 중 | 하 | 해결 — Monaco 언어 등록표 사용(일부 수동 매핑 우선) |
| U6 | `h` `symbolPatterns()` / `s` `_goto_patterns()` | Java·Kotlin·JS 중심, C/C++/C#/PHP/Swift/SQL 없음 | §3의 ctags 도입으로 대체 | 상 | 중 | 해결 — ctags 인덱스 + 언어별 선언 패턴 폴백 |
| U7 | `h` `iconFor()` | ☕ Java가 첫 규칙, 언어 11종 | 언어 ID 기반 아이콘 표(U5와 같이) | 하 | 하 | 해결 — 파일 종류 배지(약 45종) |
| U8 | `s` `max_file_bytes` 2MB | 2MB를 넘으면 앞부분만 보여 주고 읽기 전용 | 편집 상한 10–20MB, 그 이상은 읽기 전용 + 경고(§4.1) | 중 | 하 | 유지 — 2MB 유지(매니저 지시), 읽기 전용 배너로 안내 |
| U9 | `r` `EXTRA_ASSOC_EXTS` | `.txt .log .ini .cfg .csv`만 "연결 프로그램"에 추가 | U2의 판별 기준과 통일 | 하 | 하 | 해결 — 일반 텍스트 확장자 목록으로 통일 |
| U10 | 설정 UI·README | "Base Directory" 용어, 단축키 표가 IntelliJ 키(`Ctrl+B`, `Ctrl+Shift+N`) 중심 | "작업 폴더" 용어. VS Code·IntelliJ 키맵 프리셋 중 선택 | 하 | 중 | 일부 — '작업 폴더' 용어. 키맵 프리셋은 없음(VS Code·IntelliJ 키를 함께 지원) |

---

<a id="cat-3"></a>

# <span class="num">3</span> 컴포넌트 찾아가기 <span class="hctl"><a href="#toc">↑ 목차로</a></span>

> 지금은 "커서 단어로 rg `-w` 검색 → 선언처럼 보이는 줄을 범용 정규식 하나로 골라냄"이다. 의미 분석은 없다.

## 3.1 현재 수준 vs IntelliJ / VS Code

| 기능 | IntelliJ / VS Code | ReadO 현재 | 갭 |
|---|---|---|---|
| 정의로 이동 `Ctrl+B`/`F12` | 의미 분석, 정확히 1곳 | rg 단어 검색 + 정규식. 결과가 1건이면 이동하고, 여러 건이면 **FIF 모달로 넘어감**. base_dir 전체를 검색하고 현재 프로젝트를 우선하지 않음 | 큼 |
| 선언 판정 정확도 | — | 범용 정규식이 `return foo(`, `new Foo(`도 "메서드 선언"으로 잡음(오탐). Go 리시버 메서드 `func (r *T) Foo(`는 놓침 | 큼 |
| Ctrl+클릭 / 피크 | 있음 | Monaco provider를 등록하지 않아 **없음** | 큼 |
| 심볼 검색 `Ctrl+T` / `Ctrl+Alt+Shift+N` | 있음 | **없음**(Quick Open `@`는 현재 파일만) | 큼 |
| 클래스 검색 `Ctrl+N` | 있음 | 파일명 검색(`Ctrl+P`)으로 대체. 클래스명이 파일명과 같을 때만 통함 | 중 |
| 사용처 찾기 `Shift+F12` / `Alt+F7` | 있음 | **없음**(FIF로 직접 검색해야 함) | 큼 |
| 파일 내 아웃라인 | 사이드 패널 + 브레드크럼 | `Ctrl+Shift+O` 모달(언어 8종 정규식)만 있음. 패널 없음 | 중 |
| 뒤로/앞으로 `Alt+←/→` | 있음 | **있음**(50단계) | 없음 |
| 호출·타입 계층, 리네임 리팩터링 | 있음 | 없음 | 범위 밖(§5) |

## 3.2 가벼운 접근 방식 비교

| 방식 | 정확도 | 언어 범위 | 번들 증가 | 속도 | 런타임 의존 | 평가 |
|---|---|---|---|---|---|---|
| 정규식 규칙(현행 보강) | 낮음–중 | 규칙을 직접 쓴 언어만 | 0 | 즉시 | 없음 | 단기 보완용 |
| **Universal Ctags**(rg처럼 exe 번들) | 중–상(선언 위치는 정확, 참조는 없음) | 150개 이상 | 약 5MB 내외(추정) | 전체 인덱스는 백그라운드, 저장 시 파일 단위 증분 | 없음(단일 exe) | **권장 1순위** |
| tree-sitter(web-tree-sitter WASM) | 상(파일 내 구조) | 문법 파일을 넣은 언어만 | 코어 약 0.2MB + 문법당 약 0.5–3MB | 파일 단위로 빠름. 파일 간 인덱스는 직접 구현 | 없음 | 아웃라인·하이라이트 정밀화에 2단계로 검토 |
| LSP(jdtls, tsserver, pyright …) | 최상 | 서버가 있는 언어만 | 언어별 수십–수백 MB + JDK/Node | 첫 인덱싱 느림, 메모리 큼 | JDK/Node | 번들 금지. "PATH에 있으면 사용" 선택 기능으로만 |
| Monaco 내장 TS/JS 서비스 | 상(JS/TS) | JS/TS만 | 0(이미 번들됨) | 빠름 | 없음 | JS/TS 한정 보너스. 파일 간 이동에는 모델 등록 필요 |

<div class="tip">ctags로 "어디에 선언됐나"를 정확히 알고, rg로 "어디서 쓰이나"를 빠르게 찾는다. 두 exe를 합치는 조합이 LSP 없이 IntelliJ 체감의 70–80%에 이르는 가장 가벼운 길이다(추정).</div>

## 3.3 로드맵

| 단계 | 항목 | 내용 | 우선 | 난이도 | 영향 파일 | 상태 |
|---|---|---|---|---|---|---|
| <span class="st">1</span> | Monaco provider 연결 | `registerDefinitionProvider` / `ReferenceProvider` / `DocumentSymbolProvider`를 `/api/goto` 등에 연결 → Ctrl+클릭, 피크 창, 브레드크럼 심볼을 Monaco 기본 UI로 얻음 | 상 | 하 | h | 해결 |
| <span class="st">1</span> | 사용처 찾기 | `Shift+F12`/`Alt+F7`: rg `-w -s`로 찾고 선언 줄을 빼서 피크/결과 패널로 표시(FIF 렌더러 재사용) | 상 | 하 | s(`/api/refs`), h | 해결 |
| <span class="st">1</span> | 정의 랭킹·오탐 수정 | `return/new/throw/await` 다음은 선언에서 제외. 같은 프로젝트·파일명=심볼·import 경로를 우선. 여러 건이면 FIF 대신 **후보 피크 목록** | 상 | 하 | s, h | 해결 — 여러 건이면 Monaco 피크 목록 |
| <span class="st">2</span> | ctags 번들 + 심볼 인덱스 | `fetch-vendor.py`로 받아 rg처럼 번들. 백그라운드로 전체 인덱스 생성, `notify_file_changed`·폴링 때 파일 단위 갱신. JSON 출력 → 메모리 인덱스 | 상 | 중 | s, fetch-vendor.py, build.bat | 해결 — Universal Ctags p6.2.20260920.0 번들, 증분 갱신 |
| <span class="st">2</span> | 워크스페이스 심볼 검색 | `Ctrl+T`(VS Code)·`Ctrl+Alt+Shift+N`(IntelliJ) + 클래스 전용 `Ctrl+N`. Quick Open `#` 모드로 구현 | 상 | 하(ctags 이후) | s(`/api/symbols`), h | 해결 — `Ctrl+T`·`Ctrl+Alt+Shift+N`, 종류 필터(클래스/메서드/필드). `Ctrl+N`은 새 파일로 유지 |
| <span class="st">2</span> | 정의 이동을 ctags 우선으로 | 인덱스가 있으면 ctags, 없거나 만드는 중이면 현행 rg+정규식으로 폴백 | 상 | 하 | s | 해결 |
| <span class="st">3</span> | 아웃라인 패널 | 사이드바 탭(파일 트리 / 아웃라인). 데이터는 ctags 파일 단위 실행 또는 DocumentSymbolProvider | 중 | 중 | h, s | 해결 — 사이드바 outline 탭 + `Ctrl+Shift+O` |
| <span class="st">3</span> | 경량 상호 참조 | 정의 줄 hover에 "참조 N건" 표시(rg count), 파일 상단 import 클릭으로 이동 | 하 | 중 | h, s | 해결 — 선언 hover에 사용처 수, import·정의 링크(Ctrl 없이) |
| <span class="st">4</span> | LSP 선택 연동 | 설정에서 언어별 서버 명령을 지정한 경우에만 사용(기본 끔) | 하 | 상 | s, h | 미해결 — 보류(ctags·링크 해석으로 대부분 대체) |
---

<a id="cat-4"></a>

# <span class="num">4</span> 텍스트 파일 편집 · 첫 실행 경험 <span class="hctl"><a href="#toc">↑ 목차로</a></span>

> 편집 엔진(저장·충돌·인코딩)은 갖춰졌다. 막히는 지점은 "어떤 파일을 텍스트로 볼 것인가"라는 판정 규칙과 첫 화면이다.

## 4.1 텍스트 판별 기준

| 항목 | 현재 | 문제 | 개선안 |
|---|---|---|---|
| 판별 방식 | 확장자 **허용 목록**(트리·인덱스·검색·저장·새 파일 공통) | 목록 밖 텍스트 파일이 안 보이고 저장도 거부됨("file extension not allowed") | **내용 판별**: 앞 8KB에 NUL이 있거나 비텍스트 바이트 비율이 30% 이상이면 바이너리. 확장자 목록은 **차단 목록**(`.exe .dll .png .jpg .zip .jar .class .pdf …`)으로만 사용 |
| 확장자 없는 파일 | 항상 허용 | 바이너리가 섞일 수 있지만 열 때 NUL 검사로 막힘 | 현행 유지 + 내용 판별 |
| base_dir 안/밖 기준 | 안: 확장자 검사함. 밖(`Ctrl+O`, 드롭, CLI): 확장자 검사 안 함 | 같은 파일이 위치에 따라 편집 가능 여부가 달라짐 | 한 가지 규칙(내용 판별)으로 통일 |
| dot 파일 | `.*` 무시 규칙 때문에 트리·저장 모두 불가 | `.env`, `.gitignore`, `.editorconfig`를 편집할 수 없음 | `.git`만 숨기고 나머지 dot 파일은 표시(토글) |
| 인코딩 | BOM → utf-8 → cp949 → latin-1. 저장 시 원래 인코딩 유지, UTF-8/BOM/CP949로 변경 가능 | BOM 없는 UTF-16은 NUL 때문에 바이너리로 판정됨 | 짝수/홀수 바이트 NUL 패턴으로 UTF-16LE/BE 추정 |
| 대용량 | 2MB를 넘으면 앞부분만 보여 주고 읽기 전용 | 로그·덤프 파일은 흔히 2MB를 넘음 | 편집 상한 10–20MB(Monaco는 이 정도까지 무난). 그 이상은 읽기 전용 + "전체 열기" 버튼 |
| 열 수 없을 때 | 토스트 + 상태바에 읽기 전용 사유 | 바이너리는 내용이 깨진 채로 표시됨 | 바이너리는 "열 수 없음 · 크기 · 시스템 앱으로 열기" 안내 화면 |
| 편집 모드 | 시작할 때마다 켜짐(`Ctrl+Shift+E`로 끔) | 없음 | 현행 유지 |

## 4.2 첫 실행 경험

| 단계 | 현재 | 개선안 |
|---|---|---|
| 첫 화면 | base_dir가 없으면 설정 모달이 자동으로 열림(필드 3개 + 단축키 표) | **시작 화면**: [폴더 열기] [파일 열기] [최근 폴더/파일] + 단축키 3–4개 |
| 작업 폴더 변경 | 설정 모달 → 📁 버튼 → 저장 | 상단 바 폴더 이름 클릭 또는 `Ctrl+K Ctrl+O`로 "폴더 열기". 최근 폴더 목록 |
| 파일 하나만 열기 | `Ctrl+O`, 드래그앤드롭, CLI 인자, 연결 프로그램 — **충족** | 폴더 없이 파일만 연 상태(트리 숨김)도 정상 흐름으로 지원 |
| 탐색기 연결 | 설정에서 HKCU "연결 프로그램" 등록 — **충족** | 판별 기준(U2)과 확장자 목록 통일 |

---

<a id="cat-5"></a>

# <span class="num">5</span> 기능 범위 선 — VS Code / IntelliJ에서 가져올 것 vs 뺄 것 <span class="hctl"><a href="#toc">↑ 목차로</a></span>

> 기준은 "소스를 읽고, 찾아가고, 가볍게 고친다"다. 빌드·실행·의미 분석이 필요한 기능은 넣지 않는다.

| 영역 | 가져올 것(필수) | 상태 | 뺄 것(범위 밖) |
|---|---|---|---|
| 찾아가기 | 정의 이동, 사용처, 심볼 검색(`Ctrl+T`), 클래스 검색, 파일 검색, 줄 이동, 아웃라인, 뒤로/앞으로, Ctrl+클릭·피크 | 파일·줄·뒤로/앞으로만 있음 | 호출 계층, 타입 계층, 의미 기반 리네임 |
| 검색 | 파일 검색, 여러 파일 찾아 바꾸기(미리보기) | 충족 | 구조적 검색(SSR) |
| 편집 | 저장, 충돌 감지, 인코딩·EOL, 찾아 바꾸기, 다중 커서, 줄바꿈, 확대 | 충족(Monaco) | 코드 포매터, 자동 import, 리팩터링 |
| 파일 | 폴더 열기, 파일 열기, 새 파일, 최근 항목, 외부 변경 감지 | 폴더 열기 UI·최근 폴더 없음 | 이름 변경·이동 리팩터링 |
| 보기 | 탭, 분할, 테마, Markdown 미리보기, 상태바 | 충족 | 미니맵 기본 켜기, 젠 모드 |
| 연동 | (선택) git 변경 표시 | 없음 | 디버거, 터미널, 빌드·실행, 확장 마켓 |
| 언어 지능 | ctags 기반 선언 인덱스 | 없음 | 번들 LSP, 자동완성, 진단(lint) |

---

<a id="cat-6"></a>

# <span class="num">6</span> 최종 권고안 <span class="hctl"><a href="#toc">↑ 목차로</a></span>

> 순서: 일반화 기본값 → 텍스트 판별 → 컴포넌트 찾아가기 1단계 → ctags. 앞의 둘은 작고, 뒤의 둘이 제품의 핵심이다.

<div class="lay">
 <div class="cd" style="border-top-color:#82b366"><b><span class="st">1</span> 일반화(1–2일)</b><span class="s">U1 base_dir 비우기 + 시작 화면, U3 무시 규칙 축소, U4 범위 일반화, U5 언어 자동 매핑</span></div>
 <div class="ar">→</div>
 <div class="cd" style="border-top-color:#d6b656"><b><span class="st">2</span> 텍스트 판별(1–2일)</b><span class="s">허용 목록을 내용 판별 + 차단 목록으로 바꿈. base_dir 안/밖 규칙 통일, dot 파일 표시, 편집 상한 상향</span></div>
 <div class="ar">→</div>
 <div class="cd" style="border-top-color:#b85450"><b><span class="st">3</span> 찾아가기 1단계(2–3일)</b><span class="s">Monaco provider 연결, 사용처 찾기, 정의 랭킹·오탐 수정, 후보 피크 목록</span></div>
 <div class="ar">→</div>
 <div class="cd" style="border-top-color:#6c8ebf"><b><span class="st">4</span> ctags(3–5일)</b><span class="s">번들 + 증분 인덱스 → <code>Ctrl+T</code> 심볼 검색, 클래스 검색, ctags 우선 정의 이동, 아웃라인 패널</span></div>
</div>

**컴포넌트 찾아가기 1순위 권고**: Universal Ctags를 rg처럼 번들하고 rg와 함께 쓴다(정의·심볼은 ctags, 사용처는 rg). 그 결과를 Monaco provider에 연결해 Ctrl+클릭·피크·심볼 검색을 제공한다. 번들 증가는 약 5MB(추정)이고 런타임 의존은 없다. LSP는 번들하지 않고 선택 연동으로만 남긴다.
