# ReadO 릴리스 절차 — 빌드·테스트·dist 교체·버전

**대상**: 새 빌드를 `dist\reado.exe`로 내보내기까지의 절차  
**원칙**: 테스트를 통과한 빌드만 `dist`에 넣는다. 실행 중인 ReadO는 정상 닫기로 자동 종료하고, 저장 안 된 편집이 있으면 교체를 멈춘다. 강제 종료나 taskkill로 이름·경로 일괄 종료는 하지 않는다. 교체한 뒤에는 새 `dist\reado.exe`를 다시 띄운다(`--restart`, 매니저 승인 상시 규칙).

<a id="toc"></a>

## 목차

- [**1. 전체 흐름**](#cat-1)
- [**2. 빌드와 테스트 — scripts/build_test.py**](#cat-2)
- [**3. dist 교체 — scripts/swap_dist.py**](#cat-3)
- [**4. 버전 끊기 — CHANGELOG**](#cat-4)
- [**5. 폴더**](#cat-5)

---

<a id="cat-1"></a>

# 1 전체 흐름 

> 빌드는 항상 `dist-next`에 한다. `dist`는 사용 중일 수 있으므로 교체 스크립트만 건드린다.

- **1 빌드·테스트** — `python scripts/build_test.py` — dist-next에 빌드하고 자동 테스트 4종을 차례로 실행한다
- **2 수동 확인** — `README · Manual checks` — 자동 테스트로 못 하는 것(드래그 앤 드롭, 연결 프로그램, 타이틀바 등)을 dist-next exe로 확인
- **3 dist 교체** — `python scripts/swap_dist.py` — 먼저 dry run으로 할 일을 보고, --apply --expect &lt;해시&gt; --restart로 실행(닫기 → 교체 → 재기동)
- **4 버전 끊기** — `CHANGELOG.md` — [Unreleased]를 새 버전 항목으로 옮기고 README 버전을 맞춘다. 태그는 매니저 결정 후

| 단계 | 누가 실행하나 | 되돌리기 |
|---|---|---|
| 1 빌드·테스트 | 작업 세션 | 필요 없음(`dist-next`만 바뀜) |
| 2 수동 확인 | 매니저 또는 작업 세션 | 필요 없음 |
| 3 dist 교체 | 매니저 지시가 있을 때만 | `dist-prev\reado.exe`를 `dist`로 복사 |
| 4 버전 끊기 | 작업 세션(로컬 커밋), 태그·push는 매니저 지시 후 | 커밋 되돌리기 |

---

<a id="cat-2"></a>

# 2 빌드와 테스트 — scripts/build_test.py 

> 한 번 실행으로 `build.bat dist-next`와 자동 테스트 전부를 돌리고, 마지막에 요약과 다음에 실행할 교체 명령을 출력한다.

### 2.1 실행

```bash
python scripts/build_test.py                # 빌드 + 테스트 전부
python scripts/build_test.py --skip-build   # 이미 있는 dist-next로 테스트만
python scripts/build_test.py --gitfx DIR    # ui_git_smoke용 git 픽스처 폴더(없으면 만든다)
```

### 2.2 실행 순서

| 순서 | 단계 | 통과 기준 |
|---|---|---|
| 1 | 사전 확인: HEAD, 커밋 안 된 변경(빌드에 함께 들어간다고 알림), `dist-next`에서 실행 중인 ReadO가 있으면 중단 | — |
| 2 | `build.bat dist-next` | `dist-next\reado.exe` 생성 |
| 3 | `tests/git_fixture.py` — 픽스처 폴더가 없을 때만 | 종료 코드 0 |
| 4 | `tests/verify_editor.py` | `N / N passed` |
| 5 | `tests/test_git.py` | `all passed` |
| 6 | `tests/ui_git_smoke.py <픽스처>` | `all passed` |
| 7 | `tests/exe_startup.py dist-next\reado.exe` | `all passed` |

- 테스트는 **하나씩** 돌린다. 동시에 돌리면 verify_editor의 검색 단계가 검색 동시 실행 한도(2)에 걸려 `429`를 받는다.
- 실패한 테스트는 한 번 더 돌린다. 다시 통과하면 요약에 `passed on retry`로 남긴다. 불안정한 단계를 숨기지 않기 위해서다.
- 로그는 `%TEMP%\reado-release\<시각>\<단계>.log`에 남는다. 종료 코드는 전부 통과했을 때만 0이다.

### 2.3 이 스크립트에 없는 것

exe 화면 스모크(실제 창·마우스·타이틀바를 조작하는 35개 항목)는 저장소에 없는 별도 도구다. 실제 마우스를 쓰므로 머신 사용 중에는 결과가 흔들린다. 릴리스 전에는 이 스모크와 README의 **Manual checks**를 `dist-next\reado.exe`로 한 번 확인한다.

---

<a id="cat-3"></a>

# 3 dist 교체 — scripts/swap_dist.py 

> 인자 없이 실행하면 **dry run**이다. 할 일만 출력하고 아무것도 바꾸지 않는다. `--apply`를 줘야 실제로 교체한다.

### 3.1 실행

```bash
python scripts/swap_dist.py                                  # dry run
python scripts/swap_dist.py --apply --expect <dist-next 해시>  # 교체
python scripts/swap_dist.py --apply --expect <dist-next 해시> --restart  # 교체 후 재기동(기본 사용법)
```

`--expect`에는 build_test.py 요약에 나온 해시를 그대로 넣는다. 테스트한 그 빌드만 들어가게 하기 위해서다.

`--restart`는 매니저가 평소 띄우는 방식과 같게 새 `dist\reado.exe`를 띄운다. 작업 폴더는 `dist`, APPDATA는 스크립트를 실행한 사용자의 것을 그대로 쓰므로 마지막 폴더도 복원되며, 격리 실행이 아니다. 그다음 `instance.json`에 새 프로세스가 `shown: true`로 기록될 때까지 최대 60초 기다린다. 따라서 격리 APPDATA를 설정한 셸에서 실행하면 재기동도 그 APPDATA로 뜬다.

### 3.2 단계(--apply)

- **1 확인** — dist-next 해시 계산, --expect와 비교. dist와 같으면 이미 교체된 것이므로 끝
- **2 정상 닫기** — dist·dist-prev·dist-next에서 실행 중인 ReadO 창에 WM_CLOSE. 대상은 exe 폴더로 찾은 프로세스와, 그 폴더에서 실행 중일 때의 instance.json PID. 강제 종료는 하지 않는다
- **3 복사** — dist → dist-prev(덮어씀), dist-next → dist. 복사할 때마다 SHA256 확인
- **4 정리** — dist-next, build, build-dist-next 삭제. dist와 dist-prev만 남긴다
- **5 재기동(--restart)** — 새 dist\reado.exe를 띄우고 instance.json에 창이 떴다고 기록될 때까지 기다린다. 2에서 멈췄으면 하지 않는다

### 3.3 멈추는 경우

| 상황 | 스크립트가 하는 일 | 종료 코드 | 결과 |
|---|---|---|---|
| `dist-next\reado.exe`가 없다 | 바로 멈춘다 | 1 | 바뀐 것 없음 |
| `--expect`와 해시가 다르다 | 바로 멈춘다 | 1 | 바뀐 것 없음 |
| `dist`와 해시가 같다 | "nothing to do". `--restart`가 있으면 dist의 ReadO가 꺼져 있을 때만 띄운다 | 0 | 바뀐 것 없음(같은 빌드를 두 번 교체하지 않는다) |
| 실행 중인 ReadO에 **저장 안 된 편집**이 있다 | ReadO가 띄운 "Quit without saving?" 상자에 **Cancel**로 답하고 멈춘다 | 1 | 창과 편집은 그대로, 파일도 그대로 |
| 30초가 지나도 ReadO가 끝나지 않는다 | PID를 알려 주고 멈춘다 | 1 | 바뀐 것 없음, 사용자가 직접 닫는다 |
| 복사 중 오류 | 현재 `dist`가 옛 빌드인지, 새 빌드인지, 손상됐는지 알려 준다 | 2 | `dist-next`는 남긴다. 손상이면 `dist-prev`를 `dist`로 복사. `--restart`면 dist가 손상되지 않았을 때만 다시 띄운다 |
| `--restart`로 띄운 창이 60초 안에 뜨지 않는다 | 알리고 끝낸다 | 3 | 교체는 끝난 상태. `%APPDATA%\ReadO\startup.log`를 확인한다 |

### 3.4 검증

교체 스크립트 자체는 실제 `dist`를 쓰지 않고 다음처럼 확인했다.

| 무엇을 | 어떻게 | 결과 |
|---|---|---|
| 닫기 | scratch 폴더에 exe 사본을 따로 띄우고 편집 중인 상태와 편집 없는 상태로 `close_normally` 실행 | 편집 중이면 Cancel하고 멈추며 편집이 남는다. 편집이 없으면 모든 프로세스가 정상 종료된다(7/7) |
| 복사·정리 | 가짜 dist·dist-prev·dist-next 폴더로 `--apply` 실행 | dry run은 무변경, 해시가 틀리면 무변경, 교체 후 dist·dist-prev만 남음, 같은 빌드 재실행은 무변경(4/4) |
| 닫기 → 교체 → 재기동(`--restart`) | 가짜 dist에서 옛 exe를 격리 APPDATA로 띄운 뒤 `--apply --expect --restart` 실행. 이어서 같은 빌드로 실행 중/꺼짐 상태에서 각각 실행하고, `--restart` dry run도 실행 | instance.json PID로 찾은 옛 프로세스가 정상 종료되고, 교체 후 새 창이 뜬다. 실행 중이면 다시 띄우지 않고, 꺼져 있으면 띄운다. dry run은 아무것도 띄우지 않는다(12/12) |
| 실제 적용 | 2026-11-03 #T42: 매니저가 ReadO를 닫은 뒤 `dist`를 `8B80AC71…`로 교체하고 다시 띄움 | 창이 뜸 |

---

<a id="cat-4"></a>

# 4 버전 끊기 — CHANGELOG 

> 버전 번호는 [Semantic Versioning](https://semver.org/)을 따른다. 1.0 전에는 기능이 추가되면 MINOR, 버그 수정만 있으면 PATCH를 올린다.

| 할 일 | 위치 |
|---|---|
| `## Unreleased`의 내용을 `## X.Y.Z — 날짜` 항목으로 옮기고, `## Unreleased`는 빈 채로 남긴다 | `CHANGELOG.md` |
| 목차와 앵커(`<a id="vXYZ">`)를 추가한다 | `CHANGELOG.md` |
| 버전 표시를 맞춘다 | `README.md` 첫머리 **Version**, 앱의 Help → About(`server.py`의 `VERSION`) |
| 태그 `vX.Y.Z`와 push | 매니저 결정 후에만 |

---

<a id="cat-5"></a>

# 5 폴더 

| 폴더 | 내용 | 누가 쓰나 |
|---|---|---|
| `dist\` | 사용 중인 빌드. 매니저가 실행하는 exe | `swap_dist.py --apply`만 |
| `dist-prev\` | 바로 전 빌드(되돌리기용) | `swap_dist.py --apply`만 |
| `dist-next\` | 테스트 중인 새 빌드 | `build.bat dist-next`, `build_test.py` |
| `build-dist-next\`, `build\` | PyInstaller 작업 폴더 | 빌드할 때 생기고 교체할 때 지운다 |
