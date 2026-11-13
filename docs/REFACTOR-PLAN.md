# ReadO 고도화 1단계 — 구조 정리 계획

**기준**: HEAD `7934432` · `source.html` 5,488줄 · `server.py` 4,362줄  
**원칙**: 동작 변경 없이 리팩터링만 한다. 코드는 옮기기만 하고 고치지 않는다. 분리 단위마다 테스트를 통과시킨 뒤 로컬 커밋한다(push 안 함). 정리(D 항목)는 분리와 다른 커밋으로 한다.

<a id="toc"></a>

## 목차

- [**1. 프런트엔드 — source.html**](#cat-1)
- [**2. 서버 — server.py**](#cat-2)
- [**3. 빌드·서빙 영향**](#cat-3)
- [**4. D1~D13 정리 계획**](#cat-4)
- [**5. 검증·커밋 순서**](#cat-5)

---

<a id="cat-1"></a>

# 1 프런트엔드 — source.html 

> 원본 순서 그대로 `ui/` 아래 파일로 자른다. 브라우저에는 **지금과 똑같이 inline `<style>` 하나와 inline `<script>` 하나**로 내려간다. 서버가 페이지를 줄 때 `<!--#include ui/…-->` 자리에 파일 내용을 끼워 넣는다.

### 1.1 왜 `<script src>` 여러 개가 아니라 서버 include인가

현재 4,400줄짜리 inline 스크립트는 **하나의 스크립트**라는 점에 기대고 있다. 그래서 파일 여러 개로 나누어 각각 로드하면 동작이 바뀔 수 있다.

| 위험 | 내용 |
|---|---|
| 함수 호이스팅 | 스크립트 하나 안에서는 뒤쪽에 선언한 함수도 앞에서 호출할 수 있다. 파일을 나누면 앞 파일의 즉시 실행 코드가 뒤 파일 함수를 못 찾는다(예: `applyTheme()` 안의 `refreshToolbar()`) |
| 실행 끼어들기 | 외부 스크립트를 받는 사이에 Monaco AMD 콜백(`require([...], cb)`), `pywebviewready`, 타이머가 먼저 실행되어 아직 로드되지 않은 함수를 부를 수 있다 |
| 오류 전파 | 한 파일에서 예외가 나도 다음 파일은 계속 실행된다(지금은 그 지점에서 멈춤) |

serve 시점 include는 런타임 결과가 바이트 단위로 원본과 같으므로 위 세 가지가 모두 생기지 않는다. git.js처럼 독립적으로 로드되는 모듈은 지금처럼 `/app/…` 외부 파일로 둔다.

### 1.2 파일 경계(원본 순서 = 로드 순서)

| 파일 | 원본 구간 | 내용 |
|---|---|---|
| `ui/base.css` | 스타일 앞부분 | 테마 변수, 타이틀바, 상단 바, 레이아웃, 트리, 스플리터, 메인·탭 |
| `ui/panels.css` | 스타일 중간 | 검색 패널, Quick Open, Find in Files, 설정, 토스트 |
| `ui/chrome.css` | 스타일 끝 | 편집, 툴바, 사이드바·툴 윈도 스트립, 시작 화면, 빈 에디터 |
| `ui/state.js` | `Saved UI state` ~ `Documents` | 저장 상태, 문서(모델) 관리 |
| `ui/panes.js` | `Panes & Tabs` ~ `Small context menu` | 창·탭·분할 트리·탭 이동·컨텍스트 메뉴 |
| `ui/files.js` | `Save / reload` ~ `Opening files from outside` | 저장·충돌, 대화상자, 새 파일, 여러 파일 바꾸기, 연결 프로그램, 외부 변경 폴링, 세션 복원, 상태바, 뒤로/앞으로, 외부 파일 열기 |
| `ui/editor.js` | Markdown sanitize ~ `langFor` | Monaco 초기화·테마, 진단 설정, 토스트, 언어 매핑 |
| `ui/tree.js` | `Tree` ~ `File open` | 파일 트리, 파일 열기 |
| `ui/search.js` | `Find in Files` ~ `Wiring` | FIF, 최근 검색, 입력 연결 |
| `ui/settings.js` | `Settings` ~ `Splitter` | 설정 모달, 사이드바 폭 |
| `ui/quickopen.js` | `Quick Open` ~ `Go to Definition` | Quick Open(파일·줄·심볼) |
| `ui/commands.js` | `Commands` ~ `File-type badges` | 명령 레지스트리·팔레트, 메뉴바, 타이틀바, 파일 배지 |
| `ui/treeops.js` | `Tree: selection…` ~ `Toolbar` | 트리 조작, 키맵, 보기 토글, 인코딩, diff, git 마커, 사용처 수, 툴바 |
| `ui/nav.js` | `Component navigation` ~ `Workspace symbols` | Monaco provider, 컴포넌트 태그, 링크, 아웃라인, 워크스페이스 심볼 |
| `ui/start.js` | `Working folder` ~ `Init` | 작업 폴더·시작 화면, 부트스트랩 |

source.html에는 HTML 마크업과 include 표시만 남는다(약 330줄 예상).

---

<a id="cat-2"></a>

# 2 서버 — server.py 

> 기능 블록을 `srv_*.py` 모듈로 옮기고, 전역 상태와 외부(reado.py·gitview.py·테스트)가 읽거나 바꾸는 이름은 server.py에 남긴다.

### 2.1 모듈 경계

| 모듈 | 원본 구간 | 내용 | server.py에 남기는 것 |
|---|---|---|---|
| `server.py`(코어) | 1–928, 3229–3600, 3951–끝 | 설정·필터·인덱스·.gitignore·트리·디코딩, 요청 가드·CSRF, 외부 파일 권한·UI 상태, 저장 API, git 변경 줄, HTTP 핸들러 | — |
| `srv_search.py` | 929–1434 | Find in Files(rg·Python 폴백), 콘텐츠 캐시 | `USE_RIPGREP`(테스트가 바꿈) |
| `srv_goto.py` | 1435–1769 | 정의 이동·사용처, 선언 규칙 | — |
| `srv_links.py` | 1770–2834 | 컴포넌트 태그, import 경로·별칭·링크 해석 | — |
| `srv_tags.py` | 2835–3228 | Universal Ctags 심볼 인덱스, 아웃라인 | — |
| `srv_fileops.py` | 3601–3950 | 여러 파일 바꾸기, 이름 변경·삭제·새 폴더 | `_recycle`(테스트가 바꿈) |

### 2.2 동작을 그대로 두는 방법

| 규칙 | 이유 |
|---|---|
| 각 모듈은 `import server as S`로 코어를 참조하고, 코어 전역은 **`S.이름`으로 호출 시점에 읽는다**(gitview.py의 `S` 패턴과 같음) | `SETTINGS`·`CONFIG_PATH`·`_state`처럼 나중에 다시 대입되는 값과 테스트의 `server.X = …` 패치가 그대로 적용된다 |
| server.py는 블록이 있던 **원래 위치**에서 `from srv_x import …`로 다시 내보낸다 | 모듈 본문(데코레이터 `@write_api` 등록 등)이 원래와 같은 시점·순서로 실행된다. `server.find_in_files` 같은 기존 이름도 유지된다 |
| 블록 밖에서 쓰는 이름만 다시 내보내고, 모듈 안에서 다시 대입되는 상태(`_ctags_exe` 등)는 내보내지 않는다 | 복사된 이름이 낡은 값이 되는 일을 막는다 |
| 이름 바꾸기는 AST 도구로 기계적으로 한다(지역 변수·속성·키워드 인자는 제외). 손으로 고치지 않는다 | 누락·오타 방지. 변환 뒤 `ast.parse`와 import로 검사 |
| `python server.py` 단독 실행용으로 `sys.modules.setdefault("server", …)`를 추가한다 | `__main__`으로 실행될 때 server가 두 번 import되지 않게 한다 |

예상 크기: server.py 약 1,600줄 + 모듈 5개(각 330–1,070줄).

---

<a id="cat-3"></a>

# 3 빌드·서빙 영향 

| 항목 | 변경 |
|---|---|
| 페이지 서빙 | `_serve_html`이 토큰을 넣기 전에 `<!--#include ui/파일-->`을 펼친다. 이름은 `ui/[\w.-]+\.(js|css)`만 허용하고, 파일이 없으면 지금처럼 404 오류 |
| PyInstaller | `build.bat`에 `--add-data "%~dp0ui;ui"`를 추가한다. `srv_*.py`는 server.py의 정적 import로 자동 포함되지만 명시적으로 `--hidden-import`도 넣는다 |
| 경로 | `ui/`는 `source.html` 옆(`dirname(HTML_PATH)`)에서 찾는다. 소스 실행·테스트·exe(`_MEIPASS`) 모두 같은 규칙 |
| 빌드 출력 | 이번 단계는 `build.bat dist-next`만 사용한다. `dist\`는 건드리지 않는다 |

---

<a id="cat-4"></a>

# 4 D1~D13 정리 계획 

> FEATURES.md 작성 이후 코드가 많이 바뀌어 상당수는 이미 해소됐다. 남은 항목만 grep으로 참조가 없음을 확인하고 지운다.

| # | 현재 상태 | 처리 |
|---|---|---|
| D1 `read_file`의 도달 불가 분기 | `_decode` 재작성으로 해소 | 없음 |
| D2 `_activeMatch` | 선언만 남음(참조 0) | **삭제** |
| D3 `.search-bar` CSS | 규칙 12줄, 요소 없음(HTML·JS·git.js 참조 0) | **삭제** |
| D4 `switchTab()` 별칭 | 호출 0(테스트·reado.py `run_js` 포함) | **삭제** |
| D5 Pillow | requirements에서 이미 빠짐 | 없음 |
| D6 `reado.spec` | 추적 안 됨, build.bat이 관리 | 없음 |
| D7 `serve()` 중복 | reado.py 쪽이 이미 없어짐 | 없음 |
| D8 모듈 로드 시 `SETTINGS` 계산 | 의도된 기본값(테스트·import가 기댐) | **유지**, 보고서에 기록 |
| D9 선언 정규식 이중 관리(클라이언트 `symbolPatterns` / 서버 `_decl_rules`) | 통합하면 결과가 달라질 수 있음 | **유지**, 별도 과제로 기록 |
| D10 scope 계산 중복 | `_scoped_index`로 이미 통합 | 없음 |
| D11 기본 base_dir | `""`로 이미 바뀜 | 없음 |
| D12 파일 중간 import | `srv_search.py` 분리로 상단 import가 됨 | 분리 커밋에서 해소 |
| D13 README | config 위치는 수정됨. doc-standard `<style>` 머리말은 문서 표준이라 유지 | 없음 |

---

<a id="cat-5"></a>

# 5 검증·커밋 순서 

| 순서 | 커밋 | 검증 |
|---|---|---|
| 1 | docs: 이 계획 | — |
| 2 | 프런트: include 장치 + CSS 분리 | verify_editor, ui_git_smoke |
| 3 | 프런트: JS 분리 + 서빙 결과가 원본과 같은지 비교 | verify_editor, ui_git_smoke |
| 4–8 | 서버: 모듈 5개를 하나씩 | 매번 import·`ast` 검사 + verify_editor(검색·goto 모듈은 test_git도) |
| 9 | 정리: D2·D3·D4 | verify_editor |
| 10 | 단계 끝: 전체 회귀 + `build.bat dist-next` + exe 스모크 35/35 + exe_startup | 줄 수 전후 비교 |

서빙된 페이지 동일성은 분리 전후의 `GET /` 응답(토큰·상태 스크립트 제외)을 바이트 단위로 비교해 확인한다.
