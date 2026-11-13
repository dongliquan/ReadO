# ReadO Git 기능 설계 — 보기 중심 + AgentO 연동

**대상**: ReadO `gitview.py`(신규) · `git.js` / `git.css`(신규) · `server.py` · `source.html` · `build.bat` · 연동 조사 `C:\ClaudeCode\AgentO`(읽기만)  
**요청**: "IntelliJ의 git 기능 추가" → 방향 지시 반영: **조작(쓰기)은 AgentO, ReadO는 보여주기 중심**  
**상태**: P0 · P1 · P2 구현 완료(AgentO 데몬 WebSocket 브리지는 범위 제외) — 결과는 [§13](#cat-13) · 2026-10-12 · git 2.45.1

<a id="toc"></a>

## 목차

- [**1. 결정 사항**](#cat-1)
- [**2. 현재 상태와 확장 지점**](#cat-2)
- [**3. 구현 방식 비교 — git CLI vs 순수 Python**](#cat-3)
- [**4. ReadO ↔ AgentO 책임 경계와 연동 방안**](#cat-4)
- [**5. 기능 범위와 단계 계획**](#cat-5)
- [**6. UI 배치**](#cat-6)
- [**7. API 설계 (/api/git/\*)**](#cat-7)
- [**8. 대형 저장소 성능 · 번들 크기 목표**](#cat-8)
- [**9. 보안**](#cat-9)
- [**10. 참조 프로젝트**](#cat-10)
- [**11. 위험 요인**](#cat-11)
- [**12. 테스트 계획**](#cat-12)
- [**13. 구현 결과**](#cat-13) (실측 · 설계와 달라진 점)
- [**14. 툴바 Git 그룹 · AgentO 딥링크 요청 스펙(v1)**](#cat-14)

---

<a id="cat-1"></a>

# 1 결정 사항 

> 시스템 git CLI를 읽기 전용으로만 부르고, 쓰기 조작은 AgentO로 넘긴다.

| # | 결정 | 근거 |
|---|---|---|
| 1 | **시스템 git CLI 호출**(subprocess). git이 없으면 Git 기능만 비활성 + 설치 안내 | 번들 +0 MB, 정확도·속도가 git 자체, 기존 `_git()`·rg 실행 패턴 재사용 |
| 2 | **ReadO는 읽기 전용**: index·ref·작업 트리를 바꾸는 git 명령은 실행하지 않음 | 매니저 방향 지시. 보안·인증·충돌 처리 범위가 대폭 줄어듦 |
| 3 | 쓰기 조작은 **"AgentO로 보내기"** 액션으로 전달. 기본 = 프롬프트 클립보드 복사 + AgentO 포커스, 옵션 = AgentO 데몬 WS 브리지(실험) | AgentO에 외부 진입점(딥링크·argv)이 없음 → 무변경으로 확실한 경로는 클립보드뿐 |
| 4 | 로그 그래프는 `git log --graph` 출력이 아니라 **`--format` 파싱 + 프런트 JS 레인 계산**(VS Code SCM Graph 방식, MIT) | 페이지 단위 이어붙이기·가상 스크롤과 맞음 |
| 5 | 새 코드는 **별도 파일**(`gitview.py`, `git.js`/`git.css`)로 두고 기존 파일에는 등록 훅만 추가 | 에디터 구현 세션과 `server.py`·`source.html` 동시 수정 충돌 최소화 |
| 2a | **예외(2026-10-16, 매니저 결정; 2026-10-21 확장)**: 최신 소스를 받아 보는 **Pull, Fetch, 브랜치 Checkout**만 ReadO가 직접 실행한다([§14.4](#sec-14-4)). Pull은 fetch 후 `merge --ff-only`만 하고(= `git pull --ff-only`), 병합 커밋·rebase·autostash는 하지 않으며 fast-forward가 안 되면 아무것도 바꾸지 않고 멈춘다. Commit·Push는 계속 AgentO 담당이며, [§14](#cat-14) 딥링크로 요청한다 | ReadO는 보기 중심이고, 최신 코드를 받아 보는 일만 바로 할 수 있게 함 |
| 6 | IntelliJ에서 **가져올 것**: Log 3단(브랜치 트리·그래프 표·상세+파일 트리), 필터 바, Local Changes, diff, Annotate(blame), 파일 History. **뺄 것**: Commit/Push 대화상자, Shelf/Stash 조작, 충돌 해결 3-way 머지, 인터랙티브 rebase, 원격 관리 | 가벼운 뷰어 철학 + 쓰기는 AgentO |

---

<a id="cat-2"></a>

# 2 현재 상태와 확장 지점 

> 거터 변경 표시·HEAD 비교·브랜치 표시는 이미 있다. 새 기능은 이 코드를 확장한다.

## 2.1 이미 있는 git 코드

| 위치 | 내용 | 설계에서의 처리 |
|---|---|---|
| `server.py:3776` `_git(args, cwd)` | `subprocess.run`, `GIT_TIMEOUT=5`, `CREATE_NO_WINDOW`, 실패 시 None | `gitview.run()`(Popen·취소·환경 고정)로 대체, `_git`은 위임 |
| `server.py:3788` `git_head_text` | `git show HEAD:rel`, (path, sha) 캐시 300건 | 유지. `/api/git/show`로 일반화 |
| `server.py:3809` `git_line_changes` | difflib로 저장 안 된 텍스트 vs HEAD 줄 변경 계산 | 유지(저장 전 버퍼 비교는 git diff로 못 함) |
| `server.py:3824` `@write_api("/api/git-changes")` | 거터용 `{repo, branch, added, modified, deleted}` | 유지. POST인 이유는 버퍼 텍스트를 body로 보내기 때문 |
| `source.html:4187-4215` `scheduleGit`/`refreshGit`/`updateBranch` | `deltaDecorations` 거터 + overview ruler, `sbBranch` | 유지. 거터 클릭 시 hunk diff 미리보기 추가 |
| `source.html:4133-4162` `openDiff`/`compareWithHead` | Monaco `createDiffEditor` 전체 오버레이 | 재사용. 임의 rev 쌍 비교로 확장 |
| `docs/FEATURES.md:320` | G24 "Git 연동(변경 표시, blame, diff)" 미해결 | 이 문서가 G24의 설계 |

## 2.2 확장 지점

| 영역 | 기존 구조 | git이 얹히는 방식 |
|---|---|---|
| 라우팅 | GET: `do_GET` if/elif(3945~), POST: `POST_ROUTES` + `@write_api`(3318) | GET 라우트는 `gitview.handle_get(path, qs)` 한 줄 위임. 읽기 전용이므로 거의 전부 GET |
| 요청 가드 | `check_read_request`(Host 허용 목록), `check_write_request`(+Origin·`Sec-Fetch-Site`·CSRF 토큰 `X-ReadO-Token`·JSON·크기 제한) | GET은 read 가드, AgentO 전달만 write 가드 |
| 경로 검증 | `resolve_read_path`, `_safe_join`(realpath + 포함 검사) | 모든 path 인자는 `resolve_read_path` 통과 후 저장소 루트 기준 상대 경로로 변환 |
| 실행·취소 | rg: Popen + `threading.Timer` kill, 세대 번호 `_new_gen`/`_is_stale`(830-841) | 같은 세대 방식에 kind `git-log`/`git-blame`/`git-status` 추가 |
| 동시성 | `ThreadingHTTPServer`, `_SEARCH_EXECUTOR(8)`, `_SEARCH_GATE(2)` | git 전용 세마포어 `_GIT_GATE(3)` |
| 상태 저장 | `state.json` `{ui, external}`, POST `/api/state` | `ui.git` 아래: 패널 열림·높이·활성 탭·로그 필터·컬럼 폭 |
| 명령 | `COMMANDS`(3495) `{id, cat, title, keys, bind, run, enabled, when}` | `cat:'Git'` 명령 20여 개 추가(§6.3) |
| 메뉴·툴바 | `MENUS`(3687) File/Edit/View/Go/Window/Help, 툴바 그룹 file/search/view/prefs | **Git** 최상위 메뉴 신설(Go와 Window 사이), 툴바는 그룹 하나(`git`)에 버튼 2개만 |
| 레이아웃 | 사이드바 탭 files/outline, 분할 pane 최대 4, **하단 패널 없음** | 하단 도구창(`#toolwin`) 신설 — 가장 큰 UI 변경 |
| 파일 트리 | `loadTree` → `div.node[data-path]` | `.node`에 `git-M`/`git-A`/`git-U` 클래스(색) 부여 |
| 상태바 | `sbBranch` 존재 | 클릭 → 브랜치 팝업, ahead/behind 표시 |

---

<a id="cat-3"></a>

# 3 구현 방식 비교 — git CLI vs 순수 Python 

> 읽기 전용이 되면서 차이가 더 벌어졌다. 인증·쓰기를 안 하므로 순수 Python의 유일한 장점(git 미설치 환경)만 남는다.

| 기준 | a 시스템 git CLI | b dulwich(순수 Python) | c MinGit 번들 |
|---|---|---|---|
| exe 크기 | **+0 MB** | +약 1~2 MB(C 확장 제외) | +30 MB 이상 |
| 로그 속도(10만 커밋) | commit-graph 파일 사용, 수백 ms 단위 | Python 객체 순회 — 수십 배 느림 | (a)와 같음 |
| status 속도(대형 트리) | fsmonitor·untracked cache 사용 | 인덱스·stat 비교 직접 — 느림 | (a)와 같음 |
| 정확도 | 기준 그 자체(rename 탐지, `.gitattributes`, sparse, worktree, LFS 포인터) | rename·blame·`--follow` 미흡, blame은 직접 구현 필요 | (a)와 같음 |
| blame | `--porcelain`/`--incremental` | 없음(직접 구현) | (a)와 같음 |
| 미설치 환경 | 기능 비활성 + 안내 | 동작 | 동작 |
| 라이선스 | 해당 없음(외부 프로그램) | Apache-2.0 선택 가능 | GPL-2 바이너리 재배포 고지 필요 |
| 결론 | **채택** | 비채택 | 비채택(git 사용자는 이미 git 설치) |

**git 탐색 순서**: `config.json`의 `git_path` → `shutil.which("git")` → `%ProgramFiles%\Git\cmd\git.exe`. 최소 버전 **2.24**(`--end-of-options`), 미만이면 비활성. 결과는 `/api/git/info`의 `available`·`version`·`reason`으로 UI에 알린다.

---

<a id="cat-4"></a>

# 4 ReadO ↔ AgentO 책임 경계와 연동 방안 

> AgentO에는 git 쓰기 UI가 없다. git 조작은 AgentO의 **에이전트 세션**이 한다. 그래서 "AgentO로 보내기"는 git 명령이 아니라 **세션에 보내는 지시문**이다.

## 4.1 AgentO 조사 결과 (읽기만 함)

| 항목 | 현황 | 근거 |
|---|---|---|
| git 기능 | `git status --porcelain` 읽기만 함(트리 M/A/D 배지). diff 뷰는 "not yet" | `src\daemon\fsapi.ts:140-175`, `store.ts:24` |
| git 쓰기 | 앱 자체에는 없음. Claude/Codex 세션(pty)이 실행 | `sessions.ts:305-322` |
| 세션 작업 폴더 | 세션은 프로젝트 + 폴더에 속하고, `cwd = folder.path` | `src\daemon\index.ts:541-557` |
| CLI 인자 / 딥링크 | **없음**. 두 번째 실행은 창 표시만(argv 무시) | `src\main\index.ts:30-50` |
| 데몬 | 127.0.0.1:47831(+10까지), HTTP + WebSocket, 첫 메시지 `hello{token}` 인증 | `index.ts:152-195, 725-731` |
| 토큰 | `%APPDATA%\AgentO\daemon.json` `{port, token, pid, version}`. 데몬 재시작마다 바뀜 | `index.ts:192-194` |
| 지시 전달 메시지 | `session.message{id,text}`(멈춘 세션도 깨움), `team.order{target,text}`, `session.create`, `project.start` | `team.ts:648, 1174` |
| MCP | `POST /mcp/<sessionId>` + Bearer 토큰. 기존 세션 신원을 빌려야 함 | `team.ts:1617-1660` |
| handoff 폴더 | 세션 메모용. 감시되는 수신함 아님 | `freshstart.ts:13-15` |

## 4.2 연동 방안 비교

| 방안 | AgentO 변경 | 가능한 것 | 현실성 | 단점 |
|---|---|---|---|---|
| A 클립보드 + AgentO 열기 | 없음 | 지시문(폴더·파일·메시지 초안 포함) 복사 → `AgentO.exe` 실행(단일 인스턴스라 창만 앞으로) | **확실** | 사용자가 세션을 골라 붙여넣어야 함 |
| B 데몬 WebSocket 브리지 | 없음 | `daemon.json` 읽기 → `hello(client:'cli')` → `welcome`의 세션 중 cwd 일치 세션에 `session.message` | 기술적으로 가능 | **비공개 내부 프로토콜**(버전 변경 시 깨짐), 토큰이 전권 토큰, Python 표준 라이브러리에 WS 클라이언트 없음(직접 구현 ~150줄 또는 `websocket-client` Apache-2.0 번들) |
| C MCP 엔드포인트 | 없음 | `send_to_session` 등 호출 | 가능하나 부적합 | 다른 세션의 신원을 빌려야 함 — 기록상 "그 세션이 보낸 것"이 됨 |
| D 외부 터미널 열기 | 없음 | `wt.exe -d <repo>` 또는 `cmd /k cd /d <repo>`, 명령은 클립보드 | 확실 | AgentO를 거치지 않음 — 보조 수단 |
| E AgentO에 공식 진입점 추가 | **필요**(AgentO 팀) | `agento://order?folder=…&text=…` 또는 `second-instance` argv 처리, 범위 제한 토큰, "세션 X 포커스" | 가장 깔끔 | AgentO 일정에 의존 |

**권고**: P2에서 A를 기본으로, D를 보조로 넣는다. B는 설정 `agento_bridge: false`(기본 꺼짐)의 **실험 기능**으로만. 동시에 AgentO 쪽에 E(딥링크 + 범위 제한 토큰)를 요청하고, 들어오면 B를 E로 교체한다.

- **ReadO** — `Local Changes · Log · Branch 팝업` — 선택한 파일·커밋·브랜치로 지시문 생성<br>예: "C:\repo 에서 a.py, b.py 를 커밋해 줘. 메시지 초안: …"
- **A 기본** — `클립보드 + AgentO.exe 실행` — 토스트: "AgentO에서 세션을 골라 붙여넣으세요"
- **B 실험(옵션)** — `ws://127.0.0.1:port` — cwd 일치 세션 선택 대화상자 → session.message. 실패 시 A로 폴백
- **AgentO 세션** — `Claude/Codex pty` — git 실행 → ReadO는 status/log 자동 갱신으로 결과 확인

## 4.3 책임 경계

| 영역 | ReadO | AgentO |
|---|---|---|
| 변경 목록·diff·blame·로그·브랜치 보기 | **담당** | (트리 배지만) |
| stage/unstage, commit, amend | 지시문만 생성 | **담당**(세션) |
| push / pull / fetch, 자격 증명 | 하지 않음 | **담당**(세션 → git credential helper) |
| checkout, 브랜치 생성·삭제, merge, rebase, cherry-pick, revert, stash | 지시문만 생성 | **담당** |
| 충돌 | 충돌 파일 표시(U 상태)·충돌 마커 하이라이트 | 해결 |
| 결과 확인 | 파일 감시·포커스 시 status/log 재조회 | 세션 출력 |
| 작업 폴더 | ReadO 루트 = 저장소 경로를 지시문에 넣음 | 세션 cwd |

---

<a id="cat-5"></a>

# 5 기능 범위와 단계 계획 

> 난이도: 하(≤0.5일) · 중(1~2일) · 상(3일 이상). 영향 파일 중 굵은 것은 신규 파일.

## 5.1 P0 — 기반 (1.5일)

| ID | 항목 | 난이도 | 영향 파일 |
|---|---|---|---|
| G0-1 | git 실행기 `run()`: Popen, 세대 취소, 타임아웃, 환경 고정(§9), `_GIT_GATE` | 중 | **gitview.py**, `server.py`(import·라우트 위임 2곳) |
| G0-2 | 저장소 탐지·`/api/git/info`, 미설치·구버전·저장소 아님 안내 | 하 | **gitview.py** |
| G0-3 | 프런트 로더: `git.js`/`git.css` 정적 서빙, `COMMANDS`·`MENUS`에 Git 항목 주입 | 하 | **git.js**, `source.html`(script 태그·훅), `server.py`(정적 경로), `build.bat`(add-data) |
| G0-4 | 하단 도구창 `#toolwin` 골격(탭·리사이즈·상태 저장) | 중 | **git.js**, `source.html`(레이아웃 컨테이너) |

## 5.2 P1 — 읽기 전용 핵심 (10항목, 약 8일)

| ID | 항목 | IntelliJ 대응 | 난이도 | 영향 파일 |
|---|---|---|---|---|
| G1-1 | **Local Changes** 탭: 폴더별 트리·파일 수, 상태 색(M/A/D/R/U/?), staged/unstaged 구분 표시 | Commit 도구창 | 중 | **git.js**, **gitview.py** |
| G1-2 | **diff 보기**: 작업 트리↔HEAD, index↔HEAD, 커밋↔부모. Monaco diff editor, side-by-side/inline 전환, 다음/이전 변경 | Show Diff (Ctrl+D) | 중 | **git.js**, `source.html`(`openDiff` 인자 확장) |
| G1-3 | **거터 변경 표시** 보강: 거터 클릭 → hunk diff 팝업(읽기), HEAD 기준 외에 index 기준 옵션 | 거터 change marker | 하 | `source.html`(`refreshGit` 부근) |
| G1-4 | **파일 트리 상태 색/배지**, 사이드바 폴더에 변경 점 | 프로젝트 뷰 색 | 하 | **git.js**, `source.html`(`loadTree` 훅 1줄) |
| G1-5 | **브랜치**: 상태바 브랜치 + ahead/behind, 클릭 팝업(로컬·원격·태그 목록, 읽기) | Branches 팝업 | 하 | **git.js**, **gitview.py** |
| G1-6 | **Log 그래프**: 페이지 로딩(200개), 가상 스크롤, JS 레인 계산, ref 라벨, 머지 커밋 흐리게 | Log 탭 | 상 | **git.js**, **gitview.py** |
| G1-7 | **Log 필터**: 텍스트/해시, Branch, User, Date, Paths. 좌측 브랜치 트리(HEAD/Local/Remote/Tags) 클릭 = Branch 필터 | 필터 바 · 브랜치 트리 | 중 | **git.js**, **gitview.py** |
| G1-8 | **커밋 상세**: 전체 메시지·작성자·해시·포함 ref, 변경 파일 트리(폴더별 수, +/− 줄 수), 파일 클릭 → diff | 우측 상세 패널 | 중 | **git.js**, **gitview.py** |
| G1-9 | **파일 History**: `--follow` 이력, 선택 → 해당 리비전 diff | Show History | 중 | **git.js**, **gitview.py** |
| G1-10 | **Blame(Annotate)**: 거터 왼쪽 작성자·날짜 열, 나이 색 농도, 호버 → 커밋 요약, 클릭 → Log에서 선택 | Annotate | 상 | **git.js**, **gitview.py**, `source.html`(Monaco 옵션 1곳) |

## 5.3 P2 — AgentO 연동 + 읽기 보강 (6항목, 약 4일)

| ID | 항목 | 난이도 | 영향 파일 |
|---|---|---|---|
| G2-1 | "AgentO로 보내기" 공통: 지시문 템플릿(커밋·푸시·풀·체크아웃·브랜치 생성·cherry-pick·revert·stash), 클립보드 + `AgentO.exe` 실행(방안 A) | 중 | **git.js**, `reado.py`(exe 실행 JS API 또는 서버 엔드포인트) |
| G2-2 | 외부 터미널 열기(방안 D) | 하 | `reado.py` |
| G2-3 | AgentO WS 브리지(방안 B, 기본 꺼짐), 세션 선택 대화상자, 실패 시 A 폴백 | 상 | **agento_bridge.py**, **git.js** |
| G2-4 | 자동 갱신: 창 포커스·`.git/HEAD`·`index` mtime 변화 시 status/log 재조회 | 하 | **gitview.py**, **git.js** |
| G2-5 | 충돌 상태 표시: 상단 배너("MERGING 3 files"), 충돌 마커 하이라이트(해결은 AgentO) | 하 | **git.js** |
| G2-6 | Stash/Shelf **목록·diff 보기**(읽기) | 중 | **git.js**, **gitview.py** |

## 5.4 P3 — 후보 (필요 시)

| 항목 | 판단 |
|---|---|
| Console 탭(ReadO가 실행한 git 명령·소요 시간 로그) | 진단용으로 유용, 하(0.5일). 읽기 명령만이라 우선순위 낮음 |
| 두 커밋/브랜치 임의 비교(Compare with Branch) | 중. G1-2 확장 |
| 다중 파일 diff 한 화면(diff2html) | 중. Monaco 단일 파일로 충분하면 생략 |
| 서브모듈·worktree 전환 표시 | 하~중 |

## 5.5 제외 (ReadO에 넣지 않음)

stage/unstage · commit/amend · rollback · checkout(단, 브랜치 이동은 2026-10-21부터 ReadO가 직접 — §14.4) · 브랜치 생성/삭제 · push(fetch·pull은 ReadO 직접 — 결정 2a) · merge/rebase · 인터랙티브 rebase · cherry-pick/revert 실행 · stash 생성/적용 · 3-way 충돌 해결 UI · 원격·태그 관리 · 자격 증명 처리. → 전부 G2-1 지시문으로 AgentO에 넘긴다.

---

<a id="cat-6"></a>

# 6 UI 배치 

> 하단 도구창 하나에 Git을 모으고, 상시 노출은 상태바·파일 트리 색·거터만.

## 6.1 화면 구성

- **사이드바(기존)** — `files · outline` — 파일 트리 이름 색: M 파랑 · A 초록 · ? 빨강 · U 주황 · 무시 회색. 폴더에 변경 점
- **에디터 pane(기존)** — `거터 · Blame 열` — 변경 막대 클릭 → hunk 팝업. Blame 켜면 줄 왼쪽에 작성자·날짜
- **하단 도구창 Git(신규)** — `[Local Changes] [Log] [Console*]` — Log = 브랜치 트리 | 그래프 표 | 커밋 상세+파일 트리 (3단, IntelliJ 동일). 높이·탭은 state.json
- **상태바(기존)** — `⎇ main ↑2 ↓0` — 클릭 → 브랜치 팝업(읽기 + "AgentO에서 체크아웃")

> * Console은 P3

| 탭 | 왼쪽 | 가운데 | 오른쪽 | 컨텍스트 메뉴(쓰기는 전부 AgentO로) |
|---|---|---|---|---|
| Local Changes | — | 변경 파일 트리(Changes / Unversioned / Conflicts 그룹) | 선택 파일 미니 diff(선택) | Show Diff · 열기 · History · *AgentO로: 커밋/롤백* |
| Log | 브랜치 트리 HEAD/Local/Remote/Tags | 필터 바 + 그래프·메시지·ref·날짜·작성자 | 변경 파일 트리 + 메시지 상세 | 해시 복사 · 이 커밋과 비교 · *AgentO로: 체크아웃/cherry-pick/revert/브랜치 생성* |

## 6.2 메뉴 — Git 최상위 메뉴 신설

| 그룹 | 항목 |
|---|---|
| 보기 | Git 도구창 · Local Changes · Log · 현재 파일 History · Blame 토글 · HEAD와 비교 · 브랜치… |
| AgentO로 | 커밋 요청… · 푸시 요청 · 풀 요청 · 브랜치 체크아웃 요청… |
| 기타 | 외부 터미널 열기 · 새로 고침 |

File > Compare 의 기존 `compareWithHead`는 그대로 두고 Git 메뉴에도 노출. 툴바는 `git` 그룹에 **Git 도구창**·**AgentO로 커밋** 버튼 2개만.

## 6.3 단축키

| 명령 | IntelliJ 프리셋 | VS Code 프리셋 | 충돌 검사 결과 |
|---|---|---|---|
| Git 도구창 토글 | **Alt+9** | Ctrl+Shift+G | 둘 다 미사용 |
| Local Changes 탭 | **Alt+0** | — | Alt+0 미사용(Ctrl+0은 줌 리셋 — 다른 키) |
| AgentO로 커밋 요청 | **Ctrl+K** | — | IntelliJ 프리셋에선 미사용. VS Code 프리셋은 Ctrl+K가 Monaco 코드 chord 접두사라 **바인딩 안 함** |
| AgentO로 푸시 요청 | **Ctrl+Shift+K** | — | Monaco 기본 "줄 삭제"와 충돌 → IntelliJ 프리셋에서만 `capture`로 가로챔(IntelliJ에서 줄 삭제는 Ctrl+Y) |
| AgentO로 풀 요청 | Ctrl+T(IntelliJ Update Project) | — | **충돌**: ReadO는 Ctrl+T = `go.symbolFolder` → **바인딩 안 함**, 메뉴로만 |
| diff 보기(선택 파일/커밋) | Ctrl+D(도구창 포커스일 때만 `when`) | Enter | 에디터의 Ctrl+D(Monaco)와는 `when`으로 분리 |
| Blame 토글 | — (메뉴) | — | — |
| 파일 History | — (메뉴) | — | — |

Ctrl+K·Ctrl+Shift+K는 실제 커밋이 아니라 **지시문 미리보기 대화상자**를 연다(확인 후 복사·전송). 기존 충돌 검사기(`source.html:4081`)에 새 바인딩을 넣어 검증한다.

---

<a id="cat-7"></a>

# 7 API 설계 (/api/git/\*) 

> 모두 JSON. 읽기는 GET(`check_read_request`), 프로그램을 띄우는 두 개만 POST(`@write_api`). 공통 오류 `{error:"no_git"|"old_git"|"not_repo"|"unsafe_repo"|"timeout"|"cancelled"|"busy"|"bad_arg"|"git_failed", detail}`. `repo` = 저장소 최상위 절대 경로(`/repos`가 준 값).

| 메서드·경로 | 입력 | 출력(개요) |
|---|---|---|
| GET `/api/git/info` | `path?`(ReadO 키) 또는 `repo?` | `{available, version, reason, min_version, repo?:{root, name, base, state, branch, detached}, rel?}` |
| GET `/api/git/repos` | — | `{repos:[{root, name, base, state}]}` — 작업 폴더를 감싼 저장소 + 2단계 아래 저장소(최대 100) |
| GET `/api/git/status` | `repo`, `fresh?` | `{branch:{oid, head, detached, upstream, ahead, behind}, files:[{path, orig?, x, y, kind, staged, unstaged}], truncated, ms}` |
| GET `/api/git/decor` | `dir*`(펼친 트리 폴더) | `{files:{key:"M"\|"A"\|"U"\|"C"\|"R"}, dirs:{key:code}, repos}` |
| GET `/api/git/fp` | `repo` | `{fp, state}` — HEAD·index·refs·logs mtime 지문(자동 새로 고침 판단) |
| GET `/api/git/refs` | `repo` | `{head, head_sha, user, local:[{name, ref, sha, upstream, ahead, behind, gone, current}], remote:[…], tags:[…]}` |
| GET `/api/git/authors` | `repo` | `{authors:[…]}` — 최근 3000커밋 빈도순(User 필터) |
| GET `/api/git/log` | `repo`, `offset`, `n≤1000`, `ref*`, `author*`, `since`, `until`(YYYY-MM-DD), `path*`, `text`, `regex`, `case`, `follow`(History), `reload` | `{commits:[{h, p, an, ae, at, refs, s, path_at?, path_from?, fs?}], has_more, done, loaded, hash_hit, ms}` |
| GET `/api/git/commit` | `repo`, `rev` | `{h, p, an, ae, at, cn, ce, ct, refs, body, parent, files:[{path, orig?, status, add, del, binary}], truncated}` |
| GET `/api/git/show` | `repo`, `rev`(sha·`HEAD~n`·ref·`INDEX`·`WORKTREE`), `path` | `{text, encoding, size}` 또는 `{binary}` · `{too_big}` · `{missing}` |
| GET `/api/git/blame` | `path`(ReadO 키), `w?` | `{repo, rel, lines:[commit 번호], commits:[{h, an, ae, at, s, uncommitted}]}` 또는 `{untracked}` |
| GET `/api/git/stash` | `repo` | `{items:[{name, h, at, s}]}` |
| GET `/api/git/console` | `since?` | `{entries:[{id, t, cmd, cwd, ms, rc, kind, err}]}` (최근 300건) |
| POST `/api/git-changes` | `{path, text, want_head?}` | 기존 그대로(거터 표시·HEAD와 비교) — 내부 실행기만 `gitview`로 교체 |
| POST `/api/git/agento` | `{path?, probe?}` | `{launched, path?, reason?}` — 실행 중 AgentO.exe 경로 → `%LOCALAPPDATA%\Programs\AgentO` 순으로 찾아 실행(포커스) |
| POST `/api/git/terminal` | `{repo}` | `{ok, terminal:"wt"\|"cmd"}` |

**입력 검증**: `rev`는 `^[0-9a-f]{4,64}$`·`HEAD(~n|^n)*`·`INDEX`·`WORKTREE` 또는 `/api/git/refs` 목록에 있는 ref 이름만 허용 → 그다음 `rev-parse --verify --end-of-options <rev>^{commit}`으로 sha로 바꿔서만 사용. `path`는 `resolve_read_path` 뒤 저장소 루트 기준 상대 경로로 바꾸고 항상 `--` 뒤에 둔다. `author`·`grep`은 `--author=<값>` 한 인자로만 넘기고(셸 없음) 길이 200자 제한.

---

<a id="cat-8"></a>

# 8 대형 저장소 성능 · 번들 크기 목표 

## 8.1 기법

| 대상 | 방식 |
|---|---|
| 로그 목록 | `git log -z --format=%H%x00%P%x00%an%x00%ae%x00%at%x00%D%x00%s` (본문 `%b` 제외, 상세는 선택 시 `/commit`) |
| 순서 | 기본 `--date-order`(`--topo-order`보다 첫 출력이 빠름). 레인 계산은 부모 목록만 쓰므로 둘 다 동작 |
| 페이지 | 200개씩. 커서 = 마지막 페이지의 아직 안 나온 부모 sha 집합 + 본 sha 경계 → `git log <부모들> --not <경계>`. `--skip`은 매번 처음부터 다시 걸어서 쓰지 않음 |
| 레인 계산 | 프런트 JS, 활성 레인 배열을 행마다 갱신(첫 부모가 레인 승계). 페이지 사이에 레인 상태를 유지해 그래프가 이어짐 |
| 렌더링 | 가상 스크롤(보이는 행 + 여유 20행만 DOM). 행마다 작은 SVG |
| commit-graph | `.git/objects/info/commit-graph`가 없고 커밋이 1만 개를 넘으면 안내 배너: "`git commit-graph write --reachable --changed-paths` 실행 시 로그·History가 빨라집니다" — **ReadO는 직접 실행하지 않음**(쓰기) |
| status | `status --porcelain=v2 -z --branch --untracked-files=normal`. 파일 5천 개 넘으면 `truncated` + 폴더 요약 |
| 파일 History | `--follow -- <path>`, `--changed-paths` 블룸 필터가 있으면 빠름 |
| blame | `--incremental` 스트림을 청크로 전달, 보이는 범위부터 표시. `-w -M -C`는 옵션 |
| 실행 제어 | 세대 번호로 이전 요청 kill(필터 입력마다), 타임아웃: info/status 10초 · log 페이지 15초 · blame 30초 · show 10초. 동시 3개 |
| 캐시 | (HEAD sha, index mtime) 키로 status·refs 캐시. `show`는 기존 300건 캐시 |

## 8.2 목표 수치

| 항목 | 목표 | 측정 저장소 |
|---|---|---|
| exe 크기 증가 | **+0.2 MB 이하**(Python·JS·CSS만, 바이너리 추가 없음) | dist\reado.exe 현재 22.6 MB |
| Git 도구창 첫 표시 | 300 ms 이하 | 파일 1만 개 |
| Log 첫 페이지(200) | 400 ms 이하(commit-graph 있을 때), 1.5초 이하(없을 때) | 커밋 10만 개(fixture 합성) |
| 스크롤 | 프레임 16 ms 이하, DOM 행 300개 이하 | 같음 |
| 레인 계산 | 1만 커밋 50 ms 이하 | 같음 |
| Blame 첫 화면 | 1초 이하(5천 줄 파일), 완료 5초 이하 | — |
| 거터 갱신 | 기존 수준 유지(입력 디바운스 1.2초) | — |

---

<a id="cat-9"></a>

# 9 보안 

> 읽기 전용이라 인증·푸시·인덱스 손상 문제는 사라진다. 남는 핵심은 **열어 본 저장소의 설정이 명령을 실행하는 것**이다.

| 위협 | 대책 |
|---|---|
| 악성 저장소 설정이 읽기 명령 중 프로그램 실행(`core.fsmonitor`, `diff.external`, textconv, `core.pager`, `core.sshCommand`) | 모든 호출에 `-c core.fsmonitor=false -c core.pager=cat -c diff.external= -c core.hooksPath=NUL` + `--no-ext-diff --no-textconv`. 이 고정 인자를 우회하는 경로가 없도록 `run()` 한 곳에서만 실행 |
| 인덱스 잠금·쓰기 부작용(status가 index를 갱신) | `GIT_OPTIONAL_LOCKS=0` |
| 인자 주입(`--output=…` 등을 rev/path로) | §7 입력 검증, `--end-of-options`, path는 `--` 뒤, 리스트 인자(셸 없음) |
| 저장소 밖 경로 | `resolve_read_path` → realpath 포함 검사, 저장소 루트도 `rev-parse --show-toplevel` 결과가 ReadO 루트·허용된 외부 경로 안인지 확인 |
| 자격 증명 프롬프트로 멈춤 | 네트워크 명령 없음. 그래도 `GIT_TERMINAL_PROMPT=0`, `GCM_INTERACTIVE=never`, stdin=DEVNULL |
| 출력 인코딩·경로 깨짐 | `-c core.quotepath=off`, `-z`, `LC_ALL=C.UTF-8`, `--no-color` |
| CSRF / DNS rebinding | GET은 기존 Host 검사, AgentO 전달은 `@write_api`(토큰·Origin) |
| `safe.directory` 소유자 불일치 | 오류를 `reason:"unsafe_repo"`로 안내만. ReadO가 전역 설정을 바꾸지 않음 |
| AgentO 토큰(브리지) | `daemon.json`을 요청마다 읽고 메모리에만 보관, 로그·state.json에 기록 금지. 전송 전 지시문 미리보기·확인 필수 |

---

<a id="cat-10"></a>

# 10 참조 프로젝트 

> 라이선스는 2026-10-12 GitHub 메타데이터와 LICENSE 파일로 확인. **GPL 계열·비표준 라이선스는 코드 복사 금지, 아이디어만 참조.**

| 프로젝트 | 라이선스 | 재사용 | 가져올 것 |
|---|---|---|---|
| **VS Code SCM Graph** (`microsoft/vscode` `src/vs/workbench/contrib/scm/browser/scmHistory.ts`) | MIT | 코드 가능 | 부모 목록 → 레인 배정 + 행 단위 SVG 렌더링. 가상 리스트용으로 작고 TS라 이식 쉬움 |
| **GitHub Desktop** (`desktop/desktop` `app/src/lib/git/`) | MIT | 코드 가능 | `status --porcelain=v2 -z`, `log %x00`, `diff --numstat -z` 파서 → Python 이식 |
| VS Code git 확장 (`extensions/git/src/git.ts`) | MIT | 코드 가능 | log·blame·show 파서, Monaco diff에 `git show REV:path` 양쪽 공급 |
| GitLens | MIT(단 `plus/` 폴더는 GitKraken EULA) | `plus/` 밖만 | 줄 blame·파일/줄 History UI, `blame --incremental` 파서. 그래프는 `plus/`라 금지 |
| Gitea `services/repository/gitgraph` | MIT | 코드 가능 | `--graph` ASCII를 격자로 파싱하는 대안(레인 계산을 git에 맡김) — 페이지 이어붙이기엔 불리해 예비안 |
| lazygit `pkg/gui/presentation/graph` | MIT | 코드 가능 | 캐시를 쓰는 빠른 레인 알고리즘 |
| git-graph (Rust, git-bahn) | MIT | 코드 가능 | main을 0열에 고정하는 브랜치 열 규칙 |
| diff2html | MIT | 코드 가능 | (P3) 커밋 전체 다중 파일 diff |
| isomorphic-git / dulwich / GitPython | MIT / Apache-2.0 또는 GPL / BSD-3 | 가능 | CLI 방식이라 불필요. GitPython blame 파서만 참고 |
| **vscode-git-graph (mhutchie)** | **비표준**(MIT 유사 + 파생물 배포 금지) | **아이디어만** | IntelliJ형 로그 UX, 커밋 클릭 시 인라인 파일 목록, straight branches |
| commit-graph (npm) | npm은 MIT, 저장소는 Apache-2.0 — 불일치 | 확인 전 보류 | 작은 레인 알고리즘 |
| tig, gitk/git-gui, git-cola, Git Extensions, Forgejo, gitamine | GPL-2/3 | **아이디어만** | tig: 부모 커밋 기준 re-blame. gitk: 경로 하이라이트. Git Extensions: 레인 캐시 |
| IntelliJ, Sublime Merge, Fork, GitKraken | 비공개 | 아이디어만 | IntelliJ 3단 Log·필터 바(목표 UX), Sublime Merge 속도 |
| pvigier "Commit graph drawing algorithms"(2019) | 글 | 아이디어 | straight vs curved branches, 금지 인덱스 규칙, O(n) 레인 배정의 표준 설명 |

**추천 Top 3**: 1 VS Code SCM Graph(MIT, 레인+SVG 그대로 이식) · 2 GitHub Desktop git 파서(MIT, CLI 출력 파싱 검증됨) · 3 mhutchie Git Graph + pvigier 글(UX·알고리즘 아이디어만, 코드는 직접 작성).

---

<a id="cat-11"></a>

# 11 위험 요인 

| # | 위험 | 영향 | 대응 |
|---|---|---|---|
| 1 | **열어 본 저장소의 설정이 명령 실행**(fsmonitor·textconv 등) | 높음 — 폴더만 열어도 임의 코드 실행 | §9 고정 인자, fixture에 "마커 파일을 만드는 fsmonitor"를 넣어 실행 안 됨을 자동 검증 |
| 2 | **대형 저장소 성능**(로그 그래프·status·blame) | 높음 — 창이 멈추면 뷰어 가치가 떨어짐 | 페이지 커서 + 가상 스크롤 + 세대 취소 + 타임아웃, 10만 커밋 fixture로 수치 검증(§8.2) |
| 3 | **AgentO 연동의 결합도**: 공식 진입점 없음, WS는 비공개 프로토콜·전권 토큰 | 중 — AgentO 업데이트 시 브리지 고장, 토큰 노출 시 전 세션 조작 가능 | 기본은 클립보드(A), 브리지는 기본 꺼짐 + 폴백, AgentO에 딥링크·범위 제한 토큰 요청 |
| 4 | 에디터 구현 세션과 `source.html`·`server.py` 동시 수정 충돌 | 중 | 신규 파일 분리, 기존 파일엔 훅 몇 줄만. 착수 전 그 세션과 훅 위치 합의 |
| 5 | 하단 도구창 신설이 기존 분할 pane·Monaco 레이아웃에 영향 | 중 | `#toolwin`을 pane 컨테이너 바깥 형제로 두고 `editor.layout()` 재호출만 |
| 6 | git 미설치·구버전·`safe.directory` 오류 | 낮음 | `/info`의 `reason`으로 안내, 나머지 기능은 영향 없음 |

---

<a id="cat-12"></a>

# 12 테스트 계획 

> 헤드리스: fixture 스크립트로 임시 저장소를 만들고, `server.make_server`로 서버만 띄워 `urllib`로 API를 검증한다. UI는 기존처럼 브라우저 자동화로 스모크만.

## 12.1 fixture — `tests/git_fixture.py`

| 저장소 | 내용 | 검증 |
|---|---|---|
| `basic` | 선형 20커밋, 수정·추가·삭제·untracked, staged와 unstaged가 섞인 파일 | status 종류·x/y, diff-files 줄 수 |
| `branches` | main + feat 3개 + 머지 커밋 + 태그 + 원격 추적 ref(로컬 bare 원격) | refs, ahead/behind, log 부모·ref 라벨, 레인 수 |
| `rename` | 파일 이동 + 수정, 한글·공백 파일명, CRLF | `--follow` History, `path_at`, quotepath |
| `binary` | PNG·큰 파일(>5 MB) | `binary`/`too_big` 플래그 |
| `conflict` | 머지 충돌 상태로 멈춤, detached HEAD 변형 | `state:"merging"`, `conflicted` |
| `huge` | `git fast-import`로 커밋 10만·파일 1만 합성 | §8.2 시간 목표, 페이지 커서 연속성(중복·누락 0) |
| `malicious` | `core.fsmonitor`·`diff.external`·textconv가 마커 파일을 만드는 스크립트를 가리킴 | 모든 엔드포인트 호출 후 **마커 파일 없음** |
| `not_repo` / git 없음(`git_path`를 없는 경로로) | — | `reason` 값, 다른 API 정상 |

## 12.2 항목

| 구분 | 내용 |
|---|---|
| 인자 주입 | rev=`--output=x`, `-c`, `HEAD;calc`, path=`..\..\Windows` → 전부 `bad_arg` |
| 가드 | GET에 잘못된 Host → 거부, `/api/agento/handoff`에 토큰 없음 → 403 |
| 읽기 전용 보장 | 전체 테스트 전후 `.git` 트리 해시(refs·index·HEAD) 동일 |
| 취소·타임아웃 | 같은 kind 연속 요청 시 이전 프로세스 종료 확인, 인위적 지연으로 `timeout` |
| 레인 계산 | JS 함수를 순수 함수로 분리해 fixture 로그 결과를 기대 열 배치와 비교(브라우저 자동화로 실행) |
| AgentO 연동 | 클립보드 텍스트 내용 검증. 브리지는 가짜 WS 서버(hello/welcome/session.message 기록)로 검증 — 실제 AgentO에는 보내지 않음 |
| UI 스모크 | Alt+9로 도구창 열기 → Log 스크롤 → 커밋 클릭 → 파일 diff 열림, Blame 토글 |

## 12.3 작업량

| 단계 | 기간(1명) | 신규 코드(추정) |
|---|---|---|
| P0 기반 | 1.5일 | gitview.py ~250줄, git.js 골격 |
| P1 읽기 핵심 10항목 | 약 8일 | gitview.py +450줄, git.js ~1,500줄, git.css ~200줄 |
| P2 연동·보강 6항목 | 약 4일 | agento_bridge.py ~200줄, git.js +400줄 |
| 테스트·fixture | 2일 | tests ~400줄 |
| **합계** | **약 15일(3주)** | 기존 `server.py`·`source.html` 변경은 각 30줄 내외 |

실제 규모는 §13.1.

---

<a id="cat-13"></a>

# 13 구현 결과 

> P0 · P1 · P2를 구현했다. AgentO 데몬 WebSocket 브리지(방안 B)와 AgentO 쪽 수정·딥링크 요청은 범위에서 뺐다.

## 13.1 파일과 규모

| 파일 | 줄 수 | 내용 |
|---|---|---|
| `gitview.py`(신규) | 약 1,200 | 실행기(허용 명령·고정 `-c`·환경·세대 취소·타임아웃·Console 기록), 저장소 판별, status·decor·refs·log 세션·commit·show·blame·stash, AgentO·터미널 실행 |
| `git.js`(신규) | 약 1,570 | 도구창, Local Changes, Log(레인 계산·가상 스크롤·필터·브랜치 트리·상세), History, Stash, Console, blame, 트리 색, 상태바, AgentO 지시문 대화상자, 명령·메뉴·키·툴바 등록 |
| `git.css`(신규) | 약 180 | 라이트·다크 테마 변수 |
| `server.py` | +25 | `import gitview`·등록, `/api/git/*`·`/app/git.js|css` 라우팅, `_git()`을 gitview 실행기로 위임 |
| `source.html` | +6 | git.css·git.js 로드, `closeDiff`가 git 비교용 두 번째 모델도 해제, `openDiff` 안내 문구 초기화 |
| `build.bat` | +3 | git.js·git.css 번들, `gitview` hidden import |
| `tests/` | 약 740 | `git_fixture.py`(저장소 6종 생성), `test_git.py`(헤드리스 API 74항목 + 실측), `ui_git_smoke.py`(브라우저 36항목) |
| `NOTICE` | 신규 | VS Code SCM 그래프·GitHub Desktop 파서(MIT) 참조 표기, mhutchie Git Graph 미사용 명시 |

## 13.2 설계와 달라진 점

| 항목 | 설계 | 구현 | 이유 |
|---|---|---|---|
| Stash | Local Changes 안 | **Stash 탭**(읽기 전용 목록 + 파일 + diff) | IntelliJ Shelf 탭 자리와 맞춤 |
| 로그 페이지 | 부모 sha 커서 | **로그 세션**: 뷰마다 `git log` 하나를 띄워 두고 출력을 쌓아 offset으로 잘라 줌 | 다음 페이지 4~20ms, 순서·누락 문제 없음 |
| `/diff-files` | 별도 API | 없음 — `/commit`의 파일 목록(`diff-tree --raw --numstat` 1회)으로 충분 | 호출 수 절감 |
| AgentO 전달 | `/api/agento/*` + 브리지 | `/api/git/agento`(실행·포커스), `/api/git/terminal`. 지시문은 페이지에서 만들고 클립보드로 | 브리지는 범위 제외 |
| 파일 diff 열기 | 더블클릭 → ReadO diff 오버레이 | **단일 클릭(Enter) → 모달 diff**: 제목에 경로·커밋 해시, side-by-side/unified, ↑↓·버튼으로 이전/다음 파일(Git 창 선택이 따라감), Open in Editor, Esc·✕·바깥 클릭으로 닫기. History 행은 더블클릭 → 그 파일의 리비전을 ↑↓로 이동 | 매니저 요청(2026-10-13) — 하단 영역 대신 크게 보기 |
| History 그래프 | 레인 그래프 | 점만 표시 | `--follow`는 부모를 다시 쓰지 않아 레인이 이어지지 않음 |
| 텍스트·사용자·날짜 필터 | 레인 그래프 | 점만 표시(브랜치·경로 필터는 그래프 유지, 경로는 `--parents`로 연결) | 걸러진 커밋의 부모가 목록에 없음 |
| repo config 차단 | fsmonitor·filter·ext diff·textconv | 같음 + `core.hooksPath`·`log.showSignature=false`·`GIT_LITERAL_PATHSPECS=1`·상속 `GIT_*` 환경 제거. fsmonitor는 사용자 설정이어도 끔 | 경로 하나로 단순화 |

## 13.3 실측 (git 2.45.1, Windows 11)

| 대상 | status | refs | 로그 첫 페이지 | 다음 페이지 | 깊은 페이지(offset 5000) | 커밋 상세 | 결과 |
|---|---|---|---|---|---|---|---|
| fixture `huge` 30,000커밋·500파일 | 117 ms | 348 ms | 447 ms | 10 ms | 22 ms | 451 ms | 목표(400 ms) 근접, 1.5 s 상한 내 |
| `bsp-sales-service` 10,161커밋·7,791파일·366 ref | 125 ms | 25 ms | 82 ms | 8 ms | 12 ms | 358 ms | 목표 충족 |
| `bsp-bo` 7,250커밋·412 ref | 83 ms | 4 ms | 91 ms | 4 ms | 16 ms | 392 ms | 목표 충족 |
| `my-repo` 6,626커밋 | 152 ms | 8 ms | 88 ms | 20 ms | 17 ms | 351 ms | 목표 충족 |
| 브라우저(30k fixture) | — | — | 화면 표시 1.4 s(창 전환 포함) | 스크롤 6회에 3,300행 | — | — | DOM 행 120개 미만 |

세 실제 저장소는 측정 전후 HEAD·index·refs·logs·config 해시가 같았다(읽기 전용 확인). 커밋 상세가 350~450 ms인 것은 `show` + `diff-tree` 2회 실행의 Windows 프로세스 기동 비용이다.

## 13.4 번들 크기

| 빌드 | reado.exe |
|---|---|
| 이전(`dist-prev`) | 27,253,828 B |
| 이번(`dist`, `dist-next`) | 27,320,384 B (**+66,556 B ≈ +65 KB**, 목표 +0.2 MB 이하) |

## 13.5 검증

| 구분 | 결과 |
|---|---|
| 헤드리스 `python tests/test_git.py --huge 30000 --repo …` | 전부 통과 — status 종류·한글 경로·충돌·ahead, 트리 색, refs·stash·authors, log 필터·해시·페이지 연속성, History(rename), commit·show·blame, 인자 주입 9종 거부, Host·CSRF 가드, 쓰기 명령 실행기 거부, 악성 repo config 실행 0건(대조: 일반 `git status`는 실행됨), 거터 API 회귀, fixture·실제 저장소 무변경 |
| 브라우저 `python tests/ui_git_smoke.py <fixture>` | 36항목 통과 — 메뉴·팔레트·툴바, 두 키맵 충돌 0, Local Changes·diff·Esc, AgentO 대화상자 내용, Log 그래프·라벨·브랜치 트리 필터·텍스트 필터, 30k 페이지·가상 스크롤, History·blame on/off·Stash·Console, MERGING 배너·충돌 마커, 트리 색, 상태바, Alt+9 / Ctrl+Shift+G, 페이지 오류 0 |
| exe 스모크(`dist-next`) | 기동 → `/app/git.js`·`/app/git.css` 200, `/api/git/info` available(2.45.1), `/api/git/repos`가 C:\Projects 저장소 목록 반환 |

## 13.6 추가: Annotate with Git Blame 진입점 (2026-10-14)

| 항목 | 내용 |
|---|---|
| 진입점 | 에디터 우클릭(Monaco 메뉴, 켜져 있으면 같은 자리가 **Close Annotations**), 거터 우클릭(ReadO 메뉴: Show Diff · Show Commit in Git Log · Copy Revision Number · Annotate/Close · 줄 끝 표시 토글 · History), Git 메뉴, 팔레트 |
| 호버 | 해시 · 작성자(메일) · 날짜 · 메시지 첫 줄 툴팁. 기존 `linesDecorationsTooltip`은 Monaco 0.45에 없는 옵션이라 실제로 표시되지 않았음 → 자체 툴팁으로 교체 |
| 클릭 | 기존: Git Log에서 커밋 선택 → 변경: 그 커밋의 변경 파일을 **diff 모달**로 열고 이 파일부터 표시(↑↓로 다른 파일). Log 이동은 거터 우클릭 메뉴로 유지 |
| rename | `/api/git/blame` 커밋마다 `f`(그 커밋에서의 경로, porcelain `filename`)를 추가해 이름이 바뀐 파일도 맞는 diff를 연다 |
| 줄 끝 표시 | 설정 "Git: show the current line's commit…" / Git 메뉴 "Show Current Line's Commit at Line End", 기본 OFF(`STATE.git.lineBlame`). 커서 줄 끝에 `작성자, 상대 날짜 · 메시지`를 흐리게. 저장 안 된 편집 중에는 숨김, 저장·HEAD 변경 시 다시 계산. 같은 파일의 blame 요청은 하나로 합침 |
| 검증 | `test_git.py` blame 항목 +3(경로 추적, 클릭 대상 파일, 툴팁 필드), `ui_git_smoke.py` +12(에디터 메뉴 on/off 라벨, 호버 툴팁, 거터 메뉴, 클릭 → 모달, Close, 줄 끝 기본 OFF·표시·끄기) |

## 13.7 변경: diff 모달 → 비모달 플로팅 창 (2026-10-14)

| 항목 | 내용 |
|---|---|
| 이유 | 실제 창 피드백: 모달이 떠 있으면 Git 창·에디터를 클릭할 수 없고, 창을 옮길 수 없음 |
| 형태 | 페이지 안 플로팅 패널(OS 창 아님). 배경 dim·클릭 차단 없음. z-index 40~47(에디터·Git 창 위, ReadO 메뉴 60 아래) |
| 조작 | 타이틀바 드래그 이동, 가장자리·모서리 8곳 리사이즈(최소 380×220), □ 최대화/복원(타이틀바 더블클릭도), ✕ 닫기, 클릭·포커스 시 맨 앞으로. Esc는 포커스된 창만 닫음 |
| 위치 | 화면 밖으로 못 나가게 제한(앱 창 크기 변경 시 다시 맞춤). 마지막 위치·크기를 `STATE.git.dwin`(state.json)에 저장, 다음 첫 창이 그 자리에 열림 |
| 여러 창 | 파일+리비전(`L:<repo>\|path`, `C:<hash>\|path`)마다 창 하나. 같은 것을 다시 열면 기존 창을 앞으로. 새 창은 맨 앞 창에서 26px씩 cascade. 최대 8개, 넘으면 가장 오래된 창을 닫음 |
| 진입점 | Local Changes·커밋/스테시 파일 클릭, 파일 우클릭 Show Diff, History 행 더블클릭, Blame 주석 클릭이 모두 같은 창(`openDiffWin`)을 씀. ↑↓ 파일 이동은 창 안에서 그대로 |
| 검증 | `ui_git_smoke.py` diff 항목 28개로 교체(전체 76항목 통과): 오버레이 없음, 모서리 리사이즈, 타이틀바 이동, 화면 밖 제한, 위치·크기 기억, 열린 채로 부모 클릭 → 두 번째 창(cascade), 같은 파일 → 앞으로, 창 클릭 → z-order, Esc는 한 창만, 최대화/복원, 8개 상한, 열린 채로 에디터 클릭 |

## 13.8 변경: Annotate 표시를 IntelliJ와 같게 (2026-10-14)

| 항목 | 내용 |
|---|---|
| 칼럼 순서 | 주석 → 줄 번호 → 코드. Monaco 0.45의 line-decorations 칸은 줄 번호 오른쪽이고 `lineNumberClassName`이 없어서, 줄 번호 칸을 넓히고(`lineNumbersMinChars`) 그 왼쪽 160px에 margin 데코레이션(`marginClassName`)으로 그린다. 줄 번호는 오른쪽 정렬 그대로, 커서 줄 번호 강조도 Monaco 기본 |
| 글자 | `M/D/YYYY 작성자`를 **모든 줄에** 반복(로케일 무관), 흐린 회색 12px 고정폭 글꼴, 긴 이름은 말줄임 |
| 음영 | 커밋 단위 배경. 파일 안 커밋들의 시간 순위로 농도를 정함 — 오래된 25%는 음영 없음, 최신일수록 진한 파랑. 라이트 최대 알파 .30, 다크 .42 |
| 줄바꿈·접힘 | 음영 데코(whole-line)는 줄바꿈된 모든 행에, 글자 데코(빈 범위)는 첫 행에만. 접힌 줄은 그려지지 않음. 줄 번호와 같은 margin 행 안에 그려서 스크롤·줄 높이가 어긋날 수 없음 |
| 마우스 | 주석 칸 클릭은 Monaco의 줄 선택 대신 커밋 diff 창을 연다(편집기 컨테이너에서 capture 단계로 가로챔 — Monaco는 모델을 바꿀 때마다 자체 DOM 노드를 새로 만들므로 컨테이너에 건다). 호버 툴팁·우클릭 메뉴는 그대로 |
| 함께 고침 | Log: 같은 뷰 요청이 겹치면 앞의 `git log`가 kill되어 "git log exited 1"이 표시되던 경쟁 → kill된 세션은 오류로 보지 않고 다음 세션 결과를 받는다(`test_git.py` 동시 reload 항목 추가) |
| 검증 | `ui_git_smoke.py` +5: 칼럼 순서(주석 0~160 \| 번호 188 \| 코드 221), M/D/YYYY 형식, 줄마다 한 개·제 행, 커밋별 음영(가장 오래된 것 무음영, 최신일수록 진함), 줄바꿈 시 글자 첫 행·음영 전체 행. 접힘은 별도 probe로 확인 |

## 13.9 변경: Local Changes 좌우 분할 (2026-10-14)

| 항목 | 내용 |
|---|---|
| 배치 | 왼쪽 파일 트리(기존 그대로: 그룹·체크박스·툴바), 가운데 분할선, 오른쪽 인라인 diff. 분할선 드래그로 왼쪽 폭 조절(200px~, `STATE.git.cw`에 기억, 기본 420) |
| 오른쪽 | `DiffPane` — 플로팅 diff 창과 같은 헤더·Monaco diff 편집기·`showDiffItem`을 재사용. 헤더: 경로, `HEAD ↔ Current version`(열린 파일이면 `HEAD ↔ editor`), 이전/다음 변경(`goToDiff`), Side by side/Unified, 공백 무시(Do not ignore 기본, `STATE.git.ignoreWs`, 플로팅 창에도 적용), Open in Editor, Show in Window. 선택이 없으면 "Select a file to see its changes" |
| 동작 | 단일 클릭·↑↓(파일 행) → 오른쪽 갱신(폴더 행에서는 유지). 더블클릭·Enter·우클릭 "Show Diff in Window"·툴바 diff → 플로팅 창. 상태가 바뀌면 선택 파일 diff를 다시 읽음 |
| 다른 탭 | Log·History·Stash의 파일 클릭은 그대로 플로팅 창 |
| Log 적용 여부 | 기술적으로는 가능(같은 `DiffPane`을 커밋 상세 칸에 붙이면 됨). 다만 Log는 이미 브랜치·목록·상세 3단이라 4단이 되면 기본 높이 300px 창에서 좁다. 상세 칸을 "파일 트리 \| diff"로 바꾸는 토글 방식을 제안하고, 이번에는 적용하지 않음 |
| 검증 | `ui_git_smoke.py` 분할 항목 14개: 좌우 배치·안내 문구, 클릭 → 오른쪽 diff(창 없음), 헤더, ↓ 폴더 행 유지·파일 행 갱신·↑ 복귀, 공백 옵션, 다음 변경, 분할선 드래그·기억, 더블클릭 → 창, 우클릭 Show Diff in Window. 기존 diff 창 테스트는 Local Changes 진입을 더블클릭으로 바꿈 |

## 13.10 변경: diff 창을 OS 별도 창으로 (2026-10-14)

| 항목 | 내용 |
|---|---|
| 이유 | 매니저 피드백: 페이지 안 플로팅 패널은 본창 안에서만 움직이고 본창을 가림 → 진짜 별도 창 |
| 구조 | 본창 페이지가 파일 목록을 **해석된 형태**(쪽마다 revision + path, 제목, ident)로 `POST /api/git/diffwin`에 보냄 → `gitview.DIFFWIN`이 창 단위를 관리 → `reado.py`의 `DiffWindowBackend`가 pywebview `create_window`로 `/diffwin?id=…`(diffwin.html + diffwin.js, 같은 서버·같은 토큰)를 연다. 창 안은 `/api/git/show`로 양쪽을 읽어 Monaco diff로 그림 |
| 창 | 기본 Windows 타이틀바(본창의 커스텀 프레임은 쓰지 않음 — 허용 범위), 앱 아이콘, 제목 `파일명 · 커밋해시`(로컬은 `· local changes`). 본창 밖·다른 모니터로 자유 이동·리사이즈 |
| 관리 | 파일+리비전(ident)마다 창 하나, 같은 ident 재요청은 restore + 앞으로. 최대 8개, 넘으면 가장 오래 연 창을 닫음. ↑↓로 파일을 바꾸면 그 창의 ident·제목이 따라감(`/api/git/diffwin-nav`). Esc → `/api/git/diffwin-close`. 본창 `closed` 이벤트에서 전부 닫음(pywebview는 남은 창이 있으면 계속 돌기 때문) |
| 위치 | 마지막으로 닫힌 창의 위치·크기를 `%APPDATA%\ReadO\diffwin.json`에 저장(state.json은 본창 페이지가 통째로 덮어쓰므로 분리), 새 창은 열려 있는 최신 창에서 28px cascade |
| Open in Editor | `/api/git/diffwin-edit`(열린 창 id만 허용) → 본창 `openFile(key, line)` + 본창 앞으로 |
| 보안 | 항목마다 revision(HEAD·WORKTREE·INDEX·hex만)과 경로(`_check_rel`) 검증, 저장소는 기존 `repo_of` 규칙, 쓰기 API 토큰·Host 가드 그대로 |
| 스레드·exe | pywebview 6.2.1은 시작 후 다른 스레드에서의 `create_window`/`destroy`/`set_title`/`run_js`를 GUI 스레드로 넘김 → HTTP 핸들러에서 직접 호출. 두 번째 실행 전달(instance.json)과 무관. PyInstaller에 diffwin.html·diffwin.js 추가 |
| 폴백 | pywebview 백엔드가 없으면(브라우저 모드 `python server.py`, 테스트) 서버가 `native: false`를 돌려주고 기존 인페이지 패널로 연다. 패널 코드는 이 폴백 용도로만 남김 |
| 알려진 차이 | 창은 디스크의 작업 트리를 비교(본창 편집기의 저장 안 된 내용은 반영 안 됨, 인페이지 패널·오른쪽 인라인 diff는 반영). 창 안의 Unified·공백 옵션은 그 창에만 적용(저장 안 함) |
| 검증 | `test_git.py` +15(가짜 백엔드: 생성·URL·제목, /diffwin 페이지, 재사용, ↑↓ 제목, Open in Editor·위조 id 거부, 8개 상한, 잘못된 revision·경로·저장소·토큰 거부, Esc, 본창 종료 시 전부 닫힘). `ui_git_smoke.py` +10(본창 더블클릭 → 창 요청·재사용, 창 페이지 렌더·제목·↓·모드·공백·Open in Editor·Esc). **exe 스모크**(dist 빌드, 격리 APPDATA, 실제 WebView2 창): 별도 최상위 창·제목, 독립 이동·리사이즈, 재사용, 9개 → 8개, 본창 WM_CLOSE → 프로세스 정상 종료, diffwin.json 저장, PrintWindow 캡처로 diff 렌더 확인 |

## 13.11 변경: Annotate 모든 줄 표시 확인 · 호버 툴팁 IntelliJ 형식 (2026-10-14)

| 항목 | 내용 |
|---|---|
| 모든 줄 | 13.8에서 이미 줄마다 데코레이션 1개(`gbl`)로 `M/D/YYYY 작성자`를 그림 — 같은 커밋이 이어지는 줄에도 반복. 코드 변경 없음, 테스트만 추가 |
| 줄바꿈 | 텍스트 데코레이션은 `isWholeLine` 없이 줄 첫 칸 범위라 첫 시각 줄에만, 음영(`gba`)은 모든 시각 줄. 거터 행 높이 = lineHeight 확인 |
| 툴팁 | `commit <전체 해시>` / `Author: 이름 <메일>` / `Date: M/D/YYYY h:mm AM/PM` / 빈 줄 / 메시지 (pre-wrap 한 블록). 처음엔 blame의 subject, 첫 호버 때 `/api/git/commit`으로 전체 메시지를 받아 커밋별 캐시 후 교체. 이전의 "click / right-click" 안내 줄은 뺌 |
| 검증 | `test_git.py` +3(app.py 25/25줄 커밋 매핑·연속 5줄 같은 커밋, author-mail, 전체 메시지). `ui_git_smoke.py` +3(툴팁 형식 정규식, 줄바꿈 행 높이, 연속 같은 커밋 2~6줄 모두 표시 + 중간 줄 호버 시 전체 메시지) |

## 13.12 추가: Log 칼럼 폭 조절 · 표시 선택 (2026-10-15)

| 항목 | 내용 |
|---|---|
| 이유 | 매니저 피드백: Author·Date·Hash 칼럼이 너무 넓다. 폭 조절과 표시 여부 선택이 필요 |
| 헤더 | Log·History 목록 위에 `Subject · Author · Date · Hash` 헤더(20px). 스크롤바 폭만큼 오른쪽 여백을 줘 행과 정렬 |
| 폭 | 각 칼럼 왼쪽 경계를 드래그(왼쪽으로 끌면 넓어짐), 최소 Author 50 · Date 60 · Hash 50, 최대 480. 경계 더블클릭은 기본폭. 기본폭은 내용에 맞춰 Author 100 · Date 125 · Hash 70(이전 120 · 140 · 70 + 패딩) |
| 표시 | 헤더 우클릭 메뉴: Subject(항상 켜짐, 비활성) · Author · Date · Hash 체크, Reset Column Widths |
| 좁은 창 | 뷰마다 `layoutLogCols`가 목록 폭을 보고, 칼럼 합이 남은 폭(목록의 65%, 최소 메시지 120px 확보)을 넘으면 비율로 줄여 CSS 변수 `--gl-au/dt/hs`로 지정. 헤더와 행이 같은 값을 쓰므로 어긋나지 않음. `.gl-list`는 `overflow-x: hidden` |
| 저장 | `STATE.git.logCols = {au: {w, on}, dt: …, hs: …}` → state.json. `logCols()`는 값을 제자리에서 보정(드래그 중 잡고 있는 객체가 바뀌지 않게) |
| 검증 | `ui_git_smoke.py` +13: 헤더, 기본폭·말줄임 없음, 드래그 100→140(헤더·행·상태), 최소폭, 더블클릭 복원, 우클릭 메뉴, Hash·Date 숨김 시 메시지 확장, 1000px·760px 창에서 가로 스크롤 없음·정렬, state.json, 새 페이지(다음 실행)에서 유지, Reset. "branch tree" 체크는 refs 로드를 기다리게 고침 |

## 13.13 추가: Log 복수 커밋 선택 (2026-10-15)

| 항목 | 내용 |
|---|---|
| 이유 | 매니저 피드백: 커밋을 여러 개 골라 그 커밋들의 파일 전부를 보는 일이 많다 |
| 선택 | Ctrl+클릭 토글, Shift+클릭 앵커부터 범위(Ctrl+Shift는 추가), Shift+↑↓/PgUp/PgDn 범위 확장, Ctrl+A 로드된 전체, Ctrl+C 해시 목록(줄바꿈). 선택은 해시 집합(`selH`)이라 새로고침해도 유지. 리드 행은 왼쪽 강조선. 우클릭은 선택된 행이면 선택 유지 |
| 서버 | `POST /api/git/commits {repo, revs}`(해시 수백 개는 URL에 안 들어감. 읽기 전용이지만 쓰기 API와 같은 토큰·Host 검사). revs는 전체 해시만, 2~5000개. ① `rev-list --parents -n1 oldest` → base(가장 오래된 커밋의 첫 부모, 루트면 빈 트리) ② `rev-list --max-count=n+1 newest ^base`가 선택과 같으면 **연속 범위** ③ 범위: `diff-tree base newest` 한 번. 아니면 `git log --no-walk=unsorted -m --first-parent --raw --numstat -z` 한 번(최대 500개, 나머지는 `partial`)으로 커밋별 변경을 받아 파일별 병합 + base↔newest `diff-tree` 한 번(각 파일 diff용 상태 `bh`) |
| 병합 규칙 | 같은 경로는 한 번. 상태: 처음 A이고 끝이 D가 아니면 A, 끝이 D이고 처음이 A가 아니면 D, 처음 R/C면 R/C, 나머지 M. 추가/삭제 줄 수 합산, `n` = 그 파일을 바꾼 선택 커밋 수(트리에 "3 commits" 태그). 머지 커밋은 단일 커밋 보기와 같이 첫 부모 기준 |
| 파일 diff | 연속 범위: base ↔ newest(IntelliJ 방식). 비연속: 같은 base ↔ newest 비교를 쓰고 상세 칸 상단에 "not one range … can include commits in between that are not selected"로 표시(커밋별 diff 이어 붙이기는 하지 않음). 창 제목·해시는 `base..newest`, ident는 `M:base..head|path`라 단일 커밋 창과 섞이지 않음 |
| 상세 칸 | 위에 요약(`N commits selected · F files` + 범위/비연속 안내), 가운데 병합 파일 트리, 아래 선택 커밋 목록(최대 200, 해시 클릭 시 그 커밋만 선택, "copy N hashes"). 단일 선택은 기존 그대로 |
| 우클릭 | 복수 선택 시 Copy Revision Numbers (N), Copy Subjects (N)만 활성. Show in Log·AgentO 항목은 비활성 |
| 성능 | 30,000커밋 저장소: 연속 800개 0.3s, 흩어진 600개(500개 나열) 0.6s. 응답이 늦게 와도 세대 번호로 버림 |
| 검증 | `test_git.py` +14(범위·base, 병합·합산·A 상태, 정렬, 머지 커밋, 루트까지 범위, 1개·옵션형 rev·토큰 없음 거부, huge 범위·partial). `ui_git_smoke.py` +14(Ctrl+클릭, 강조, 요약, 병합 트리, base..newest diff, 우클릭 메뉴·선택 유지, Shift+클릭 범위, Shift+↓, Ctrl+A, Ctrl+C, 단일 선택 회귀 2) |

---

<a id="cat-14"></a>

# 14 툴바 Git 그룹 · AgentO 딥링크 요청 스펙(v1, 초안) 

> 상단 툴바에서 현재 브랜치를 보여 준다. Pull은 ReadO가 직접 실행하고, Commit·Push는 AgentO에 요청한다(2026-10-16). **현재 단계**: Commit·Push는 기존 방식대로 지시문을 클립보드에 복사하고 AgentO를 띄운다. `agento://` 딥링크(§14.3)는 AgentO 핸들러가 준비되면 켠다. 서버 API와 테스트는 이미 있고, `git.js`의 `USE_DEEPLINK = false`로 꺼 두었다.

## 14.1 툴바와 상단 바 정리

| 항목 | 내용 |
|---|---|
| 대상 저장소 | 활성 파일이 속한 저장소(`/api/git/info?path=`, 폴더별 60초 캐시)다. 열린 파일이 없으면 Git 도구창에서 고른 저장소를 쓴다 |
| 브랜치 버튼 | 브랜치 아이콘, 브랜치 이름(13px 굵게, 말줄임), ↑ahead ↓behind(0이면 숨김)를 보여 준다. 클릭하면 브랜치 팝업([§14.4](#sec-14-4))이 열린다. 우클릭하면 Git 도구창 Log 탭이 그 저장소로 열린다(2026-10-21에 클릭·우클릭을 바꿨다). 툴팁에는 저장소, upstream, 경로를 보여 준다 |
| Pull ↓ | ReadO가 직접 실행한다(§1 결정 2a). 비활성 조건은 git 없음, 저장소 아님, detached, upstream 없음, merge·rebase 진행 중, 실행 중이다 |
| Commit ✓ · Push ↑ | AgentO 요청 버튼이다. 점선 테두리와 `A` 표시로 Pull과 구분하고, 툴팁은 "AgentO에 요청(head coach에게 전달)"이다. Commit은 대상 파일 목록(Local Changes에서 체크한 파일, 없으면 변경 전부)과 선택 입력인 메시지 초안을 받는다. Push는 확인창을 거친다. 지금은 두 버튼 모두 지시문을 복사하고 AgentO를 띄운다(토스트: "AgentO에 보낼 commit 지시문을 복사했습니다"). Commit은 변경 파일이 없으면, Push는 ahead 0이면(upstream이 있을 때) 비활성이다. git commit·push를 실행하는 코드는 없다 |
| 새로고침 | 활성 파일이 바뀌면 바로, 그 밖에는 4초마다 fingerprint를 확인한다. 바뀌었거나 8초가 지나면 status를 다시 읽는다. 창 포커스, pull, 요청 후에는 즉시 갱신하고, 같은 저장소면 Log·Local Changes·상태바도 갱신한다 |
| 브레드크럼 | 작업 폴더 아래에 있는 저장소면 경로에서 저장소 폴더 세그먼트를 칩(굵게, 강조 배경)으로 표시한다. 작업 폴더 자체가 저장소이거나 저장소 안에 있으면 칩 없이 폴더 칩만 보인다 |
| 검색창 | 플레이스홀더를 "Go to file (Ctrl+P) · Commands (Ctrl+Shift+P) · Find in Files (Ctrl+Shift+F)"로 바꿨다. 팔레트 모드 탭은 Files · `>` Commands · `%` Text · `#` Symbols다. `%`는 폴더 전체 일반 텍스트 검색(최대 300줄)이다. 첫 줄 또는 Ctrl+Enter, Ctrl+Shift+F를 누르면 같은 검색어로 Find in Files 창이 열린다. 툴바의 Find in Files 버튼은 제거했고, 창과 단축키는 그대로다 |
| 설정 | 톱니 아이콘을 왼쪽 도구창 스트립 맨 아래(Git 아래)로 옮겼다. 테마 토글은 오른쪽에 그대로 둔다 |
| 좁은 창 | compact에서는 라벨과 ↑↓를 숨기고 브랜치 이름 최대폭을 150px로 줄인다. tiny에서는 브랜치 이름도 숨겨 아이콘만 남는다(file·view 그룹은 `⋯`로 접힘) |

## 14.2 Pull 동작

| 단계 | 내용 |
|---|---|
| 확인창 | `GET /api/git/pullinfo?repo=`로 저장소, 브랜치 ← upstream, 원격 이름과 URL(`user:pass@` 제거), 로컬 변경 수, 저장 안 된 편집 파일 수를 보여 준다 |
| 실행 | `POST /api/git/pull {repo, unsaved[], allow_unsaved}`(`write_api`: CSRF 토큰, Host·Origin 검사, `repo_of` 경로 검증). `git fetch <remote>`를 실행한 뒤 HEAD와 `@{upstream}`을 비교한다. 같거나 upstream이 HEAD의 조상이면 "Already up to date"다. HEAD가 upstream의 조상이 아니면 `non_ff`로 멈춘다 |
| 저장 안 된 편집 | 들어올 파일(`diff-tree HEAD..upstream`)과 페이지의 저장 안 된 파일이 겹치면 `need_confirm: "unsaved"`로 멈추고 다시 묻는다 |
| 병합 | `git merge --ff-only <fetch한 sha>`를 실행한다. 로컬 변경을 덮어쓰게 되면 git이 거부하므로(`local_changes`) 아무것도 바뀌지 않는다 |
| 제한 | 단계마다 60초 타임아웃이 있다. `GIT_TERMINAL_PROMPT=0`, `GCM_INTERACTIVE=never`, 빈 `GIT_ASKPASS`를 쓰고, 자격 증명이 필요하면 `auth` 오류로 안내한다. hooks는 끄고(`core.hooksPath=NUL`), 저장소별 쓰기 잠금(pull·fetch·checkout 공용)을 건다(`busy`). 허용 명령은 `WRITE_CMDS={fetch, merge, switch}`이고 `pull()`·`fetch()`·`checkout()`만 고정 옵션으로 쓰며, `run()`은 여전히 읽기 전용만 허용한다 |
| 결과 | 성공(커밋·파일 수)과 이미 최신은 토스트로 알린다. 거부·실패(비FF, 로컬 변경, 인증, merge·rebase 진행 중)는 대화상자에 이유, ReadO가 merge·rebase·강제 실행을 하지 않는다는 안내, git 출력 끝부분을 보여 주고 [Stash Changes… (AgentO)]·[show Console]을 제공한다. 명령과 출력은 Console 탭에 기록된다(`out` 필드) |
| 실행 위치 | 툴바 Pull, Git 도구창 머리의 `↓ Pull`, 브랜치 팝업, Git 메뉴·팔레트 `Pull (fast-forward only)` |
| 성공 뒤 갱신 | 서버: status·refs 캐시를 비우고 파일 목록과 ctags 인덱스를 백그라운드로 다시 만든다(`server.source_changed`). 페이지(`refreshSource`): 열린 파일 중 수정 안 된 파일은 다시 읽고, 수정 중인 파일은 덮어쓰지 않고 "changed on disk — saving will ask"로 표시한다. 디스크에서 없어진 파일 탭은 삭제됨으로 표시한다. 파일 트리를 다시 그리고, 변경 줄 표시·상태바 브랜치, Git 도구창, 툴바도 갱신한다 |

<a id="sec-14-4"></a>

## 14.4 Fetch · 브랜치 Checkout (2026-10-21)

| 항목 | 내용 |
|---|---|
| 브랜치 팝업 | 툴바 브랜치 칩 클릭, 상태바 브랜치, Git 도구창 머리의 `⎇ 브랜치` 버튼, Git 메뉴 `Branches…`에서 연다. 맨 위에 현재 브랜치(`Current: main → origin/main ↑1 ↓0`, detached·merge 상태 포함), 이어서 Pull·Fetch·Show Log·New Branch(AgentO)·Push(AgentO), **Local**·**Remote** 목록이 있다. 위쪽 입력란으로 거른다. 현재 브랜치는 강조하고 `✓ current`, 로컬 브랜치는 ↑↓와 upstream gone을 보여 준다. 원격 브랜치에는 추적 중인 로컬 브랜치(`local main`) 또는 `new local branch`를 표시한다. 고르면 바로 checkout한다 |
| Checkout API | `POST /api/git/checkout {repo, ref, unsaved[], allow_unsaved}`(`write_api`, `repo_of`). ref는 `refs/heads/x` 또는 `refs/remotes/<원격>/x`만 받고, 실제로 있는 ref인지 `for-each-ref` 결과와 대조한다. 그 밖(태그, HEAD, 옵션 모양, 없는 브랜치)은 `bad_arg`(400)다 |
| 로컬 브랜치 | `git switch --no-guess x` |
| 원격 전용 브랜치 | 원격 이름(가장 긴 일치)을 떼어 로컬 이름을 정하고 `git switch --no-guess --create x --track <원격>/x`로 추적 브랜치를 만들며 이동한다. 같은 이름의 로컬 브랜치가 그 원격 브랜치를 이미 추적하면 그 브랜치로 이동한다. 다른 것을 추적하거나 추적하지 않으면 `local_exists`로 멈추고, 화면에서 그 로컬 브랜치로 갈지 묻는다(reset·rename은 하지 않는다) |
| 안전장치 | 강제 옵션(`-f`, `--discard-changes`, `--merge`)은 쓰지 않는다. 로컬 변경이 걸리면 git이 거부하고 아무것도 바뀌지 않는다(`local_changes`). 대화상자에 git 메시지를 그대로 보여 주고 stash를 안내한다(Stash Changes… → AgentO). merge·rebase 진행 중이면 `repo_busy`로 실행하지 않는다 |
| 저장 안 된 편집 | 그 저장소에 저장 안 된 편집이 있으면 checkout 전에 파일 목록과 함께 [save all and check out]·[cancel]을 묻는다. 저장하면 로컬 변경이 되므로 git이 가져가거나 거부한다. 서버도 바뀔 파일과 `unsaved`가 겹치면 `need_confirm`으로 멈춘다 |
| Fetch API | `POST /api/git/fetch {repo}`: `git fetch --prune <현재 브랜치의 원격>`(원격이 없으면 git 기본값). 작업 트리와 HEAD는 바뀌지 않는다. 결과 토스트에 upstream 기준 ↑↓를 보여 준다. Git 도구창 `Fetch`, 브랜치 팝업, Git 메뉴에서 실행한다 |
| 갱신 | checkout 성공 뒤에는 Pull과 같다([§14.2](#cat-14) 성공 뒤 갱신). 없어진 파일 탭은 삭제됨으로 표시하고, 새 파일은 트리에 나타난다 |
| 명령 기록 | 모든 단계가 Console 탭에 출력과 함께 남는다. 저장소별 쓰기 잠금, 60초 타임아웃, 프롬프트 없음, hooks 끔은 Pull과 같다. git 2.24 미만이거나 git이 없으면 API가 그 이유로 거부하고 UI도 꺼진다 |
| AgentO 메뉴 | Pull·Fetch는 ReadO가 직접 하므로 AgentO ▾ 메뉴와 Git ▸ AgentO 하위 메뉴에서 뺐다. Commit·Push·New Branch·Stash·Merge·Rebase·Delete는 계속 AgentO 담당이다(`USE_DEEPLINK` 그대로) |

<a id="sec-14-5"></a>

## 14.5 줄바꿈(CRLF/LF)만 다른 변경 (2026-10-21)

| 항목 | 내용 |
|---|---|
| 원인(재현) | 저장소에 LF로 들어 있는 파일을 편집기나 도구가 CRLF로 다시 쓰면 `core.autocrlf=false` 또는 `input`에서 `git status`가 수정으로 보여 준다. `autocrlf=true`에서는 CRLF로 커밋된 파일이 LF로 바뀐 경우에 보인다. `git diff HEAD --numstat --ignore-cr-at-eol`은 이런 파일을 아예 목록에서 뺀다. 들어오는 커밋이 그 파일을 바꾸면 `merge --ff-only`·`switch`가 "would be overwritten"으로 거부한다(내용은 같아도 git에는 로컬 변경이다) |
| 판정 | status의 수정 파일 중 인덱스나 작업 트리 한쪽이 HEAD와 같은 파일(XY에 `.`)만 `git diff HEAD --numstat --ignore-cr-at-eol --no-textconv --no-ext-diff -z -- <경로>`로 확인해 `eol: true`를 붙인다. 진짜 변경을 스테이징한 MM 파일은 숨기지 않는다. 결과는 파일별(HEAD, mtime, 크기)로 캐시해 status 폴링마다 다시 계산하지 않는다. 한 번에 최대 3000개, 명령줄 2.4만 자 단위로 나눠 실행한다 |
| 비용 | 2000개 파일 기준 첫 status +1.2초, 이후 status의 확인 비용 약 25ms(stat만 한다) |
| Local Changes | 기본은 숨긴다. 요약에 "N files · M line-ending-only hidden"이 표시된다. 바 버튼 [Show line-ending-only changes](Git 메뉴에도 있음, 설정 저장)를 누르면 흐리게 보이고 "line endings only" 태그가 붙는다. 툴바 Commit 개수, Commit 대상 기본 목록, 파일 트리 색(`/api/git/decor?eol=1`일 때만 포함)도 같은 기준을 따른다 |
| diff | 헤더에 [Ignore line endings] 버튼이 있다(Local Changes 오른쪽 diff, 플로팅 diff 창, OS diff 창, Git 메뉴 "Diff: Ignore Line Endings"). 기본은 켬이다. Monaco는 줄을 CR·LF 모두에서 나누므로 켜면 CRLF↔LF 차이가 변경으로 보이지 않는다. 끄면 CR을 `␍`로 그려 줄바꿈이 바뀐 줄이 변경으로 보인다. 이때 열린 편집 문서는 읽기 전용 복사본으로 보여 준다. 양쪽 줄바꿈 형식이 다르면 헤더 설명에 "line endings LF → CRLF"를 붙인다. 설정은 메인 창 상태에 저장하고, OS diff 창은 그 값으로 시작한다(창 안 토글은 그 창에만 적용) |
| Pull·Checkout 거부 | git이 나열한 "in the way" 파일 중 줄바꿈만 다른 파일을 `eol_files`로 돌려준다. 대화상자는 그 파일과 "git은 여전히 로컬 변경으로 본다", 현재 `core.autocrlf` 값, 해결 방법(core.autocrlf·`.gitattributes` 확인 후 `git checkout -- <file>` 또는 `git add --renormalize .`, AgentO에 요청)을 안내한다. ReadO는 파일을 되돌리거나 덮어쓰지 않고, `checkout -- .`·`reset --hard`도 하지 않으며, 저장소 설정도 바꾸지 않는다. Pull 확인창은 로컬 변경 수와 그중 줄바꿈만 다른 수를 함께 보여 준다 |
| 읽기 명령 | `diff`를 READ_ONLY에 넣었다. `--output`·`--ext-diff`·`--textconv`는 `_check_allowed`에서 거부한다 |
| 에디터 저장 | 서버는 받은 텍스트를 그대로 쓴다. Monaco 모델은 파일 전체가 CRLF이거나 LF이면 그 형식을 유지해 저장한다(테스트로 확인). **줄바꿈이 섞인 파일은 열 때 많은 쪽 형식으로 통일되어**, 저장하면 다른 줄의 줄바꿈도 바뀐다(Monaco 모델의 한계라 에디터 코드는 고치지 않았다) |

<a id="sec-14-6"></a>

## 14.6 Changelist (2026-10-23)

git에는 changelist가 없다. IntelliJ처럼 Local Changes를 묶어 보는 ReadO 자체 메타데이터다. git·인덱스·작업 트리·설정은 건드리지 않는다.

| 항목 | 내용 |
|---|---|
| 저장 | `%APPDATA%\ReadO\changelists.json`(config.json 옆). 저장소 경로(`normcase`)를 키로 `{lists:[{id, name, desc}], active, files:{경로: list id}}`. 저장소 안에는 아무 파일도 만들지 않는다. 임시 파일 + fsync + `os.replace`로 원자적으로 쓴다. 파일이 깨졌거나 형식이 틀리면 무시하고 기본 상태에서 시작하며, 다음 변경 때 새로 쓴다. 저장소는 최근 변경 순으로 200개까지, 저장소당 목록 50개·파일 2만 개까지 |
| 기본 목록 | `Changes`(id `default`)는 항상 있고 삭제할 수 없다(이름·설명은 바꿀 수 있다). 목록이 이것 하나뿐이고 따로 배정한 파일이 없으면 아무것도 저장하지 않는다 |
| 배정 규칙 | 항목이 없는 tracked 변경 파일은 기본 목록이다. 다른 목록이 활성이면 새로 생긴 변경 파일을 활성 목록으로 적어 둔다(활성으로 바꾸는 순간의 기존 변경은 기본 목록으로 고정). untracked 파일은 옮기기 전까지 Unversioned Files에 있고, 충돌 파일은 항상 Merge Conflicts에 보인다(항목은 머지 뒤를 위해 남긴다) |
| 정리 | status 결과마다 맞춘다: 더 이상 변경이 아닌 파일(커밋·되돌리기)의 항목은 지우고, rename(`orig`)은 새 경로로 옮긴다. status가 잘렸으면(`truncated`) 지우지 않는다. 바뀐 것이 있을 때만 쓴다. 저장소 전환·브랜치 checkout·재시작 뒤에도 유지된다 |
| API | `GET /api/git/status` 응답에 `changelists`가 붙는다. `POST /api/git/changelist {repo, op}`(`write_api`: CSRF, Host/Origin, `repo_of`). op: `new {name, desc, active?, files?}`, `edit {id, name, desc}`, `delete {id}`, `active {id}`, `move {to, files[]}`(`to`가 `unversioned`이면 untracked 파일을 Unversioned Files로 되돌린다). 이름은 1~60자, 제어 문자 금지, 대소문자 무시 중복 거부(`name_taken`). 설명은 1000자까지(줄바꿈·탭만 허용). 경로는 `_check_rel`로 검사하고, 변경이 아닌 파일은 건너뛴다 |
| 화면 | Local Changes 트리가 목록별 그룹(파일 수, 접기·펼치기)이다. 목록이 둘 이상이면 활성 목록에 `active` 태그가 붙고, 설명은 그룹 툴팁이다. 목록이 하나면 이전 화면과 같다. 폴더 트리, 체크박스(그룹 체크 = 목록 전체), staged 배지, 줄바꿈 숨김 토글은 그대로다. 목록 사이를 옮겨도 체크 상태는 유지된다 |
| 선택·이동 | Ctrl·Shift+클릭으로 여러 파일을 고른다. 우클릭 **Move to Changelist…**(목록 + Unversioned Files(untracked일 때) + New Changelist…), 또는 파일을 목록 그룹 위로 끌어다 놓는다(HTML5 drag and drop) |
| 우클릭 메뉴 | 파일·폴더·그룹 공통: Commit… (AgentO), Rollback… (AgentO), Show Diff, (파일) Open File·Show History·Copy Path, Move to Changelist…, New Changelist…, Edit Changelist…, Delete Changelist, Set Active Changelist, Resolve Conflict… (AgentO), Refresh. 대상이 맞지 않는 항목은 회색이다 |
| Commit·Rollback | 기존 AgentO 지시문 대화상자(`agentDialog`) 그대로, 대상은 그 목록(또는 선택) 파일만이다. 파일들이 한 사용자 목록에 있으면 목록 이름이 커밋 메시지 초안, 설명이 본문 초안이 된다. Rollback은 "diff를 보여 주고 확인을 받아 줘" 규칙 그대로다. Shelve는 이번 범위가 아니다 |

<a id="sec-14-7"></a>

## 14.7 저장소 선택 메뉴 (2026-11-03)

Git 창 머리의 저장소 선택이 네이티브 `<select>`였다. 펼친 목록이 OS 기본 모양(흰 배경)이라 옆 브랜치 메뉴·앱 테마와 달랐다. 브랜치 메뉴와 같은 팝업(`.gpick`, 테마 변수)으로 바꿨다.

| 항목 | 내용 |
|---|---|
| 버튼 | `.gw-repo` 버튼: 선택한 저장소 이름 + 변경 수 배지 + ▾. 저장소가 하나면 숨긴다(이전과 같음). 툴팁은 저장소 경로 |
| 메뉴 | 필터 입력(이름·폴더 경로), 저장소마다 이름 · 열린 폴더 기준 위치(이름과 다를 때) · 선택 표시 ✓ · 변경 수 배지. 충돌이 있으면 빨간 배지, 세는 중이면 `…`. 줄바꿈만 다른 파일은 Local Changes처럼 숨김 설정을 따른다 |
| 키보드 | 열면 필터에 포커스, 현재 저장소가 강조된다. ↑↓ 이동, Enter 선택(필터 결과의 첫 항목 포함), Esc 닫기. 버튼을 다시 누르면 닫힌다 |
| 동작 | 고르면 기존 `selectRepo` 그대로: Git 창 전환, `state.json`의 `git.repo` 저장 |
| 배지 데이터 | `GET /api/git/summary?repo=` — `status()`(캐시, 저장소별 1회 실행 잠금, git 게이트)를 그대로 쓰고 파일 목록 없이 `{n, eol, conflicts, truncated, branch, state}`만 준다. 페이지는 메뉴를 열 때 15초보다 오래된 것만 다시 묻고, 동시에 3개까지만 보낸다(같은 저장소는 하나로 합친다). 선택한 저장소는 `/status` 응답으로도 갱신된다 |

### 여러 저장소를 함께 보기 (Local Changes)

매니저 요청: "local changes를 전부 다 보고 싶을 때가 있다." 보기만 여러 저장소로 넓힌다. 쓰기(Pull·Fetch·Checkout)와 AgentO 요청은 지금처럼 한 저장소 단위다.

| 항목 | 내용 |
|---|---|
| 고르기 | 메뉴의 저장소마다 체크박스, 맨 위에 **All repositories**. 이름 클릭(또는 Enter)은 그 저장소 하나, 체크박스 클릭(또는 강조 행에서 Space)은 표시만 하고 메뉴를 열어 둔다. 하단 **Show n**(Ctrl+Enter)이 적용, **clear**가 모두 해제. All 행은 일부만 체크되면 중간 상태로 보인다 |
| 저장 | `state.json`의 `git.repoAll`(전체) 또는 `git.repoMulti`(경로 목록). `git.repo`(단일 선택)는 그대로 두어 예전 저장값과 호환된다. 둘 다 비면 예전처럼 한 저장소다. All은 나중에 찾은 저장소도 포함한다. 폴더를 바꾸면 비운다. 목록에서 사라진 저장소는 빠진다 |
| Local Changes | 저장소별 그룹: 이름, `⎇ 브랜치 ↑↓`, 진행 상태(MERGING 등), 파일 수. 그룹은 접고 펼 수 있다. 변경이 없는 저장소는 숨기고, 상태 조회에 실패한 저장소는 오류와 함께 보인다. 요약 줄은 `n files in m of k repositories · loading x…` 형태다. 체크·폴더 트리·줄바꿈만 다른 파일 숨김은 한 저장소일 때와 같다 |
| 파일 | 클릭하면 오른쪽 diff, 더블클릭·Enter는 diff 창이다. 둘 다 그 파일의 저장소 기준이다. diff 창의 ↑↓는 같은 저장소 파일만 돈다(OS diff 창은 저장소 하나를 받는다) |
| 메뉴 | Commit… / Rollback… / Resolve Conflict…(AgentO)는 한 저장소의 파일일 때만 켜지고, 그 저장소로 지시문을 만든다. Show Diff, Open File, Show History, Copy Path(여러 저장소면 `저장소명/경로`), **Show Only <저장소>**, Refresh가 있다. Changelist 항목은 없다(Changelist는 한 저장소 기준) |
| 막는 것 | 머리의 브랜치·Pull·Fetch 버튼은 꺼지고 툴팁으로 안내한다. AgentO ▾ 메뉴는 Open AgentO만 켜진다. Ctrl+K는 체크한 파일이 한 저장소일 때만, Push는 저장소를 고르라고 안내한다. Log·History·Stash 탭은 "한 저장소만 보여 준다"는 안내와 선택한 저장소 버튼을 보여 준다(누르면 그 저장소 하나로). Console은 그대로다 |
| 조회 | 저장소마다 `/api/git/status`(기존 엔드포인트, 서버 캐시·잠금·git 게이트 그대로). 페이지 큐가 동시에 3개까지 보내고 도착하는 대로 그린다(60 ms 묶음). 결과는 페이지에 남겨 탭 전환 때 바로 그린다. 갱신은 열려 있는 동안 20초마다, 창 포커스(5초 간격 제한), ⟳ 버튼 때다 |
| 단일로 돌아가기 | 메뉴에서 이름 클릭, Show Only, Log 안내의 저장소 버튼, History·Show Log·blame 커밋 열기 등 한 저장소 화면으로 가는 동작. 대화상자에 저장소만 필요한 경우(브랜치 메뉴의 New Branch·Push, 실패 대화상자의 Console)는 여러 저장소 보기를 유지한다 |

<a id="sec-14-3"></a>

## 14.3 AgentO 딥링크 요청 스펙(v1, 초안 — AgentO 구현과 맞춰 확정)

ReadO는 구조화된 값만 보낸다. 지시문 본문은 AgentO가 만든다. 셸 명령, 토큰, 임의 코드는 넣지 않으며, force 관련 파라미터는 아예 없다.

```
agento://dispatch?v=1&source=reado&kind=<commit|push>&repo=<저장소 루트 절대경로>&branch=<현재 브랜치>&ahead=<n>&dirty=<변경 파일 수>[&msg=<커밋 메시지 초안>][&ref=<요청 id>]
```

| 파라미터 | 필수 | 값 |
|---|---|---|
| `v` | ✓ | `1`(스펙 버전). 모르는 버전은 거부한다 |
| `source` | ✓ | `reado` |
| `kind` | ✓ | `commit` 또는 `push`(화이트리스트). 그 밖의 값은 거부한다 |
| `repo` | ✓ | 저장소 루트 절대경로(Windows 표기 `C:\…`)를 퍼센트 인코딩한 값이다 |
| `branch` | ✓ | 현재 체크아웃 브랜치(detached면 요청하지 않음) |
| `ahead` | ✓ | upstream보다 앞선 커밋 수(upstream이 없으면 0) |
| `dirty` | ✓ | 변경 파일 수(untracked 포함) |
| `msg` | | 커밋 메시지 초안. 제어문자를 제거하고 200자로 자른다. URL이 2000자를 넘으면 요청 파일로 옮기고 URL에서는 뺀다 |
| `ref` | | 요청 파일 id(`YYYYMMDD-HHMMSS-<8 hex>`). commit은 항상 붙고, push는 msg를 옮길 때만 붙는다 |

- **인코딩**: 모든 값을 UTF-8로 퍼센트 인코딩한다(`encodeURIComponent`와 같으며 예약문자도 인코딩). URL 전체 길이는 2000자 이하이고, 넘으면 `too_long` 오류다.
- **요청 파일** `%APPDATA%\ReadO\requests\<ref>.json`(UTF-8):
  - 키: `{v, id, source, kind, repo, branch, upstream, ahead, behind, dirty, msg, created, files:[{path, kind}]}`
  - `files`는 저장소 기준 상대경로이고 최대 2000개다. Local Changes에서 체크한 파일이 있으면 그 파일만 들어간다.
  - 24시간이 지난 파일은 다음 요청 때 지운다.
- **실행**:
  1. 서버가 `HKCR\agento`에 `URL Protocol` 값과 `shell\open\command`가 있는지 확인한다.
  2. 있으면 `os.startfile(url)`로 요청을 보낸다. 토스트: "AgentO에 commit 요청을 보냈습니다".
- **폴백**: 핸들러가 없거나(`fallback: "no_handler"`) 실행에 실패하면(`launch_failed`) 기존 지시문(§4)을 클립보드에 복사한다. 토스트: "AgentO가 아직 agento:// 요청을 지원하지 않습니다. 지시문을 복사했습니다".
- **API**: `POST /api/git/agento-request {repo, kind, msg?, files?}` → `{sent, fallback?, url, ref, branch, ahead, dirty, files}`. 값(branch, ahead, dirty, files)은 서버가 git status로 다시 구하고, 페이지가 보낸 값은 쓰지 않는다. 비활성 조건은 서버에서도 확인한다(`nothing_to_commit`, `nothing_to_push`, `detached`).

예시:

```
agento://dispatch?v=1&source=reado&kind=commit&repo=C%3A%5CProjects%5Cmy-repo&branch=feature%2Fmy-page&ahead=0&dirty=3&msg=fix%3A%20claim%20model&ref=20261016-101500-1a2b3c4d
agento://dispatch?v=1&source=reado&kind=push&repo=C%3A%5CProjects%5Cmy-repo&branch=main&ahead=2&dirty=0
```

**AgentO 구현자 요구사항(보안)**

| # | 요구 |
|---|---|
| 1 | `v`·`source`·`kind`는 화이트리스트로 검사하고, 모르는 파라미터는 무시한다. 퍼센트 디코딩이 실패하거나 값에 제어문자가 있으면 거부한다 |
| 2 | **`repo`가 AgentO에 등록된 프로젝트 폴더(또는 그 하위)일 때만** 처리하고, 그 프로젝트의 head coach에게 "kind 요청"으로 전달한다. 등록되지 않은 경로는 사용자에게 알리고 버린다 |
| 3 | `ref`는 `^\d{8}-\d{6}-[0-9a-f]{8}$` 형식만 허용한다. `%APPDATA%\ReadO\requests\` 밖의 파일은 읽지 않는다. 파일의 `repo`·`kind`가 URL과 다르면 거부한다 |
| 4 | `msg`·`files`는 지시문의 데이터로만 쓰고, 명령으로 해석하거나 셸에 넘기지 않는다. push는 force 없이 진행하고 ahead·behind를 먼저 확인하라고 지시한다 |
| 5 | 같은 요청이 여러 번 오면(사용자 연타) 짧은 시간 안의 중복은 하나로 합친다 |

## 14.4 검증

| 테스트 | 항목 |
|---|---|
| `test_git.py` | 로컬 bare 원격과 클론 2개로 pullinfo, 성공(커밋 수·파일 수), 이미 최신, 비FF 거부(HEAD 불변), 로컬 변경 충돌 시 중단(작업 트리 불변), 저장 안 된 편집 확인, upstream 없음, CSRF 거부, `run()`의 fetch·merge 거부를 확인한다. 딥링크는 URL 형식, 인코딩, 200자 msg, 2000자 제한, ref 파일 내용, 핸들러 미등록 폴백, startfile 실패 폴백, kind 화이트리스트, nothing_to_commit·push를 확인한다(startfile 목킹). 2026-10-21: checkout(로컬 브랜치, 원격 전용 → 추적 브랜치 생성, 이미 추적하는 로컬로 이동, 추적 안 하는 같은 이름 거부, 로컬 변경 거부와 git 메시지 전달·작업 트리 불변, 저장 안 된 편집 확인, 현재 브랜치, 잘못된 ref·토큰 없음·폴더 밖 거부, `run()`의 switch·checkout 거부, 쓰기 러너의 checkout -f·reset·stash·clean 거부, 인덱스 갱신 호출)과 fetch --prune(↓ 표시, 지운 원격 브랜치 정리, HEAD 불변, 토큰 없음 거부), 인증 오류 문구 분류 |
| `ui_git_smoke.py` | 툴바 그룹 렌더, 브랜치 이름·↑↓, 버튼 비활성 조건, 브레드크럼 저장소 칩, pull 확인창과 실행, commit 요청 대화상자, 설정 아이콘 위치, 팔레트 모드 탭·`%` 검색, Find in Files 버튼 제거를 확인한다. 2026-10-21: Pull 거부 대화상자(이유·git 메시지·Stash·Console), Git 도구창 Fetch·Pull·브랜치 버튼, 브랜치 팝업(현재 브랜치·Local/Remote·추적 표시·검색), 원격 전용 브랜치 checkout 뒤 칩·상태바·트리·열린 파일 갱신, 로컬 브랜치 checkout 뒤 삭제된 파일 탭 표시, 저장 안 된 편집 경고(취소·저장 뒤 git 거부) |
