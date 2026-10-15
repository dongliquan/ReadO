# ReadO 성능 측정 보고서

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

**측정일**: 2026-10-07  
**기준 소스**: 커밋 `aebd051` + 작업 트리(`reado.py`·`README.md` 수정분) · `server.py` 772줄 · `source.html` 1768줄  
**환경**: Windows 11 Home 10.0.26200 · Python 3.12.10 · pywebview 6.2.1 · PyInstaller 6.21 · Playwright Chromium 1228(headless) · ripgrep **미설치**  
**범위**: 측정과 보고만 한다. 소스 코드는 수정하지 않았고, 측정 스크립트와 합성 코퍼스는 프로젝트 밖(세션 scratchpad)에 두었다.

<div class="warn">아래 <code>source.html</code> 라인 번호는 2026-10-07 시점 기준이다. 다른 세션이 곧 이 파일을 수정하므로, 적용할 때는 함수명으로 위치를 다시 찾는다.</div>

**범례 (영역·색)**
- 🟦 **서버** — `server.py`, `reado.py` (Python HTTP 서버·런처)
- 🟪 **프론트엔드** — `source.html` (Monaco·트리·검색 UI)
- 🟧 **빌드·번들** — `build.bat`, `reado.spec`, `vendor/`

<a id="toc"></a>

## 목차 <span class="hctl"><label for="xo" style="color:#0969da;cursor:pointer;text-decoration:underline">▼ 전체 펼치기</label> · <label for="xc" style="color:#0969da;cursor:pointer;text-decoration:underline">▶ 전체 접기</label></span>

- [**1. 요약**](#cat-1) — 핵심 수치 · 시작 타임라인 · 병목 Top 10 한눈에
- [**2. 측정 방법**](#cat-2) (3 항목)
- [**3. 측정 결과**](#cat-3) (7 항목)
- [**4. 병목 Top 10**](#cat-4) (10 항목)
- [**5. 개선안**](#cat-5) — 예상 효과 · 난이도 · 수정 파일
- [**6. 권장 적용 순서**](#cat-6) (4 단계)
- [**7. 2단계 A 적용 결과**](#cat-7) (4 항목) — 서버 보안·성능 전/후 수치
- [📎 **부록**](#appendix) — A.1 원시 로그 · A.2 측정 스크립트 · A.3 부수 발견

---

<a id="cat-1"></a>

# <span class="num">1</span> 요약 <span class="hctl"><a href="#toc">↑ 목차로</a></span>

> 가장 큰 문제는 서버다. 단일 스레드 HTTP 서버에서 Python 검색·심볼 찾기가 수 초~수십 초 걸리고, 그 동안 트리·파일 열기까지 함께 멈춘다.

### 핵심 수치

<table>
<thead><tr><th style="white-space:nowrap">영역</th><th style="white-space:nowrap">항목</th><th style="white-space:nowrap">측정값</th><th style="white-space:nowrap">판정</th></tr></thead>
<tbody>
<tr style="background:#f8f9fa"><td rowspan="2" valign="top"><b>🟧 시작</b></td><td>exe 실행 → 서버 응답</td><td>2.6 ~ 4.5 s (소스 실행 0.39 s)</td><td>느림</td></tr>
<tr style="background:#f8f9fa"><td>exe 실행 → Monaco 준비 완료</td><td>6.4 ~ 8.2 s (첫 실행 14.1 s)</td><td>느림</td></tr>
<tr style="background:#ffffff"><td rowspan="5" valign="top"><b>🟦 서버</b></td><td>찾기(Find in Files), 2.5만 파일, 첫 실행</td><td><b>32.6 s</b></td><td>심각</td></tr>
<tr style="background:#ffffff"><td>찾기, 반복 실행(캐시 후) · 단어 단위</td><td>7.1 s · <b>12.3 s</b></td><td>심각</td></tr>
<tr style="background:#ffffff"><td>정의로 이동(<code>/api/goto</code>)</td><td>9.0 ~ 10.1 s</td><td>심각</td></tr>
<tr style="background:#ffffff"><td>검색 중 트리 요청 대기</td><td>338 ms → <b>9.1 s</b></td><td>심각</td></tr>
<tr style="background:#ffffff"><td>Quick Open 인덱스 재구축(60초마다)</td><td>1.7 s</td><td>보통</td></tr>
<tr style="background:#f8f9fa"><td rowspan="4" valign="top"><b>🟪 프론트</b></td><td>폴더 5,200항목 펼치기</td><td>707 ms (서버 338 ms 포함)</td><td>보통</td></tr>
<tr style="background:#f8f9fa"><td>2 MB 파일 열기 / 50 MB(상한 해제) 열기</td><td>0.14 ~ 0.27 s / 0.91 s</td><td>양호 / 보통</td></tr>
<tr style="background:#f8f9fa"><td>스크롤 프레임(1~2 MB, headless)</td><td>평균 46 ~ 66 ms (기준 20 ms)</td><td>보통</td></tr>
<tr style="background:#f8f9fa"><td>.js 파일 첫 열기 시 추가 로딩</td><td>tsWorker.js 4.6 MB + 워커 2개</td><td>낭비</td></tr>
<tr style="background:#ffffff"><td rowspan="2" valign="top"><b>메모리</b></td><td>실행 직후 프로세스 합계(WorkingSet / Private)</td><td>576 ~ 652 MB / 332 ~ 393 MB</td><td>보통</td></tr>
<tr style="background:#ffffff"><td>JS 힙: 대기 / 2 MB 탭당</td><td>16.6 MB / 약 5 MB</td><td>양호</td></tr>
<tr style="background:#f8f9fa"><td rowspan="2" valign="top"><b>🟧 번들</b></td><td><code>dist/reado.exe</code></td><td>22.6 MB (onefile)</td><td>보통</td></tr>
<tr style="background:#f8f9fa"><td><code>vendor/</code></td><td>15 MB · 118 파일 (안 쓰는 TS 언어 서비스 4.5 MB 포함)</td><td>낭비</td></tr>
</tbody>
</table>

### 시작 타임라인 (exe, 웜 스타트 기준)

<div style="font-family:'Noto Sans KR',sans-serif">
<div class="lay">
 <div class="cd" style="border-top-color:#cf7700"><b>exe 실행</b><span class="k">t = 0</span><span class="s">onefile 압축 해제 시작</span></div>
 <div class="ar">→</div>
 <div class="cd" style="border-top-color:#cf7700"><b>압축 해제 + Python 기동</b><span class="k">≈ 2.2 ~ 4.1 s</span><span class="s">소스 실행이면 0.39 s — 차이는 대부분 onefile 해제</span></div>
 <div class="ar">→</div>
 <div class="cd" style="border-top-color:#1a4d8f"><b>서버 응답</b><span class="k">2.6 ~ 4.5 s</span><span class="s">reado.py:96 <code>wait_ready()</code> 통과 후에야 창 생성</span></div>
 <div class="ar">→</div>
 <div class="cd" style="border-top-color:#7c3aed"><b>WebView2 기동</b><span class="k">+ 2.3 s</span><span class="s">msedgewebview2 프로세스 6개</span></div>
 <div class="ar">→</div>
 <div class="cd" style="border-top-color:#7c3aed"><b>페이지·Monaco 로드</b><span class="k">+ 1.4 ~ 2.3 s</span><span class="s">private_mode 라 매 실행 7 MB 재전송</span></div>
 <div class="ar">→</div>
 <div class="cd" style="border-top-color:#1a7f37"><b>사용 가능</b><span class="k">6.4 ~ 8.2 s</span><span class="s">첫 실행 14.1 s</span></div>
</div>
</div>
<div class="cap">웜 스타트 3회 측정값의 범위. 각 구간은 서로 다른 실행의 값이라 합이 정확히 맞지는 않는다.</div>

### 병목 Top 10 한눈에

<table>
<thead><tr><th style="white-space:nowrap">#</th><th style="white-space:nowrap">영역</th><th style="white-space:nowrap">병목</th><th style="white-space:nowrap">위치</th><th style="white-space:nowrap">측정 근거</th></tr></thead>
<tbody>
<tr style="background:#f8f9fa"><td>1</td><td>🟦</td><td>단일 스레드 HTTP 서버 — 느린 요청이 전체를 막음</td><td><code>reado.py:68</code>, <code>server.py:766</code></td><td>트리 338 ms → 9.1 s</td></tr>
<tr style="background:#ffffff"><td>2</td><td>🟦</td><td>본문 캐시 5,000개 상한 + FIFO 축출 → 대형 저장소에서 매번 전체 재읽기</td><td><code>server.py:396-431</code></td><td>반복 검색 7.1 s, 캐시 4,503/25,007</td></tr>
<tr style="background:#f8f9fa"><td>3</td><td>🟦</td><td>Python 대체 검색: GIL 아래 32스레드, 단어 단위 정규식이 느림, rg 미동봉</td><td><code>server.py:390-393</code>, <code>526-630</code></td><td>첫 검색 32.6 s, 단어 단위 12.3 s</td></tr>
<tr style="background:#ffffff"><td>4</td><td>🟦</td><td>정의로 이동이 모든 파일을 순차로 읽음</td><td><code>server.py:229-285</code></td><td>9.0 ~ 10.1 s</td></tr>
<tr style="background:#f8f9fa"><td>5</td><td>🟧</td><td>onefile 빌드 — 실행마다 압축 해제, 창 생성이 서버 준비를 기다림</td><td><code>build.bat:31</code>, <code>reado.py:96</code></td><td>서버 응답 2.6 ~ 4.5 s (소스 0.39 s)</td></tr>
<tr style="background:#ffffff"><td>6</td><td>🟦</td><td>파일 인덱스를 요청 안에서 동기 재구축 + 필터 함수가 호출마다 집합 재생성</td><td><code>server.py:63-73</code>, <code>151-162</code>, <code>309-318</code></td><td>1.7 s, <code>_is_text_file</code> 6.5 µs/회</td></tr>
<tr style="background:#f8f9fa"><td>7</td><td>🟦🟪</td><td>폴더 목록: 항목마다 stat 2회 + 노드마다 innerHTML·리스너</td><td><code>server.py:336-360</code>, <code>source.html:950-990</code></td><td>5,200항목 707 ms, DOM 2.1만 개</td></tr>
<tr style="background:#ffffff"><td>8</td><td>🟪🟧</td><td>읽기 전용 뷰어인데 TS/JSON 언어 워커를 띄움 + vendor 미정리</td><td><code>source.html:806</code>, <code>vendor/monaco/vs/language</code></td><td>.js 열 때 4.6 MB 추가 로드</td></tr>
<tr style="background:#f8f9fa"><td>9</td><td>🟦🟪</td><td>대용량 파일: 2 MB 조용한 절단, JSON 래핑 전송, 큰 파일용 에디터 옵션 없음</td><td><code>server.py:363-387</code>, <code>source.html:797-806</code></td><td>50 MB: 서버 397 ms + 클라 913 ms, 한 줄 JSON 타이핑 93 ms/키</td></tr>
<tr style="background:#ffffff"><td>10</td><td>🟪</td><td>Markdown: marked 가 로드되지 않음(기능 버그) + 탭 전환마다 HTML 전체 재삽입</td><td><code>source.html:575-577</code>, <code>744</code>, <code>801</code></td><td><code>typeof marked</code> = undefined</td></tr>
</tbody>
</table>

---

<a id="cat-2"></a>

# <span class="num">2</span> 측정 방법 <span class="hctl"><a href="#toc">↑ 목차로</a></span>

> 실제 코드를 그대로 import 하거나 실행하고, 설정값만 메모리에서 바꿔 측정했다. 프로젝트 파일은 건드리지 않았다.

<div class="it">
<input type="checkbox" id="i2-1a" class="ca" style="display:none">
<input type="checkbox" id="i2-1b" class="cb" style="display:none">
<label for="i2-1a" class="ih la"><span class="n">2.1</span><b>합성 코퍼스</b> <span class="sub">3만 파일 · 260 MB</span></label>
<label for="i2-1b" class="ih lb"><span class="n">2.1</span><b>합성 코퍼스</b> <span class="sub">3만 파일 · 260 MB</span></label>
<div class="ib">

<table>
<thead><tr><th style="white-space:nowrap">폴더</th><th style="white-space:nowrap">구성</th><th style="white-space:nowrap">용도</th></tr></thead>
<tbody>
<tr style="background:#f8f9fa"><td><code>mono/</code></td><td>40 모듈 × 10 패키지 × 50 = Java 20,000개(각 3~4 KB, 166 MB) + 무시 대상 <code>node_modules/</code> 5,000개</td><td>검색 · 정의로 이동 · Quick Open 인덱스</td></tr>
<tr style="background:#ffffff"><td><code>flat/</code></td><td>한 폴더에 .java 5,000 + .png 500 + 하위 폴더 200</td><td>트리 로딩</td></tr>
<tr style="background:#f8f9fa"><td><code>big/</code></td><td>Java 1 / 2 / 5 / 20 / 50 MB, 한 줄짜리 JSON 5 MB, Markdown 2 MB</td><td>대용량 열기 · 스크롤 · 편집</td></tr>
</tbody>
</table>

인덱스 대상 파일은 25,007개(무시 규칙 적용 후)다. 실제 사용 경로인 <code>c:\Projects</code> 는 측정하지 않았다 — 저장소 규모에 따라 수치가 비례해 커진다.

</div>
</div>
<div class="it">
<input type="checkbox" id="i2-2a" class="ca" style="display:none">
<input type="checkbox" id="i2-2b" class="cb" style="display:none">
<label for="i2-2a" class="ih la"><span class="n">2.2</span><b>측정 도구</b> <span class="sub">서버 · 프론트 · exe 세 갈래</span></label>
<label for="i2-2b" class="ih lb"><span class="n">2.2</span><b>측정 도구</b> <span class="sub">서버 · 프론트 · exe 세 갈래</span></label>
<div class="ib">

<table>
<thead><tr><th style="white-space:nowrap">대상</th><th style="white-space:nowrap">방법</th><th style="white-space:nowrap">반복</th></tr></thead>
<tbody>
<tr style="background:#f8f9fa"><td>🟦 서버 API</td><td><code>server.py</code> 를 import 해 별도 포트(18766)에 원래의 <code>HTTPServer</code> 로 띄우고 <code>urllib</code> 로 왕복 시간 측정. 함수 단위는 <code>perf_counter</code>, 캐시 메모리는 <code>tracemalloc</code></td><td>3 ~ 5회 중앙값</td></tr>
<tr style="background:#ffffff"><td>🟪 프론트엔드</td><td>같은 서버 + Playwright headless Chromium(WebView2 와 같은 엔진). 페이지 안에서 <code>performance.now()</code> 와 rAF 2회로 “그려질 때까지” 측정. 힙은 <code>performance.memory</code>, CDP <code>Performance.getMetrics</code></td><td>1 ~ 3회</td></tr>
<tr style="background:#f8f9fa"><td>🟧 exe 시작·메모리</td><td><code>dist/reado.exe</code> 를 <code>WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port</code> 로 실행해 실제 WebView2 에 CDP 로 붙음. 프로세스 트리 메모리는 <code>Win32_Process</code> 합산</td><td>3회</td></tr>
</tbody>
</table>

</div>
</div>
<div class="it">
<input type="checkbox" id="i2-3a" class="ca" style="display:none">
<input type="checkbox" id="i2-3b" class="cb" style="display:none">
<label for="i2-3a" class="ih la"><span class="n">2.3</span><b>측정의 한계</b> <span class="sub">수치를 읽을 때 감안할 점</span></label>
<label for="i2-3b" class="ih lb"><span class="n">2.3</span><b>측정의 한계</b> <span class="sub">수치를 읽을 때 감안할 점</span></label>
<div class="ib">

- **스크롤·타이핑 프레임 시간은 상대 비교용이다.** headless Chromium 은 GPU 없이 소프트웨어로 그리므로 작은 파일도 프레임이 20 ms 안팎이다. 절대값보다 “작은 파일 대비 몇 배”로 읽는다.
- **편집은 현재 기능이 아니다.** 에디터가 `readOnly: true`(`source.html:613`)라서, 측정할 때만 읽기 전용을 잠시 풀고 `type` 명령으로 30자를 입력했다.
- **ripgrep 이 PATH 에 없다.** 그래서 모든 검색 수치는 Python 대체 경로다. rg 가 있는 PC 에서는 검색이 훨씬 빠르지만, exe 에 rg 가 동봉되지 않으므로 일반 사용자는 대체 경로를 탄다.
- 첫 실행(콜드) 수치는 OS 파일 캐시·백신 검사 영향이 크다.

</div>
</div>

---

<a id="cat-3"></a>

# <span class="num">3</span> 측정 결과 <span class="hctl"><a href="#toc">↑ 목차로</a></span>

> 영역별 원시 수치. 병목 해석은 4장에 있다.

<div class="it">
<input type="checkbox" id="i3-1a" class="ca" style="display:none">
<input type="checkbox" id="i3-1b" class="cb" style="display:none">
<label for="i3-1a" class="ih la"><span class="n">3.1</span><b>🟧 앱 시작 시간</b> <span class="sub">dist/reado.exe · 실제 WebView2</span></label>
<label for="i3-1b" class="ih lb"><span class="n">3.1</span><b>🟧 앱 시작 시간</b> <span class="sub">dist/reado.exe · 실제 WebView2</span></label>
<div class="ib">

<table>
<thead><tr><th style="white-space:nowrap">실행</th><th style="white-space:nowrap">서버 응답</th><th style="white-space:nowrap">WebView2 기동</th><th style="white-space:nowrap">Monaco 준비</th><th style="white-space:nowrap">트리 표시</th><th style="white-space:nowrap">페이지 DCL / load</th></tr></thead>
<tbody>
<tr style="background:#f8f9fa"><td>1회차(콜드)</td><td>3,873 ms</td><td>11,750 ms</td><td>14,060 ms</td><td>14,115 ms</td><td>543 / 1,650 ms</td></tr>
<tr style="background:#ffffff"><td>2회차</td><td>4,494 ms</td><td>6,782 ms</td><td>8,152 ms</td><td>8,160 ms</td><td>289 / 890 ms</td></tr>
<tr style="background:#f8f9fa"><td>3회차</td><td>2,595 ms</td><td>4,890 ms</td><td>6,427 ms</td><td>6,439 ms</td><td>473 / 1,185 ms</td></tr>
</tbody>
</table>

- 소스 실행(`python reado.py`)의 서버 응답은 **389 ms**, `import webview` 는 207 ms. exe 와의 차이 2.2 ~ 4.1 s 는 onefile 압축 해제(22.6 MB → 임시 폴더)에서 나온다. `reado.spec:29` 의 `upx=True` 는 UPX 가 설치돼 있지 않아 실제로는 적용되지 않는다.
- 브라우저만 따로 재면(headless) 페이지 로드 → Monaco 준비 630 ms, 요청 15개 · 7.0 MB. 첫 로드는 2.1 s.
- pywebview `start()` 의 `private_mode` 기본값이 `True` 라 HTTP 캐시가 실행마다 비워진다. `/vendor/` 의 `immutable` 캐시 헤더(`server.py:741`)가 앱 재실행 사이에는 효과가 없다.

</div>
</div>
<div class="it">
<input type="checkbox" id="i3-2a" class="ca" style="display:none">
<input type="checkbox" id="i3-2b" class="cb" style="display:none">
<label for="i3-2a" class="ih la"><span class="n">3.2</span><b>🟦 서버 API 응답 시간</b> <span class="sub">가벼운 엔드포인트 · 파일 · Quick Open</span></label>
<label for="i3-2b" class="ih lb"><span class="n">3.2</span><b>🟦 서버 API 응답 시간</b> <span class="sub">가벼운 엔드포인트 · 파일 · Quick Open</span></label>
<div class="ib">

<table>
<thead><tr><th style="white-space:nowrap">엔드포인트</th><th style="white-space:nowrap">조건</th><th style="white-space:nowrap">중앙값</th><th style="white-space:nowrap">응답 크기</th></tr></thead>
<tbody>
<tr style="background:#f8f9fa"><td rowspan="4" valign="top"><b>가벼운 요청</b></td><td><code>GET /</code> (source.html)</td><td>16 ms</td><td>66 KB</td></tr>
<tr style="background:#f8f9fa"><td><code>/api/settings</code> · <code>/api/projects</code></td><td>2.6 ms</td><td>0.6 KB</td></tr>
<tr style="background:#f8f9fa"><td><code>/vendor/…/editor.main.js</code></td><td>21 ms (최대 656 ms)</td><td>3.4 MB</td></tr>
<tr style="background:#f8f9fa"><td><code>/api/tree</code> 루트(3개)</td><td>2.3 ms</td><td>0.2 KB</td></tr>
<tr style="background:#ffffff"><td rowspan="3" valign="top"><b><code>/api/file</code><br>상한 2 MB</b></td><td>1 MB / 2 MB Java</td><td>38 / 41 ms</td><td>1.1 / 2.1 MB</td></tr>
<tr style="background:#ffffff"><td>5 / 20 / 50 MB Java(2 MB 로 절단)</td><td>18 / 28 / 34 ms</td><td>2.1 MB</td></tr>
<tr style="background:#ffffff"><td>한 줄 JSON 5 MB · Markdown 2 MB</td><td>49 / 38 ms</td><td>2.5 / 2.3 MB</td></tr>
<tr style="background:#f8f9fa"><td rowspan="1" valign="top"><b><code>/api/file</code><br>상한 해제</b></td><td>5 / 20 / 50 MB Java</td><td>61 / 170 / 397 ms</td><td>5.5 / 21.9 / 54.6 MB</td></tr>
<tr style="background:#ffffff"><td rowspan="4" valign="top"><b><code>/api/files</code><br>Quick Open</b></td><td>콜드(인덱스 구축 포함)</td><td><b>1,695 ms</b></td><td>4.7 KB</td></tr>
<tr style="background:#ffffff"><td>웜, <code>q=Svc01</code></td><td>27 ms</td><td>4.7 KB</td></tr>
<tr style="background:#ffffff"><td>웜, <code>q=s</code>(거의 전부 일치)</td><td>68 ms</td><td>3.9 KB</td></tr>
<tr style="background:#ffffff"><td>웜, <code>q=*svc*java</code></td><td>93 ms</td><td>5.1 KB</td></tr>
</tbody>
</table>

함수 단위: `_walk_files` 1,335 ms(2.5만 파일) · `_is_text_file` 10만 회 648 ms · `_is_ignored` 10만 회 308 ms.

</div>
</div>
<div class="it">
<input type="checkbox" id="i3-3a" class="ca" style="display:none">
<input type="checkbox" id="i3-3b" class="cb" style="display:none">
<label for="i3-3a" class="ih la"><span class="n">3.3</span><b>🟦 찾기 · 정의로 이동</b> <span class="sub">Python 대체 경로 · 2.5만 파일</span></label>
<label for="i3-3b" class="ih lb"><span class="n">3.3</span><b>🟦 찾기 · 정의로 이동</b> <span class="sub">Python 대체 경로 · 2.5만 파일</span></label>
<div class="ib">

<table>
<thead><tr><th style="white-space:nowrap">요청</th><th style="white-space:nowrap">조건</th><th style="white-space:nowrap">시간</th><th style="white-space:nowrap">비고</th></tr></thead>
<tbody>
<tr style="background:#f8f9fa"><td rowspan="5" valign="top"><b><code>/api/search</code></b></td><td>일치 없음, 콜드</td><td><b>32,631 ms</b></td><td>전 파일 읽기</td></tr>
<tr style="background:#f8f9fa"><td>일치 없음, 웜</td><td><b>7,148 ms</b></td><td>캐시 4,503개만 남음</td></tr>
<tr style="background:#f8f9fa"><td><code>payment</code>(500건 상한 도달)</td><td>1,695 ms</td><td>상한에서 조기 종료</td></tr>
<tr style="background:#f8f9fa"><td>정규식 <code>method\d+\(</code></td><td>1,696 ms</td><td>상한에서 조기 종료</td></tr>
<tr style="background:#f8f9fa"><td>단어 단위 <code>Svc0100</code></td><td><b>12,288 ms</b></td><td>일치 적음 → 끝까지 탐색</td></tr>
<tr style="background:#ffffff"><td rowspan="2" valign="top"><b><code>/api/goto</code></b></td><td><code>Svc0100</code></td><td>8,964 ms</td><td>순차 읽기</td></tr>
<tr style="background:#ffffff"><td><code>method24</code>(일치 많음)</td><td>10,087 ms</td><td></td></tr>
<tr style="background:#f8f9fa"><td><b>동시성</b></td><td>콜드 검색 시작 0.2 s 뒤 <code>/api/tree?path=flat</code></td><td><b>9,103 ms</b></td><td>단독이면 338 ms</td></tr>
</tbody>
</table>

- 본문 캐시(`_CONTENT_CACHE`)는 콜드 검색 후 **4,503개 / 24 MB**(최대 60 MB)였다. 상한 5,000개에 닿을 때마다 오래된 10%를 지우므로, 파일이 5,000개를 넘는 저장소에서는 다음 검색도 대부분을 디스크에서 다시 읽는다.
- 일치가 적은 검색일수록 느리다 — 500건 상한에서 조기 종료하지 못하고 전 파일을 끝까지 훑기 때문이다.
- 화면 쪽 비용은 작다: 결과 500건 렌더(`renderFIFResults`) 13 ms.

</div>
</div>
<div class="it">
<input type="checkbox" id="i3-4a" class="ca" style="display:none">
<input type="checkbox" id="i3-4b" class="cb" style="display:none">
<label for="i3-4a" class="ih la"><span class="n">3.4</span><b>🟦🟪 폴더 트리 로딩</b> <span class="sub">한 폴더에 5,700항목</span></label>
<label for="i3-4b" class="ih lb"><span class="n">3.4</span><b>🟦🟪 폴더 트리 로딩</b> <span class="sub">한 폴더에 5,700항목</span></label>
<div class="ib">

<table>
<thead><tr><th style="white-space:nowrap">구간</th><th style="white-space:nowrap">시간</th><th style="white-space:nowrap">비고</th></tr></thead>
<tbody>
<tr style="background:#f8f9fa"><td>서버 <code>list_dir</code> (5,000 + png 500 + 폴더 200)</td><td>338 ms (283 ~ 552)</td><td>응답 295 KB, png 500개는 걸러짐</td></tr>
<tr style="background:#ffffff"><td>클릭 → 5,200 노드 그려짐(전체)</td><td>707 ms</td><td>DOM 요소 21,216개, 힙 +1 MB</td></tr>
</tbody>
</table>

트리는 한 단계씩 지연 로딩하므로 폴더 깊이는 문제가 아니다. 한 폴더 안 항목 수에 비례해 서버 stat 비용과 DOM 생성 비용이 함께 늘어난다.

</div>
</div>
<div class="it">
<input type="checkbox" id="i3-5a" class="ca" style="display:none">
<input type="checkbox" id="i3-5b" class="cb" style="display:none">
<label for="i3-5a" class="ih la"><span class="n">3.5</span><b>🟪 대용량 파일 열기 · 스크롤 · 편집</b> <span class="sub">headless Chromium · 기준은 4 KB 파일</span></label>
<label for="i3-5b" class="ih lb"><span class="n">3.5</span><b>🟪 대용량 파일 열기 · 스크롤 · 편집</b> <span class="sub">headless Chromium · 기준은 4 KB 파일</span></label>
<div class="ib">

<table>
<thead><tr><th style="white-space:nowrap">파일</th><th style="white-space:nowrap">줄 수</th><th style="white-space:nowrap">열기 → 그려짐</th><th style="white-space:nowrap">스크롤 프레임 평균 / p95</th><th style="white-space:nowrap">타이핑 키→프레임 중앙 / p95</th><th style="white-space:nowrap">힙</th></tr></thead>
<tbody>
<tr style="background:#f8f9fa"><td>4 KB Java (기준)</td><td>70</td><td>92 ms</td><td>19.7 / 39.4 ms</td><td>22.1 / 29.0 ms</td><td>17 MB</td></tr>
<tr style="background:#ffffff"><td>1 MB Java</td><td>14,689</td><td>125 ~ 136 ms</td><td>45.5 ~ 65.9 / 64 ~ 97 ms</td><td>43 ~ 47 / 51 ~ 66 ms</td><td>25 MB</td></tr>
<tr style="background:#f8f9fa"><td>2 MB Java</td><td>27,011</td><td>140 ~ 265 ms</td><td>47.3 ~ 65.2 / 61 ~ 109 ms</td><td>45 / 52 ~ 109 ms</td><td>38 MB</td></tr>
<tr style="background:#ffffff"><td>50 MB Java (2 MB 로 절단)</td><td>27,006</td><td>148 ~ 257 ms</td><td>46.1 ~ 59.5 / 59 ~ 81 ms</td><td>40 ~ 46 / 51 ~ 56 ms</td><td>47 MB</td></tr>
<tr style="background:#f8f9fa"><td>한 줄 JSON 5 MB (2 MB 로 절단)</td><td>1</td><td>213 ~ 248 ms</td><td>가로 19 ~ 22 ms, 최대 <b>425 ms</b></td><td><b>93 ~ 114</b> / 111 ~ 146 ms</td><td>51 MB</td></tr>
<tr style="background:#ffffff"><td>Markdown 2 MB (Monaco 로 열림)</td><td>158,278</td><td>198 ~ 391 ms</td><td>—</td><td>—</td><td><b>+54 ~ 87 MB</b></td></tr>
<tr style="background:#f8f9fa"><td rowspan="3" valign="top">상한 해제 시<br>(새 페이지)</td><td>5 MB · 71,809줄</td><td>214 ms</td><td>41.6 / 54.6 ms</td><td>28.2 / 33.2 ms</td><td>—</td></tr>
<tr style="background:#f8f9fa"><td>20 MB · 287,233줄</td><td>658 ms</td><td>42.1 / 56.1 ms</td><td>16.9 / 19.6 ms</td><td>52 MB</td></tr>
<tr style="background:#f8f9fa"><td>50 MB · 717,537줄</td><td><b>913 ms</b></td><td>—</td><td>—</td><td>132 MB</td></tr>
</tbody>
</table>

- 1 ~ 2 MB 파일에서 스크롤 프레임이 기준의 약 2.5 ~ 3배다. 멀리 점프할 때마다 새 화면 영역을 토큰화(구문 색칠)하는 비용이다.
- 20 MB 이상에서 타이핑이 오히려 빠른 것은 Monaco 의 큰 파일 모드(`largeFileOptimizations`)가 토큰화를 끄기 때문이다.
- 한 줄짜리 파일은 줄 하나가 2 MB 라 편집할 때마다 그 줄 전체를 다시 처리한다(키당 약 100 ms).
- 기본 상한 2 MB 때문에 5 MB 이상 파일은 앞부분만 보인다. 사용자에게는 토스트 한 번만 뜬다.
- 2 MB 탭 10개를 열면 힙 81 → 124 MB(탭당 약 5 MB). 탭을 닫으면 모델을 dispose 하므로 누수는 보이지 않았다.

</div>
</div>
<div class="it">
<input type="checkbox" id="i3-6a" class="ca" style="display:none">
<input type="checkbox" id="i3-6b" class="cb" style="display:none">
<label for="i3-6a" class="ih la"><span class="n">3.6</span><b>메모리 사용</b> <span class="sub">프로세스 · JS 힙 · 서버 캐시</span></label>
<label for="i3-6b" class="ih lb"><span class="n">3.6</span><b>메모리 사용</b> <span class="sub">프로세스 · JS 힙 · 서버 캐시</span></label>
<div class="ib">

<table>
<thead><tr><th style="white-space:nowrap">대상</th><th style="white-space:nowrap">측정값</th><th style="white-space:nowrap">비고</th></tr></thead>
<tbody>
<tr style="background:#f8f9fa"><td>exe 실행 2초 뒤 프로세스 합계</td><td>WorkingSet 576 ~ 652 MB · Private 332 ~ 393 MB</td><td>reado.exe 2개(부트로더+본체) + msedgewebview2 6개</td></tr>
<tr style="background:#ffffff"><td>JS 힙(대기)</td><td>16.6 MB</td><td>실제 WebView2 · headless 모두 같음</td></tr>
<tr style="background:#f8f9fa"><td>JS 힙(대용량 7탭 후)</td><td>사용 94 MB / 할당 156 MB · DOM 노드 18만</td><td>트리 5,200 노드 포함</td></tr>
<tr style="background:#ffffff"><td>서버 본문 캐시</td><td>24 MB(4,503개, 작은 파일)</td><td>상한이 <b>개수</b>(5,000)라 바이트 상한이 없음 — 이론상 5,000 × 5 MB</td></tr>
</tbody>
</table>

메모리 대부분은 WebView2(Chromium) 기본 비용이고 앱 코드가 쓰는 양은 작다. 위험 요소는 바이트 상한이 없는 서버 캐시와 큰 파일을 열 때 생기는 일시적 사본이다(JSON 직렬화 문자열 + 바이트 + 디코드 문자열).

</div>
</div>
<div class="it">
<input type="checkbox" id="i3-7a" class="ca" style="display:none">
<input type="checkbox" id="i3-7b" class="cb" style="display:none">
<label for="i3-7a" class="ih la"><span class="n">3.7</span><b>🟧 번들 크기</b> <span class="sub">dist · vendor</span></label>
<label for="i3-7b" class="ih lb"><span class="n">3.7</span><b>🟧 번들 크기</b> <span class="sub">dist · vendor</span></label>
<div class="ib">

<table>
<thead><tr><th style="white-space:nowrap">항목</th><th style="white-space:nowrap">크기</th><th style="white-space:nowrap">실제 사용 여부</th></tr></thead>
<tbody>
<tr style="background:#f8f9fa"><td><code>dist/reado.exe</code> (onefile)</td><td>22.6 MB</td><td>—</td></tr>
<tr style="background:#ffffff"><td><code>vendor/</code> 전체</td><td>15 MB · 118 파일</td><td>—</td></tr>
<tr style="background:#f8f9fa"><td><code>monaco/vs/editor/editor.main.js</code></td><td>3.4 MB (gzip 0.88 MB)</td><td>필수</td></tr>
<tr style="background:#ffffff"><td><code>monaco/vs/editor/*.nls.*.js</code> 다국어 10개</td><td>1.9 MB</td><td>안 씀(로케일 미설정)</td></tr>
<tr style="background:#f8f9fa"><td><code>monaco/vs/language/typescript</code></td><td>4.5 MB</td><td>읽기 전용 뷰어엔 불필요 — .js/.ts 열 때 워커로 로드됨</td></tr>
<tr style="background:#ffffff"><td><code>monaco/vs/language/css · html · json</code></td><td>1.4 MB</td><td>불필요(진단·자동완성 전용)</td></tr>
<tr style="background:#f8f9fa"><td><code>monaco/vs/basic-languages</code> (80개)</td><td>648 KB</td><td>필수(구문 색칠)</td></tr>
<tr style="background:#ffffff"><td><code>fonts/</code> Pretendard 2.0 MB + D2Coding 0.75 MB</td><td>2.7 MB</td><td>필수</td></tr>
</tbody>
</table>

</div>
</div>

---

<a id="cat-4"></a>

# <span class="num">4</span> 병목 Top 10 <span class="hctl"><a href="#toc">↑ 목차로</a></span>

> 사용자 체감 영향이 큰 순서. 각 항목은 위치 · 원인 · 근거 수치로 나눴다.

<div class="it">
<input type="checkbox" id="i4-1a" class="ca" style="display:none">
<input type="checkbox" id="i4-1b" class="cb" style="display:none">
<label for="i4-1a" class="ih la"><span class="n">4.1</span><b>🟦 단일 스레드 HTTP 서버</b> <span class="sub"><code>reado.py:68</code> · <code>server.py:766</code></span></label>
<label for="i4-1b" class="ih lb"><span class="n">4.1</span><b>🟦 단일 스레드 HTTP 서버</b> <span class="sub"><code>reado.py:68</code> · <code>server.py:766</code></span></label>
<div class="ib">

### <span class="n3">4.1.1</span>원인

`http.server.HTTPServer` 는 요청을 하나씩 처리한다. 검색(최대 32 s)·정의로 이동(9 s)·인덱스 재구축(1.7 s)이 도는 동안 트리 펼치기, 파일 열기, 설정 조회가 모두 줄을 선다. 프론트는 `AbortController` 로 이전 검색을 취소하지만(`source.html:1103`), 서버는 이미 시작한 검색을 끝까지 계속한다.

### <span class="n3">4.1.2</span>근거

단독 338 ms 인 트리 요청이 콜드 검색 중에는 **9,103 ms** 걸렸다. 사용자에겐 “검색하면 앱 전체가 멈춘다”로 보인다.

</div>
</div>
<div class="it">
<input type="checkbox" id="i4-2a" class="ca" style="display:none">
<input type="checkbox" id="i4-2b" class="cb" style="display:none">
<label for="i4-2a" class="ih la"><span class="n">4.2</span><b>🟦 본문 캐시 상한 5,000개 + FIFO 축출</b> <span class="sub"><code>server.py:396-431</code></span></label>
<label for="i4-2b" class="ih lb"><span class="n">4.2</span><b>🟦 본문 캐시 상한 5,000개 + FIFO 축출</b> <span class="sub"><code>server.py:396-431</code></span></label>
<div class="ib">

### <span class="n3">4.2.1</span>원인

`_CONTENT_CACHE_LIMIT = 5000`(`:397`). 가득 차면 삽입 순서로 앞 10%를 지운다(`:427-430`). 파일이 5,000개를 넘는 저장소에서는 검색 한 번이 캐시를 처음부터 끝까지 갈아엎어, 다음 검색이 다시 거의 전부를 디스크에서 읽는다. 게다가 캐시가 맞아도 파일마다 `getmtime` + `getsize` 로 stat 을 2번 한다(`:402-403`).

### <span class="n3">4.2.2</span>근거

2.5만 파일 콜드 검색 후 캐시는 4,503개만 남았고, 반복 검색(일치 없음)이 **7.1 s** 걸렸다. 캐시가 효과를 내는 건 5,000개 이하 저장소뿐이다.

</div>
</div>
<div class="it">
<input type="checkbox" id="i4-3a" class="ca" style="display:none">
<input type="checkbox" id="i4-3b" class="cb" style="display:none">
<label for="i4-3a" class="ih la"><span class="n">4.3</span><b>🟦 Python 대체 검색 엔진</b> <span class="sub"><code>server.py:390-393</code> · <code>526-630</code> · rg 미동봉</span></label>
<label for="i4-3b" class="ih lb"><span class="n">4.3</span><b>🟦 Python 대체 검색 엔진</b> <span class="sub"><code>server.py:390-393</code> · <code>526-630</code> · rg 미동봉</span></label>
<div class="ib">

### <span class="n3">4.3.1</span>원인

- `RIPGREP = shutil.which("rg")`(`:393`) — exe 에 rg 가 들어 있지 않아 대부분의 PC 에서 대체 경로를 탄다.
- `ThreadPoolExecutor(max_workers=32)`(`:392`): 파일 읽기는 병렬이지만 디코드·정규식은 GIL 때문에 사실상 한 코어에서 돈다.
- 일치한 파일은 `splitlines()` 로 통째로 나눈 뒤 줄마다 다시 정규식을 돌린다(`:535-537`).
- 단어 단위는 `(?<!\w)…(?!\w)` + `IGNORECASE` 로 바뀌어(`:569`) 일반 검색보다 7배 느리다.
- 일치가 적으면 500건 상한에 닿지 못해 조기 종료가 없다.

### <span class="n3">4.3.2</span>rg 경로의 잠재 문제

rg 가 있는 PC 에서도 `subprocess.run(capture_output=True)`(`:458`)로 **출력 전체를 메모리에 받은 뒤** 파싱한다. 전체 결과 상한이 없고(`--max-count 100` 은 파일당), `--max-columns` 도 없어 한 줄짜리 큰 파일이 걸리면 JSON 한 줄이 수 MB 가 된다. 500건에서 파싱을 멈춰도 rg 는 끝까지 돈다.

### <span class="n3">4.3.3</span>근거

콜드 **32.6 s**, 단어 단위 **12.3 s**, 일반 검색 웜 7.1 s(2.5만 파일 · 166 MB).

</div>
</div>
<div class="it">
<input type="checkbox" id="i4-4a" class="ca" style="display:none">
<input type="checkbox" id="i4-4b" class="cb" style="display:none">
<label for="i4-4a" class="ih la"><span class="n">4.4</span><b>🟦 정의로 이동이 전 파일 순차 스캔</b> <span class="sub"><code>server.py:229-285</code></span></label>
<label for="i4-4b" class="ih lb"><span class="n">4.4</span><b>🟦 정의로 이동이 전 파일 순차 스캔</b> <span class="sub"><code>server.py:229-285</code></span></label>
<div class="ib">

### <span class="n3">4.4.1</span>원인

`goto_symbol` 은 인덱스의 모든 파일을 스레드 풀 없이 **순차로** `_get_content` 한 뒤(`:261-267`), 일치한 파일을 `splitlines()` 해서 줄마다 `word_pat` 과 복잡한 `decl_pat` 을 돌린다. rg 경로도 쓰지 않는다. 4.2 의 캐시 축출 문제도 그대로 받는다. 선언이 여러 개면 프론트가 다시 `/api/search` 를 부르므로(`source.html:1638` `gotoDefinition`) 같은 스캔을 한 번 더 한다.

### <span class="n3">4.4.2</span>근거

Ctrl+B 한 번에 **9.0 ~ 10.1 s**. 그동안 서버 전체가 멈춘다(4.1).

</div>
</div>
<div class="it">
<input type="checkbox" id="i4-5a" class="ca" style="display:none">
<input type="checkbox" id="i4-5b" class="cb" style="display:none">
<label for="i4-5a" class="ih la"><span class="n">4.5</span><b>🟧 onefile 빌드와 직렬 시작</b> <span class="sub"><code>build.bat:31</code> · <code>reado.spec</code> · <code>reado.py:96</code></span></label>
<label for="i4-5b" class="ih lb"><span class="n">4.5</span><b>🟧 onefile 빌드와 직렬 시작</b> <span class="sub"><code>build.bat:31</code> · <code>reado.spec</code> · <code>reado.py:96</code></span></label>
<div class="ib">

### <span class="n3">4.5.1</span>원인

- `--onefile` 은 실행할 때마다 22.6 MB 를 임시 폴더에 풀고 나서 Python 을 띄운다. 백신 검사도 이때 걸린다.
- `main()` 이 `wait_ready()`(`:96`)로 서버 응답을 확인한 뒤에야 `create_window` 를 호출해, 창이 늦게 뜨고 WebView2 기동(약 2.3 s)이 서버 준비와 겹치지 않는다.
- `private_mode=True`(pywebview 기본값)라 Monaco 등 7 MB 를 실행마다 다시 받는다.

### <span class="n3">4.5.2</span>근거

서버 응답이 exe 2.6 ~ 4.5 s 인데 소스 실행은 0.39 s. 사용 가능까지 웜 6.4 ~ 8.2 s, 콜드 14.1 s.

</div>
</div>
<div class="it">
<input type="checkbox" id="i4-6a" class="ca" style="display:none">
<input type="checkbox" id="i4-6b" class="cb" style="display:none">
<label for="i4-6a" class="ih la"><span class="n">4.6</span><b>🟦 인덱스 동기 재구축 + 필터 함수 비효율</b> <span class="sub"><code>server.py:63-73</code> · <code>151-162</code> · <code>309-318</code></span></label>
<label for="i4-6b" class="ih lb"><span class="n">4.6</span><b>🟦 인덱스 동기 재구축 + 필터 함수 비효율</b> <span class="sub"><code>server.py:63-73</code> · <code>151-162</code> · <code>309-318</code></span></label>
<div class="ib">

### <span class="n3">4.6.1</span>원인

- `_ensure_index` 는 60초가 지나면 **요청을 처리하는 도중에** `os.walk` 로 전체를 다시 훑는다(`:155-157`). 잠시 쉬었다가 Quick Open 을 누르면 첫 글자에서 1.7 s 를 기다린다.
- `_is_text_file` 이 호출될 때마다 `_allowed_exts()` 가 확장자 집합을 새로 만든다(`:63-65`). 파일 하나당 6.5 µs.
- `_is_ignored` 는 호출마다 패턴 목록을 돌며 `lower()` 와 `fnmatch` 를 반복한다(`:311-317`).

### <span class="n3">4.6.2</span>근거

인덱스 구축 1,695 ms 중 `_walk_files` 1,335 ms. `_is_text_file` 10만 회 648 ms, `_is_ignored` 10만 회 308 ms — 걷기 시간의 상당 부분이 필터 함수다.

</div>
</div>
<div class="it">
<input type="checkbox" id="i4-7a" class="ca" style="display:none">
<input type="checkbox" id="i4-7b" class="cb" style="display:none">
<label for="i4-7a" class="ih la"><span class="n">4.7</span><b>🟦🟪 큰 폴더의 트리 로딩</b> <span class="sub"><code>server.py:336-360</code> · <code>source.html:950-990</code></span></label>
<label for="i4-7b" class="ih lb"><span class="n">4.7</span><b>🟦🟪 큰 폴더의 트리 로딩</b> <span class="sub"><code>server.py:336-360</code> · <code>source.html:950-990</code></span></label>
<div class="ib">

### <span class="n3">4.7.1</span>원인

- 서버: `os.listdir` 후 항목마다 `os.path.isdir` + `os.path.getsize` 로 stat 2회(`:351-352`) + 4.6 의 필터 함수. Windows 에서 `os.scandir` 를 쓰면 stat 정보가 목록과 함께 와서 추가 호출이 필요 없다.
- 프론트: 항목마다 `createElement` + 템플릿 `innerHTML` + `addEventListener` + `appendChild` 를 바로 DOM 에 한다(`:950-990`). 폴더 노드 클릭 때마다 `querySelector('.caret')` 도 한다. 화면에 보이는 수십 개만 그려도 되는 상황에서 전부 그린다.

### <span class="n3">4.7.2</span>근거

5,200항목 폴더: 서버 338 ms + 화면 약 370 ms = **707 ms**, DOM 요소 21,216개.

</div>
</div>
<div class="it">
<input type="checkbox" id="i4-8a" class="ca" style="display:none">
<input type="checkbox" id="i4-8b" class="cb" style="display:none">
<label for="i4-8a" class="ih la"><span class="n">4.8</span><b>🟪🟧 읽기 전용 뷰어에 언어 서비스 워커</b> <span class="sub"><code>source.html:806</code> · <code>vendor/monaco/vs/language</code></span></label>
<label for="i4-8b" class="ih lb"><span class="n">4.8</span><b>🟪🟧 읽기 전용 뷰어에 언어 서비스 워커</b> <span class="sub"><code>source.html:806</code> · <code>vendor/monaco/vs/language</code></span></label>
<div class="ib">

### <span class="n3">4.8.1</span>원인

`createModel(data.text, langFor(path))` 로 `javascript`/`typescript`/`json`/`css`/`html` 모델을 만들면 Monaco 가 해당 언어 서비스를 켜고 Web Worker 를 띄워 파일 전체를 진단한다. 에디터가 읽기 전용이라 자동완성·진단이 필요 없는데도 실행된다. `MonacoEnvironment` 설정이 없어 워커 경로를 기본값으로 찾는다.

### <span class="n3">4.8.2</span>근거

.js 파일을 처음 열 때 `tsMode.js` 24 KB + `workerMain.js` 340 KB × 2 + **`tsWorker.js` 4.6 MB** 를 추가로 받았다. .json 은 `jsonMode.js` + `jsonWorker.js` 129 KB + 워커 1개. vendor 15 MB 중 언어 서비스(5.9 MB)와 다국어 파일(1.9 MB)이 절반이다.

</div>
</div>
<div class="it">
<input type="checkbox" id="i4-9a" class="ca" style="display:none">
<input type="checkbox" id="i4-9b" class="cb" style="display:none">
<label for="i4-9a" class="ih la"><span class="n">4.9</span><b>🟦🟪 대용량 파일 처리</b> <span class="sub"><code>server.py:58</code> · <code>363-387</code> · <code>source.html:797-806</code></span></label>
<label for="i4-9b" class="ih lb"><span class="n">4.9</span><b>🟦🟪 대용량 파일 처리</b> <span class="sub"><code>server.py:58</code> · <code>363-387</code> · <code>source.html:797-806</code></span></label>
<div class="ib">

### <span class="n3">4.9.1</span>원인

- `max_file_bytes` 2 MB(`:58`)를 넘으면 앞 2 MB 만 보내고(`:373-376`) 프론트는 토스트만 띄운다. 나머지를 볼 방법이 없다. 바이트 단위로 자르므로 UTF-8 다중 바이트 글자 중간에서 잘리면 `utf-8` 디코드가 실패하고 `cp949`/`latin-1` 로 잘못 해석될 수 있다(`:380-385`).
- 본문을 JSON 문자열에 담아 보낸다(`:383`, `_send` 의 `json.dumps`). 서버는 바이트 → 문자열 → 이스케이프된 JSON → 바이트로 사본을 3번 만들고, 브라우저는 다시 JSON 파싱을 한다.
- 큰 파일·긴 줄용 에디터 설정이 없다(`source.html:611-619`). 한 줄짜리 2 MB 파일은 키 입력마다 그 줄 전체를 다시 처리한다.

### <span class="n3">4.9.2</span>근거

상한을 풀면 50 MB 파일이 서버 397 ms(54.6 MB JSON) + 화면 913 ms, 힙 132 MB. 한 줄 JSON 의 타이핑 지연은 키당 93 ~ 114 ms(기준 22 ms), 가로 스크롤 최대 425 ms 프레임.

</div>
</div>
<div class="it">
<input type="checkbox" id="i4-10a" class="ca" style="display:none">
<input type="checkbox" id="i4-10b" class="cb" style="display:none">
<label for="i4-10a" class="ih la"><span class="n">4.10</span><b>🟪 Markdown 미리보기</b> <span class="sub"><code>source.html:575-577</code> · <code>744</code> · <code>801-803</code></span></label>
<label for="i4-10b" class="ih lb"><span class="n">4.10</span><b>🟪 Markdown 미리보기</b> <span class="sub"><code>source.html:575-577</code> · <code>744</code> · <code>801-803</code></span></label>
<div class="ib">

### <span class="n3">4.10.1</span>원인

- Monaco 의 AMD `loader.js`(`:575`)가 `marked.min.js`(`:577`)보다 먼저 로드된다. marked 의 UMD 래퍼는 `define.amd` 가 있으면 전역 대신 AMD 모듈로 등록하므로 `window.marked` 가 생기지 않는다. 그래서 `typeof marked !== 'undefined'`(`:801`)가 항상 거짓이고, .md 파일은 미리보기 대신 Monaco 에 Markdown 소스로 열린다. **성능 이전에 기능 버그다.**
- 고치더라도 `switchTabIn` 이 Markdown 탭으로 돌아올 때마다 저장해 둔 HTML 문자열 전체를 `innerHTML` 로 다시 넣는다(`:744`). 스크롤 위치도 잃는다. `marked.parse` 는 메인 스레드에서 동기로 돈다(`:803`).

### <span class="n3">4.10.2</span>근거

헤드리스·실제 WebView2 모두 `typeof marked` = `undefined`. 2 MB Markdown 이 15.8만 줄 Monaco 모델로 열려 힙이 54 ~ 87 MB 늘었다.

</div>
</div>

---

<a id="cat-5"></a>

# <span class="num">5</span> 개선안 <span class="hctl"><a href="#toc">↑ 목차로</a></span>

> 번호는 4장 병목 번호와 같다. 예상 효과는 이번 측정값을 기준으로 한 추정이며 적용 후 같은 스크립트로 다시 재야 한다.

<table>
<thead><tr><th style="white-space:nowrap">#</th><th style="white-space:nowrap">개선안</th><th style="white-space:nowrap">예상 효과</th><th style="white-space:nowrap">난이도</th><th style="white-space:nowrap">수정 파일</th></tr></thead>
<tbody>
<tr style="background:#f8f9fa"><td>1</td><td><code>HTTPServer</code> → <code>ThreadingHTTPServer</code> (<code>daemon_threads=True</code>). 공유 전역(<code>_files_cache</code>, <code>_CONTENT_CACHE</code>, <code>SETTINGS</code>)은 교체 대입 방식이라 GIL 아래서 대체로 안전하나, 인덱스 재구축에는 Lock 하나를 둔다</td><td>검색 중 트리·파일 열기 9.1 s → 단독 수준(0.3 s)</td><td>하</td><td><code>reado.py</code>, <code>server.py</code></td></tr>
<tr style="background:#ffffff"><td>2</td><td>본문 캐시를 <b>바이트 예산 LRU</b>(<code>OrderedDict</code> + <code>move_to_end</code>, 예: 256 MB)로 바꾸고 stat 은 <code>os.stat</code> 1회로. rg 를 쓰게 되면 캐시 자체를 줄인다</td><td>반복 검색 7.1 s → 2 s 안팎(2.5만 파일 전부 적중 시)</td><td>하</td><td><code>server.py</code></td></tr>
<tr style="background:#f8f9fa"><td>3</td><td><b>rg.exe 동봉</b>(약 5 MB, <code>--add-binary</code>)하고 <code>RIPGREP</code> 을 번들 경로 우선으로. rg 경로는 <code>Popen</code> 으로 줄 단위 스트리밍해 <code>max_results</code> 에서 프로세스를 종료, <code>--max-columns 500</code> 추가. 대체 경로는 바이트 수준 사전 필터(대소문자 무시 리터럴은 <code>lower()</code> 후 <code>in</code>)와 단어 단위를 <code>\b</code> 로</td><td>검색 7 ~ 32 s → 1 s 미만(rg 일반적 수치), 대체 경로도 수 배</td><td>중</td><td><code>server.py</code>, <code>build.bat</code>, <code>reado.spec</code>, <code>fetch-vendor.py</code></td></tr>
<tr style="background:#ffffff"><td>4</td><td><code>goto_symbol</code> 을 rg <code>-w -l</code>(또는 3의 병렬 경로)로 후보 파일만 고른 뒤 그 파일에만 <code>decl_pat</code> 적용. 선언 여러 개일 때 결과를 그대로 넘겨 재검색 생략</td><td>9 ~ 10 s → 1 s 미만</td><td>중</td><td><code>server.py</code>, <code>source.html</code>(gotoDefinition)</td></tr>
<tr style="background:#f8f9fa"><td>5</td><td>onefile → <b>onedir</b> 빌드(압축 해제 없음, 설치 폴더나 zip 배포). <code>create_window</code> 를 먼저 호출하고 서버 준비는 병렬로(서버는 import 후 수 ms 면 뜸). 필요하면 <code>webview.start(private_mode=False, storage_path=…)</code> 로 HTTP 캐시 유지</td><td>사용 가능까지 6.4 ~ 8.2 s → 약 3 ~ 4 s</td><td>하 ~ 중</td><td><code>build.bat</code>, <code>reado.spec</code>, <code>reado.py</code></td></tr>
<tr style="background:#ffffff"><td>6</td><td>확장자 집합·무시 패턴을 설정 저장 시 한 번만 계산(정확 일치는 <code>frozenset</code>, glob 은 하나의 정규식으로 합침). 인덱스는 만료돼도 기존 목록을 바로 돌려주고 백그라운드 스레드로 재구축(stale-while-revalidate). <code>os.walk</code> 대신 <code>os.scandir</code> 재귀</td><td>Quick Open 첫 입력 1.7 s → 30 ms, 인덱스 구축 자체도 30 ~ 50% 단축</td><td>하</td><td><code>server.py</code></td></tr>
<tr style="background:#f8f9fa"><td>7</td><td>서버 <code>list_dir</code> 를 <code>os.scandir</code> + <code>entry.is_dir()</code>/<code>entry.stat()</code> 로. 프론트는 <code>DocumentFragment</code> 에 모아 한 번에 붙이고, 클릭은 <code>#tree</code> 한 곳에서 이벤트 위임. 1,000항목 이상은 가상 스크롤 또는 “더 보기”</td><td>5,200항목 707 ms → 200 ms 안팎</td><td>하(서버) · 중(가상화)</td><td><code>server.py</code>, <code>source.html</code></td></tr>
<tr style="background:#ffffff"><td>8</td><td>언어 서비스 끄기: <code>monaco.languages.typescript.javascriptDefaults/typescriptDefaults.setModeConfiguration</code> 로 진단·완성 비활성 또는 <code>setDiagnosticsOptions({noSemanticValidation, noSyntaxValidation})</code>, JSON 은 <code>jsonDefaults.setDiagnosticsOptions({validate:false})</code>. <code>fetch-vendor.py</code> 에서 <code>vs/language/*</code> 와 다국어 nls 를 빼고 빌드</td><td>.js 첫 열기 4.6 MB 로드·워커 제거, vendor 15 → 약 7.5 MB, exe 약 3 ~ 4 MB 감소</td><td>하</td><td><code>source.html</code>, <code>fetch-vendor.py</code></td></tr>
<tr style="background:#f8f9fa"><td>9</td><td>파일 본문은 JSON 대신 <code>text/plain</code> 원문으로 보내고 메타(크기·절단·인코딩)는 헤더로. 절단은 줄 경계에서 하고 “전체 불러오기” 버튼 제공. 큰 파일(예: 5 MB 이상 또는 최장 줄 1만 자 이상)은 <code>plaintext</code> 로 열고 <code>folding</code>·<code>renderWhitespace</code>·<code>wordWrap</code> 끄기, <code>maxTokenizationLineLength</code> 조정</td><td>50 MB 열기 1.3 s → 약 0.8 s, 서버 메모리 사본 3 → 1개, 한 줄 파일 입력 지연 완화</td><td>중</td><td><code>server.py</code>, <code>source.html</code></td></tr>
<tr style="background:#ffffff"><td>10</td><td><code>marked.min.js</code> 를 <code>loader.js</code> <b>앞</b>으로 옮기거나 <code>require(['vs/../marked.min'])</code> 로 로드. 탭에 HTML 문자열 대신 렌더된 DOM 요소를 보관해 전환 시 교체만, 스크롤 위치 저장. 큰 문서는 워커에서 파싱</td><td>Markdown 미리보기 복구, 탭 복귀 비용 문서 크기와 무관하게</td><td>하</td><td><code>source.html</code></td></tr>
</tbody>
</table>

### 그 밖의 작은 개선 (Top 10 밖)

- **심볼 목록(`@`)**: `runSymbolSearch` 가 `model.getValue()` 전체 복사 + `split` + 줄마다 정규식(`source.html:1466-1480`) — 2 MB 파일에서 442 ms. `model.getLineContent(i)` 순회 또는 결과 캐시로 줄일 수 있다.
- **Quick Open·심볼 목록 키 이동**: 방향키마다 `renderQO` 가 목록 전체를 다시 만든다(`:1536-1542`) — 4,000개 기준 17 ms. 선택 클래스만 바꾸면 된다.
- **탭 바**: `renderTabsFor` 가 탭 전환마다 모든 탭 DOM 을 다시 만든다(`:686`). 탭 수가 적으면 영향은 미미하다.
- **`/vendor/` 응답**: 요청마다 파일 전체를 디스크에서 읽는다(`server.py:733-734`). 실행마다 7 MB 정도라 개선안 5의 캐시 유지가 더 효과적이다.

---

<a id="cat-6"></a>

# <span class="num">6</span> 권장 적용 순서 <span class="hctl"><a href="#toc">↑ 목차로</a></span>

> 효과 대비 위험이 낮은 것부터. 1단계와 2단계는 서버 파일만 고치므로 source.html 을 수정 중인 세션과 충돌하지 않는다.

<div style="font-family:'Noto Sans KR',sans-serif">
<div class="lay">
 <div class="cd" style="border-top-color:#1a4d8f"><b><span class="st">1</span> 서버 응답성</b><span class="k">개선안 1 · 2 · 6</span><span class="s">server.py · reado.py 만. 반나절. 검색 중 멈춤 해소, 반복 검색·Quick Open 첫 입력 단축</span></div>
 <div class="ar">→</div>
 <div class="cd" style="border-top-color:#1a4d8f"><b><span class="st">2</span> 검색 엔진</b><span class="k">개선안 3 · 4</span><span class="s">rg 동봉 + 스트리밍, goto 를 rg 기반으로. 1 ~ 2일. 검색·정의로 이동 10초대 → 1초 미만</span></div>
 <div class="ar">→</div>
 <div class="cd" style="border-top-color:#7c3aed"><b><span class="st">3</span> 프론트 정리</b><span class="k">개선안 10 · 8 · 7</span><span class="s">source.html 수정 세션과 조율해서. Markdown 버그부터. 언어 워커 끄기, 트리 위임·프래그먼트</span></div>
 <div class="ar">→</div>
 <div class="cd" style="border-top-color:#cf7700"><b><span class="st">4</span> 빌드·대용량</b><span class="k">개선안 5 · 9</span><span class="s">배포 방식(onedir) 결정 필요. 파일 전송 형식 변경은 서버·프론트 동시 수정</span></div>
</div>
</div>

### 단계별 메모

- **1단계**를 먼저 하는 이유: 한 줄 수준 변경(`ThreadingHTTPServer`)으로 가장 큰 체감 문제(앱 전체 멈춤)가 사라지고, 이후 검색 개선을 측정할 때도 다른 요청이 섞이지 않는다.
- **3단계의 개선안 10**은 성능이 아니라 기능 버그 수정이라 source.html 담당 세션에 우선 전달할 만하다.
- **4단계의 개선안 5**는 배포 형태(단일 exe 유지 여부)를 정해야 하므로 사용자 결정이 필요하다. 단일 exe 를 유지하더라도 `create_window` 를 먼저 호출하는 부분은 바로 적용할 수 있다.
- 각 단계 후 부록 A.2 의 스크립트로 같은 코퍼스를 다시 재서 이 문서의 표와 비교한다.

---

<a id="cat-7"></a>

# <span class="num">7</span> 2단계 A 적용 결과 — 서버 보안·성능 <span class="hctl"><a href="#toc">↑ 목차로</a></span>

> 2026-10-07 적용. 수정 파일은 `server.py`, `reado.py`, `fetch-vendor.py`, `build.bat`, `.gitignore` 다섯 개이고 `source.html` 은 한 줄도 고치지 않았다. 아래 수치는 같은 PC·같은 코퍼스(25,014 파일)에서 원본과 수정본을 연달아 잰 값이다.

<div class="it">
<input type="checkbox" id="i7-1a" class="ca" style="display:none">
<input type="checkbox" id="i7-1b" class="cb" style="display:none">
<label for="i7-1a" class="ih la"><span class="n">7.1</span><b>전/후 벤치마크</b> <span class="sub">중앙값 · 3 ~ 5회</span></label>
<label for="i7-1b" class="ih lb"><span class="n">7.1</span><b>전/후 벤치마크</b> <span class="sub">중앙값 · 3 ~ 5회</span></label>
<div class="ib">

<table>
<thead><tr><th style="white-space:nowrap">영역</th><th style="white-space:nowrap">항목</th><th style="white-space:nowrap">전</th><th style="white-space:nowrap">후 (rg)</th><th style="white-space:nowrap">후 (Python 폴백)</th></tr></thead>
<tbody>
<tr style="background:#f8f9fa"><td rowspan="1" valign="top"><b>🟦 동시성</b></td><td>콜드 검색 중 트리(5,700항목) 요청</td><td>15,521 ms</td><td>—</td><td><b>117 ms</b></td></tr>
<tr style="background:#ffffff"><td rowspan="7" valign="top"><b>🟦 찾기</b></td><td>일치 없음, 콜드</td><td>13,624 ms</td><td><b>1,982 ms</b></td><td>11,724 ms</td></tr>
<tr style="background:#ffffff"><td>일치 없음, 웜</td><td>11,888 ms</td><td><b>1,464 ms</b></td><td>3,042 ms</td></tr>
<tr style="background:#ffffff"><td><code>payment</code> (500건 상한)</td><td>1,182 ms</td><td><b>302 ms</b></td><td>1,125 ms</td></tr>
<tr style="background:#ffffff"><td>정규식 <code>method\d+\(</code></td><td>1,022 ms</td><td><b>208 ms</b></td><td>1,485 ms</td></tr>
<tr style="background:#ffffff"><td>단어 단위, 일치 없음</td><td>21,310 ms</td><td><b>1,588 ms</b></td><td>2,896 ms</td></tr>
<tr style="background:#ffffff"><td>단어 단위, 일치 2건</td><td>19,531 ms</td><td><b>1,383 ms</b></td><td>3,156 ms</td></tr>
<tr style="background:#ffffff"><td>본문 캐시</td><td>4,514개(상한 5,000)</td><td>—</td><td>25,014개 · 130 MB(예산 256 MB)</td></tr>
<tr style="background:#f8f9fa"><td rowspan="3" valign="top"><b>🟦 정의로 이동</b></td><td>클래스 선언 1건</td><td>15,344 ms</td><td><b>1,588 ms</b></td><td>2,231 ms</td></tr>
<tr style="background:#f8f9fa"><td>일치 많음 <code>method24</code></td><td>14,697 ms</td><td><b>1,662 ms</b></td><td>2,683 ms</td></tr>
<tr style="background:#f8f9fa"><td>일치 없음</td><td>15,099 ms</td><td><b>1,689 ms</b></td><td>2,611 ms</td></tr>
<tr style="background:#ffffff"><td rowspan="5" valign="top"><b>🟦 인덱스·트리</b></td><td>Quick Open 콜드(인덱스 구축)</td><td>2,214 ms</td><td colspan="2"><b>909 ms</b></td></tr>
<tr style="background:#ffffff"><td>인덱스 만료(60초) 후 첫 요청</td><td>2,169 ms</td><td colspan="2"><b>36 ms</b> (백그라운드 재구축)</td></tr>
<tr style="background:#ffffff"><td>Quick Open 웜 <code>Svc01</code> / <code>*svc*java</code></td><td>53 / 123 ms</td><td colspan="2">25 / 118 ms</td></tr>
<tr style="background:#ffffff"><td>필터 함수 10만 회</td><td>1,746 ms</td><td colspan="2">520 ms</td></tr>
<tr style="background:#ffffff"><td>트리 5,700항목 (<code>/api/tree</code>)</td><td>430 ms</td><td colspan="2"><b>63 ms</b></td></tr>
<tr style="background:#f8f9fa"><td rowspan="2" valign="top"><b>🟧 번들</b></td><td><code>reado.exe</code> 크기</td><td>22.6 MB</td><td colspan="2">24.6 MB (rg.exe 5.4 MB 압축 포함)</td></tr>
<tr style="background:#f8f9fa"><td>실제 앱 검색 <code>class</code> (<code>c:\Projects</code>)</td><td>—</td><td colspan="2">WebView2 소스 실행 252 ms · 테스트 빌드 exe 148 ~ 829 ms, <code>engine: rg</code></td></tr>
</tbody>
</table>

- 남은 rg 시간 1.4 ~ 2 s 는 대부분 rg 프로세스가 166 MB 를 훑는 비용이다(Windows 백신 실시간 검사 포함). 500건 상한에 걸리는 검색은 그 자리에서 rg 를 종료하므로 0.2 ~ 0.3 s 다.
- 이번 측정에서 원본의 콜드 검색은 13.6 s 였다(2장 측정 때는 32.6 s). 차이는 OS 파일 캐시 상태다.
- Python 폴백 정규식(1,485 ms)이 원본(1,022 ms)보다 느린 것은 스레드를 32 → 8개로 줄였기 때문이다. 같은 실험에서 일치 없는 검색 속도는 같았고 검색 중 다른 요청의 대기는 4.7 s → 1.9 s 로 줄었다.

</div>
</div>
<div class="it">
<input type="checkbox" id="i7-2a" class="ca" style="display:none">
<input type="checkbox" id="i7-2b" class="cb" style="display:none">
<label for="i7-2a" class="ih la"><span class="n">7.2</span><b>변경 내용</b> <span class="sub">4장 병목 번호 기준</span></label>
<label for="i7-2b" class="ih lb"><span class="n">7.2</span><b>변경 내용</b> <span class="sub">4장 병목 번호 기준</span></label>
<div class="ib">

<table>
<thead><tr><th style="white-space:nowrap">#</th><th style="white-space:nowrap">변경</th><th style="white-space:nowrap">위치</th></tr></thead>
<tbody>
<tr style="background:#f8f9fa"><td>보안</td><td>Host·Origin·Sec-Fetch-Site 검사(모든 요청), POST 는 CSRF 토큰 + JSON + 본문 상한, HTML 에 <code>X-Frame-Options: DENY</code>, 전 응답 <code>nosniff</code>, 루프백 외 바인딩 거부, Windows 에서 <code>SO_REUSEADDR</code> 해제</td><td><code>server.py</code> request guards · <code>make_server</code></td></tr>
<tr style="background:#ffffff"><td>1</td><td><code>ThreadingHTTPServer</code>(데몬 스레드). 클라이언트가 끊은 요청의 traceback 은 숨김(윈도 exe 에 stderr 없음)</td><td><code>ReadOServer</code>, <code>reado.py:68-69</code></td></tr>
<tr style="background:#f8f9fa"><td>2</td><td>본문 캐시를 바이트 예산 LRU(256 MB)로, stat 1회</td><td><code>_ByteLRU</code>, <code>_get_content</code></td></tr>
<tr style="background:#ffffff"><td>3</td><td>rg 14.1.1 번들(<code>vendor/rg/rg.exe</code>, SHA-256 고정) · 줄 단위 스트리밍 · 상한 도달 시 rg 종료 · 60 s 타임아웃 · 더 새 검색이 오면 이전 검색 중단 · cp949 줄 디코드 · 바이트→문자 열 위치 변환 · 2,000자 넘는 줄은 일치 주변만 · 근접 일치의 문맥 줄 누락(원래 rg 경로 버그) 수정 · <code>--no-ignore --hidden</code> 으로 ReadO 설정만 따름. Python 폴백은 리터럴 사전 필터, 단어 단위 <code>\b</code>, 스레드 8개</td><td><code>_rg_events</code>, <code>_ripgrep_search</code>, <code>find_in_files</code>, <code>fetch-vendor.py</code>, <code>build.bat</code></td></tr>
<tr style="background:#f8f9fa"><td>4</td><td>정의로 이동을 rg 스트리밍으로(선언 최대 200 · 검사 5,000줄). rg 가 없으면 병렬 Python 폴백(원본과 같은 결과)</td><td><code>_goto_rg</code>, <code>goto_symbol</code></td></tr>
<tr style="background:#ffffff"><td>6</td><td>확장자·무시 패턴을 설정값 단위로 미리 계산(glob 은 정규식 하나로). 인덱스는 <code>os.scandir</code> 로 걷고, 만료되면 기존 목록을 돌려주며 백그라운드에서 재구축</td><td><code>_filters</code>, <code>_walk_files</code>, <code>_ensure_index</code></td></tr>
<tr style="background:#f8f9fa"><td>7(서버)</td><td><code>list_dir</code> 를 <code>os.scandir</code> 로</td><td><code>list_dir</code></td></tr>
<tr style="background:#ffffff"><td>9(일부)</td><td>2 MB 절단을 줄 경계(또는 UTF-8 글자 경계)에서</td><td><code>_cut_at_boundary</code></td></tr>
</tbody>
</table>

이번 단계에서 하지 않은 것: <span class="cn">5</span> onedir 전환(보류 지시), <span class="cn">8</span> 언어 워커·vendor 정리와 <span class="cn">10</span> Markdown(프론트 담당), <span class="cn">9</span> 의 원문 전송 형식 변경(프론트 동시 수정 필요). <code>reado.spec</code> 은 <code>build.bat</code> 이 매번 지우고 다시 만드는 생성 파일이고 <code>vendor</code> 전체를 이미 포함하므로 수정하지 않았다.

</div>
</div>
<div class="it">
<input type="checkbox" id="i7-3a" class="ca" style="display:none">
<input type="checkbox" id="i7-3b" class="cb" style="display:none">
<label for="i7-3a" class="ih la"><span class="n">7.3</span><b>쓰기 API 공통 가드 사용법</b> <span class="sub">에디터 담당용</span></label>
<label for="i7-3b" class="ih lb"><span class="n">7.3</span><b>쓰기 API 공통 가드 사용법</b> <span class="sub">에디터 담당용</span></label>
<div class="ib">

### <span class="n3">7.3.1</span>서버 쪽

`@write_api` 로 등록하면 Host·Origin·토큰·Content-Type·본문 크기 검사와 JSON 파싱이 먼저 끝난 뒤 함수가 불린다. 경로는 반드시 `resolve_write_path` 를 거치고, 기록은 `atomic_write` 로 한다.

```python
@write_api("/api/save", max_body=50_000_000)
def api_save(data):
    full, err = resolve_write_path(data.get("path"), must_exist=True)
    if err:
        return 400, {"error": err}
    mtime, err = atomic_write(full, data["text"].encode("utf-8"),
                              expect_mtime_ns=data.get("mtime_ns"))
    return (409, {"error": err}) if err else {"mtime_ns": mtime}
```

<table>
<thead><tr><th style="white-space:nowrap">함수</th><th style="white-space:nowrap">하는 일</th></tr></thead>
<tbody>
<tr style="background:#f8f9fa"><td><code>write_api(path, max_body)</code></td><td>POST 라우트 등록. 함수는 dict 를 받고 dict 또는 <code>(상태코드, dict)</code> 를 돌려준다. 실패 시 403 · 413 · 400 은 가드가 응답</td></tr>
<tr style="background:#ffffff"><td><code>resolve_write_path(rel, must_exist)</code></td><td>symlink·junction 을 풀어도 base_dir 안인지, 무시 대상(.git, node_modules …)·허용 안 된 확장자·Windows 금지 이름(<code>CON</code>, <code>a:b</code>, 끝 점/공백)·없는 상위 폴더·폴더 대상을 거부. <code>(절대경로, None)</code> 또는 <code>(None, 오류)</code></td></tr>
<tr style="background:#f8f9fa"><td><code>atomic_write(full, bytes, expect_mtime_ns)</code></td><td>같은 폴더 임시 파일 + <code>os.replace</code>. <code>expect_mtime_ns</code> 와 디스크가 다르면 쓰지 않고 <code>"file changed on disk"</code>. 성공 시 새 mtime_ns</td></tr>
<tr style="background:#ffffff"><td><code>notify_file_changed(full)</code></td><td>검색 캐시·Quick Open 인덱스 갱신. <code>atomic_write</code> 는 자동 호출, 삭제·이름 변경 API 는 직접 호출</td></tr>
<tr style="background:#f8f9fa"><td><code>check_read_request</code> / <code>check_write_request</code></td><td>라우트 밖에서 같은 검사가 필요할 때 쓰는 원본 함수(오류 문자열 또는 None)</td></tr>
</tbody>
</table>

### <span class="n3">7.3.2</span>프론트 쪽

할 일이 없다. 서버가 `source.html` 을 내보낼 때 `</head>` 앞에 토큰 `<meta name="reado-token">` 과 `window.READO_TOKEN`, 그리고 같은 출처의 GET/HEAD 가 아닌 `fetch()` 에 `X-ReadO-Token` 헤더를 붙이는 래퍼를 끼워 넣는다. 평소처럼 `fetch('/api/save', {method:'POST', headers:{'Content-Type':'application/json'}, body})` 로 부르면 된다. `XMLHttpRequest` 나 폼 전송을 쓰면 헤더를 직접 붙여야 한다. 응답의 `mtime_ns` 를 보관했다가 다음 저장 때 돌려보내면 외부 변경 충돌을 막을 수 있다.

</div>
</div>
<div class="it">
<input type="checkbox" id="i7-4a" class="ca" style="display:none">
<input type="checkbox" id="i7-4b" class="cb" style="display:none">
<label for="i7-4a" class="ih la"><span class="n">7.4</span><b>검증</b> <span class="sub">서버 83항목 · 브라우저 15항목 · 실제 WebView2 · 테스트 빌드 exe</span></label>
<label for="i7-4b" class="ih lb"><span class="n">7.4</span><b>검증</b> <span class="sub">서버 83항목 · 브라우저 15항목 · 실제 WebView2 · 테스트 빌드 exe</span></label>
<div class="ib">

<table>
<thead><tr><th style="white-space:nowrap">스크립트</th><th style="white-space:nowrap">확인 내용</th><th style="white-space:nowrap">결과</th></tr></thead>
<tbody>
<tr style="background:#f8f9fa"><td><code>verify_server.py</code></td><td>읽기·쓰기 가드 각 경우, <code>resolve_write_path</code> 16경우(junction 탈출 포함), <code>atomic_write</code> 충돌·임시 파일·캐시 무효화, 원본과 결과 비교(필터·인덱스 순서·트리·파일·Quick Open·검색 5종의 Python/rg·문맥 줄·정의로 이동), cp949·긴 줄, 검색 중 트리 응답, 이전 검색 취소, 바인딩</td><td>83 / 83 통과</td></tr>
<tr style="background:#ffffff"><td><code>smoke_front.py</code></td><td>원본 <code>source.html</code> 로 headless Chromium: 로드·파일 열기·찾기·Quick Open·정의로 이동·설정 저장(UI 경로)·<code>Request</code> 객체 POST, 다른 출처 페이지의 JSON POST·no-cors POST·폼 전송·읽기 차단</td><td>15 / 15 통과</td></tr>
<tr style="background:#f8f9fa"><td><code>smoke_webview.py</code> / <code>smoke_exe.py</code></td><td>실제 WebView2 에서 소스 실행과 scratchpad 에 따로 만든 exe: 토큰·트리·rg 검색·가드 응답</td><td>통과(<code>dist/</code> 는 건드리지 않음)</td></tr>
<tr style="background:#ffffff"><td><code>bench_ab.py</code></td><td>7.1 의 전/후 수치</td><td>—</td></tr>
</tbody>
</table>

### <span class="n3">7.4.1</span>검증 중 발견한 기존 문제 (수정하지 않음)

- **정의로 이동 후 커서가 1행으로 간다** — `gotoInEditor`(`source.html:1015-1030`)가 `findMatches` 를 대소문자 무시로 불러 `package …svc01000;` 같은 소문자 일치까지 선택하고, 그 첫 선택이 주 커서가 된다. 서버 응답은 원본과 같다(선언 3행). 프론트 담당에게 전달할 항목이다.
- rg 가 확장자 없는 파일(Dockerfile 등)은 검색하지 않는다. 확장자 glob 으로 거르기 때문이며, rg 가 PATH 에 있던 PC 에서는 원래 그랬다.

</div>
</div>


<hr style="margin:4.5em 0 2em">

<a id="appendix"></a>

<details>
<summary class="apx"><span class="num">A</span> 부록: 원시 로그 · 스크립트 · 부수 발견 <span class="hctl"><a href="#toc">↑ 목차로</a></span></summary>

## A.1 원시 측정 로그 (발췌)

```text
[server] rg: None
GET / (source.html)                     median   16.1 ms  bytes 66,355
GET /vendor editor.main.js (3.4MB)      median   21.1 ms  bytes 3,469,378
tree: flat (5000 files+500 png+200 dirs) median  338.0 ms  bytes 295,027
file: big_50mb.java (cap lifted)        median  396.9 ms  bytes 54,591,199
files: q=Svc01 COLD (index build)               1695.3 ms  indexed=25007
_walk_files alone                               1335.0 ms
_is_text_file x100k                              647.9 ms
_is_ignored x100k                                308.2 ms
search: no-hit COLD (reads all files)          32630.7 ms
  content cache entries / traced mem           4503 entries, 24.0 MB (peak 60.5 MB)
search: no-hit warm (cache)             median 7148.1 ms
search: 'payment' (500 cap) warm        median 1695.4 ms
search: whole-word 'Svc0100' warm       median 12288.4 ms
goto: Svc0100 warm                      median 8963.6 ms
goto: method24 (many hits) warm         median 10087.4 ms
tree(flat) issued 0.2s into a COLD search      9103.1 ms  (search took 8954.5 ms)
[load run1] DCL 107ms tree 163ms monaco-ready 628ms painted 646ms req=15 bytes=6,965,875 heap=14.5MB
[tree] expand flat (5200 nodes) 707ms DOM elems=21216
[js] open sample.js 213ms; extra: tsMode.js(23,674) workerMain.js(339,604)x2 tsWorker.js(4,602,226)
[open fresh, cap lifted] big_50mb.java: 913ms lines=717,537 heap=132MB
[md] typeof marked = undefined
[exe run2] server-port 2595ms webview-cdp 4890ms monaco-ready 6427ms tree 6439ms
           processes {'reado.exe': 2, 'msedgewebview2.exe': 6} WorkingSet 583MB Private 337MB
```

## A.2 측정 스크립트

프로젝트 밖 세션 scratchpad(`%TEMP%\claude\C--ClaudeCode-ReadO\<session>\scratchpad\`)에 있다. 프로젝트에는 아무것도 추가하지 않았다.

| 파일 | 내용 |
|---|---|
| `gen_corpus.py <dir>` | 2.1 의 합성 코퍼스 생성(약 50초) |
| `bench_server.py <corpus>` | 3.2 · 3.3 서버 API · 함수 단위 · 동시성 측정 |
| `bench_front.py <corpus>` | 3.4 · 3.5 headless Chromium 로드 · 트리 · 열기 · 스크롤 · 타이핑 · 렌더 |
| `bench_front2.py <corpus>` | 언어 워커 로드, 탭 메모리, 상한 해제 시 새 페이지 열기 |
| `bench_exe.py [회수]` | 3.1 · 3.6 exe 시작 시간 + 실제 WebView2 CDP + 프로세스 메모리 |
| `bench_ab.py <server_dir> <corpus> [라벨]` | 7.1 전/후 비교(원본 사본은 scratchpad `before/`) |
| `verify_server.py <corpus>` | 7.4 서버 동작·보안 검증 83항목 |
| `smoke_front.py <corpus>` · `smoke_webview.py` · `smoke_exe.py <exe>` | 7.4 브라우저·실제 WebView2·exe 확인 |

`bench_exe.py` 는 `%APPDATA%\ReadO\config.json` 이 없으면 exe 가 기본 설정 파일을 만든다. 측정 뒤 지워야 사용자 환경이 그대로 유지된다.

## A.3 부수 발견 (성능 외)

| 위치 | 내용 |
|---|---|
| `source.html:575-577`, `801` | marked 가 AMD 모듈로 등록돼 전역 `marked` 가 없음 → Markdown 미리보기가 한 번도 동작하지 않음(4.10) |
| `server.py:373-385` | 2 MB 절단이 바이트 단위라 UTF-8 글자 중간에서 잘리면 <code>cp949</code>/<code>latin-1</code> 로 잘못 디코드될 수 있음 |
| `reado.spec:29` | <code>upx=True</code> 이지만 UPX 미설치로 효과 없음 |
| `server.py:438-439` | rg 경로는 <code>--max-filesize 5M</code> 인데 파일 열기 상한은 2 MB — 검색 결과로 연 파일에서 해당 줄이 잘려 보이지 않을 수 있음 |

</details>
