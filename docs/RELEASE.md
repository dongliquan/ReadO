# ReadO 릴리스 절차 — 빌드·테스트·dist 교체·버전

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

**대상**: 새 빌드를 `dist\reado.exe`로 내보내기까지의 절차  
**원칙**: 테스트를 통과한 빌드만 `dist`에 넣는다. 실행 중인 ReadO는 정상 닫기만 하고, 저장 안 된 편집이 있으면 교체를 멈춘다. 프로세스를 이름·경로로 일괄 종료하지 않는다.

<a id="toc"></a>

## 목차

- [**1. 전체 흐름**](#cat-1)
- [**2. 빌드와 테스트 — scripts/build_test.py**](#cat-2)
- [**3. dist 교체 — scripts/swap_dist.py**](#cat-3)
- [**4. 버전 끊기 — CHANGELOG**](#cat-4)
- [**5. 폴더**](#cat-5)

---

<a id="cat-1"></a>

# <span class="num">1</span> 전체 흐름 <span class="hctl"><a href="#toc">↑ 목차로</a></span>

> 빌드는 항상 `dist-next`에 한다. `dist`는 사용 중일 수 있으므로 교체 스크립트만 건드린다.

<div class="lay">
 <div class="cd" style="border-top-color:#6c8ebf"><b><span class="st">1</span> 빌드·테스트</b><span class="k">python scripts/build_test.py</span><span class="s">dist-next에 빌드하고 자동 테스트 4종을 차례로 실행한다</span></div>
 <div class="ar">→</div>
 <div class="cd" style="border-top-color:#d6b656"><b><span class="st">2</span> 수동 확인</b><span class="k">README · Manual checks</span><span class="s">자동 테스트로 못 하는 것(드래그 앤 드롭, 연결 프로그램, 타이틀바 등)을 dist-next exe로 확인</span></div>
 <div class="ar">→</div>
 <div class="cd" style="border-top-color:#82b366"><b><span class="st">3</span> dist 교체</b><span class="k">python scripts/swap_dist.py</span><span class="s">먼저 dry run으로 할 일을 보고, --apply --expect &lt;해시&gt;로 실행</span></div>
 <div class="ar">→</div>
 <div class="cd" style="border-top-color:#9673a6"><b><span class="st">4</span> 버전 끊기</b><span class="k">CHANGELOG.md</span><span class="s">[Unreleased]를 새 버전 항목으로 옮기고 README 버전을 맞춘다. 태그는 매니저 결정 후</span></div>
</div>

| 단계 | 누가 실행하나 | 되돌리기 |
|---|---|---|
| <span class="st">1</span> 빌드·테스트 | 작업 세션 | 필요 없음(`dist-next`만 바뀜) |
| <span class="st">2</span> 수동 확인 | 매니저 또는 작업 세션 | 필요 없음 |
| <span class="st">3</span> dist 교체 | 매니저 지시가 있을 때만 | `dist-prev\reado.exe`를 `dist`로 복사 |
| <span class="st">4</span> 버전 끊기 | 작업 세션(로컬 커밋), 태그·push는 매니저 지시 후 | 커밋 되돌리기 |

---

<a id="cat-2"></a>

# <span class="num">2</span> 빌드와 테스트 — scripts/build_test.py <span class="hctl"><a href="#toc">↑ 목차로</a></span>

> 한 번 실행으로 `build.bat dist-next`와 자동 테스트 전부를 돌리고, 마지막에 요약과 다음에 실행할 교체 명령을 출력한다.

### <span class="n3">2.1</span> 실행

```bash
python scripts/build_test.py                # 빌드 + 테스트 전부
python scripts/build_test.py --skip-build   # 이미 있는 dist-next로 테스트만
python scripts/build_test.py --gitfx DIR    # ui_git_smoke용 git 픽스처 폴더(없으면 만든다)
```

### <span class="n3">2.2</span> 실행 순서

| 순서 | 단계 | 통과 기준 |
|---|---|---|
| <span class="st">1</span> | 사전 확인: HEAD, 커밋 안 된 변경(빌드에 함께 들어간다고 알림), `dist-next`에서 실행 중인 ReadO가 있으면 중단 | — |
| <span class="st">2</span> | `build.bat dist-next` | `dist-next\reado.exe` 생성 |
| <span class="st">3</span> | `tests/git_fixture.py` — 픽스처 폴더가 없을 때만 | 종료 코드 0 |
| <span class="st">4</span> | `tests/verify_editor.py` | `N / N passed` |
| <span class="st">5</span> | `tests/test_git.py` | `all passed` |
| <span class="st">6</span> | `tests/ui_git_smoke.py <픽스처>` | `all passed` |
| <span class="st">7</span> | `tests/exe_startup.py dist-next\reado.exe` | `all passed` |

- 테스트는 **하나씩** 돌린다. 동시에 돌리면 verify_editor의 검색 단계가 검색 동시 실행 한도(2)에 걸려 `429`를 받는다.
- 실패한 테스트는 한 번 더 돌린다. 다시 통과하면 요약에 `passed on retry`로 남긴다. 불안정한 단계를 숨기지 않기 위해서다.
- 로그는 `%TEMP%\reado-release\<시각>\<단계>.log`에 남는다. 종료 코드는 전부 통과했을 때만 0이다.

### <span class="n3">2.3</span> 이 스크립트에 없는 것

exe 화면 스모크(실제 창·마우스·타이틀바를 조작하는 35개 항목)는 저장소에 없는 별도 도구다. 실제 마우스를 쓰므로 머신 사용 중에는 결과가 흔들린다. 릴리스 전에는 이 스모크와 README의 **Manual checks**를 `dist-next\reado.exe`로 한 번 확인한다.

---

<a id="cat-3"></a>

# <span class="num">3</span> dist 교체 — scripts/swap_dist.py <span class="hctl"><a href="#toc">↑ 목차로</a></span>

> 인자 없이 실행하면 **dry run**이다. 할 일만 출력하고 아무것도 바꾸지 않는다. `--apply`를 줘야 실제로 교체한다.

### <span class="n3">3.1</span> 실행

```bash
python scripts/swap_dist.py                                  # dry run
python scripts/swap_dist.py --apply --expect <dist-next 해시>  # 교체
```

`--expect`에는 build_test.py 요약에 나온 해시를 그대로 넣는다. 테스트한 그 빌드만 들어가게 하기 위해서다.

### <span class="n3">3.2</span> 단계(--apply)

<div class="lay">
 <div class="cd" style="border-top-color:#6c8ebf"><b><span class="st">1</span> 확인</b><span class="s">dist-next 해시 계산, --expect와 비교. dist와 같으면 이미 교체된 것이므로 끝</span></div>
 <div class="ar">→</div>
 <div class="cd" style="border-top-color:#d6b656"><b><span class="st">2</span> 정상 닫기</b><span class="s">dist·dist-prev·dist-next에서 실행 중인 ReadO 창에 WM_CLOSE. 강제 종료는 하지 않는다</span></div>
 <div class="ar">→</div>
 <div class="cd" style="border-top-color:#82b366"><b><span class="st">3</span> 복사</b><span class="s">dist → dist-prev(덮어씀), dist-next → dist. 복사할 때마다 SHA256 확인</span></div>
 <div class="ar">→</div>
 <div class="cd" style="border-top-color:#9673a6"><b><span class="st">4</span> 정리</b><span class="s">dist-next, build, build-dist-next 삭제. dist와 dist-prev만 남긴다</span></div>
</div>

### <span class="n3">3.3</span> 멈추는 경우

| 상황 | 스크립트가 하는 일 | 종료 코드 | 결과 |
|---|---|---|---|
| `dist-next\reado.exe`가 없다 | 바로 멈춘다 | 1 | 바뀐 것 없음 |
| `--expect`와 해시가 다르다 | 바로 멈춘다 | 1 | 바뀐 것 없음 |
| `dist`와 해시가 같다 | "nothing to do" | 0 | 바뀐 것 없음(같은 빌드를 두 번 교체하지 않는다) |
| 실행 중인 ReadO에 **저장 안 된 편집**이 있다 | ReadO가 띄운 "Quit without saving?" 상자에 **Cancel**로 답하고 멈춘다 | 1 | 창과 편집은 그대로, 파일도 그대로 |
| 30초가 지나도 ReadO가 끝나지 않는다 | PID를 알려 주고 멈춘다 | 1 | 바뀐 것 없음, 사용자가 직접 닫는다 |
| 복사 중 오류 | 현재 `dist`가 옛 빌드인지, 새 빌드인지, 손상됐는지 알려 준다 | 2 | `dist-next`는 남긴다. 손상이면 `dist-prev`를 `dist`로 복사 |

### <span class="n3">3.4</span> 검증

교체 스크립트 자체는 실제 `dist`를 쓰지 않고 다음처럼 확인했다.

| 무엇을 | 어떻게 | 결과 |
|---|---|---|
| 닫기 | scratch 폴더에 exe 사본을 따로 띄우고 편집 중인 상태와 편집 없는 상태로 `close_normally` 실행 | 편집 중이면 Cancel하고 멈추며 편집이 남는다. 편집이 없으면 모든 프로세스가 정상 종료된다(7/7) |
| 복사·정리 | 가짜 dist·dist-prev·dist-next 폴더로 `--apply` 실행 | dry run은 무변경, 해시가 틀리면 무변경, 교체 후 dist·dist-prev만 남음, 같은 빌드 재실행은 무변경(4/4) |

---

<a id="cat-4"></a>

# <span class="num">4</span> 버전 끊기 — CHANGELOG <span class="hctl"><a href="#toc">↑ 목차로</a></span>

> 버전 번호는 [Semantic Versioning](https://semver.org/)을 따른다. 1.0 전에는 기능이 추가되면 MINOR, 버그 수정만 있으면 PATCH를 올린다.

| 할 일 | 위치 |
|---|---|
| `## Unreleased`의 내용을 `## X.Y.Z — 날짜` 항목으로 옮기고, `## Unreleased`는 빈 채로 남긴다 | `CHANGELOG.md` |
| 목차와 앵커(`<a id="vXYZ">`)를 추가한다 | `CHANGELOG.md` |
| 버전 표시를 맞춘다 | `README.md` 첫머리 **Version**, 앱의 Help → About(`server.py`의 `VERSION`) |
| 태그 `vX.Y.Z`와 push | 매니저 결정 후에만 |

---

<a id="cat-5"></a>

# <span class="num">5</span> 폴더 <span class="hctl"><a href="#toc">↑ 목차로</a></span>

| 폴더 | 내용 | 누가 쓰나 |
|---|---|---|
| `dist\` | 사용 중인 빌드. 매니저가 실행하는 exe | `swap_dist.py --apply`만 |
| `dist-prev\` | 바로 전 빌드(되돌리기용) | `swap_dist.py --apply`만 |
| `dist-next\` | 테스트 중인 새 빌드 | `build.bat dist-next`, `build_test.py` |
| `build-dist-next\`, `build\` | PyInstaller 작업 폴더 | 빌드할 때 생기고 교체할 때 지운다 |
