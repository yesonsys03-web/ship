# 선적전송 / 선적관리 프로토타입

Python 백엔드와 Tauri UI로 만든 초기 골격입니다. 지금 단계에서는 실제 파일 전체를 복사하지 않고, 드래그한 폴더의 목록 manifest를 사내 공유 DB 파일에 저장하고 선적관리 앱이 같은 DB를 읽는 흐름을 먼저 잡았습니다.

## 구조

```text
python/ship_common   공용 폴더 스캔, manifest, 공유 SQLite DB
python/ship_sender   선적전송 로컬 백엔드
python/ship_manager  선적관리 수신 백엔드
apps/sender          Tauri/React 선적전송 화면
apps/manager         Tauri/React 선적관리 화면
contracts            JSON 계약과 HTTP API 메모
tests                Python 동작 테스트와 샘플 폴더
```

## Python 백엔드 실행

터미널 1: 선적관리 PC에서 수신 서버 실행

```bash
cd /Volumes/data/python_bak/ship
PYTHONPATH=python python3 -m ship_manager.server
```

터미널 2: 선적전송 Mac에서 송신 서버 실행

```bash
cd /Volumes/data/python_bak/ship
PYTHONPATH=python python3 -m ship_sender.server
```

전송 내용은 아래 후보 중 기존 `shipments.sqlite3` 파일이 있는 경로를 우선 사용하고, 없으면 현재 PC에 만들 수 있는 첫 번째 경로에 저장됩니다.

```text
/USA_DB/test_jn/ship_db/shipments.sqlite3
/System/Volumes/Data/mnt/USA_DB/test_jn/ship_db/shipments.sqlite3
```

개발/테스트용으로 다른 DB 폴더를 쓰려면 `SHIP_DB_DIR`을 지정하세요.

브라우저에서 직접 개발 화면을 띄울 때는 허용 Origin을 환경변수로 조정할 수 있습니다.

```bash
SHIP_SENDER_ALLOWED_ORIGINS=http://127.0.0.1:1420 PYTHONPATH=python python3 -m ship_sender.server
SHIP_MANAGER_ALLOWED_ORIGINS=http://127.0.0.1:1430 PYTHONPATH=python python3 -m ship_manager.server
```

## Tauri 앱 실행

Rust/Cargo와 Node 의존성이 필요합니다.

```bash
cd /Volumes/data/python_bak/ship/apps/sender
npm install
npm run tauri dev
```

```bash
cd /Volumes/data/python_bak/ship/apps/manager
npm install
npm run tauri dev
```

개발 모드에서는 위의 Python 백엔드를 먼저 실행한 뒤 Tauri 앱을 실행하세요. `scripts/build_apps_py312.sh`로 만든 릴리스 `.app`은 PyInstaller onedir Python sidecar bundle을 `Contents/Resources`에 포함하며, 앱 실행 시 `Contents/MacOS`의 sidecar wrapper가 백엔드를 같이 시작합니다.

## macOS 12 호환 앱 빌드

릴리스 스크립트에는 의도적인 thin/native 모드와 x86_64+arm64 universal 모드가 있습니다. 기본값은 `SHIP_MACOS_BUILD_MODE=native`이며, 현재 빌드 호스트의 Rust target에 맞는 단일 아키텍처 `.app`을 만듭니다. native 모드는 python.org의 `python-3.9.13-macosx10.9.pkg` 런타임을 `build/python-runtime-cache`에 내려받아 사용합니다. 이 런타임은 macOS 12에서 로드 가능한 Python dylib를 포함하므로, 최신 macOS의 Homebrew Python이 만드는 `_mkfifoat` 오류를 피합니다.

```bash
cd /Volumes/data/python_bak/ship
./scripts/build_apps_py312.sh
```

Universal 앱을 만들려면 아래처럼 명시적으로 요청합니다. 이 모드는 Tauri를 `tauri build --bundles app --target universal-apple-darwin`로 실행하고, PyInstaller sidecar를 `--target-arch universal2`로 빌드하며, sidecar wrapper도 `cc -arch x86_64 -arch arm64`로 만듭니다. 기본 universal Python 런타임은 official python.org `python-3.11.9-macos11.pkg` universal2 패키지입니다.

```bash
cd /Volumes/data/python_bak/ship
SHIP_MACOS_BUILD_MODE=universal ./scripts/build_apps_py312.sh
```

Universal 모드는 아래 전제 조건이 없으면 x86_64로 조용히 fallback하지 않고 중단합니다.

```text
- cargo와 rustc가 설치되어 있어야 합니다.
- x86_64-apple-darwin 및 aarch64-apple-darwin Rust target이 있어야 합니다.
- lipo가 있어야 합니다.
- 선택된 Python dylib가 x86_64와 arm64를 모두 포함하는 universal2이어야 합니다.
- PyInstaller 산출물, Tauri app main executable, sidecar wrapper, bundled sidecar executable이 모두 lipo -archs 기준 x86_64와 arm64를 포함해야 합니다.
```

다른 Python을 직접 지정할 수도 있지만, native 모드에서는 그 Python dylib가 macOS 12 이하를 지원해야 하고, universal 모드에서는 macOS 12 호환 universal2 Python이어야 합니다.

```bash
PYTHON_RUNTIME_VERSION=3.12 PYTHON_BIN=/path/to/macos12-compatible/python3.12 ./scripts/build_apps_py312.sh
SHIP_MACOS_BUILD_MODE=universal PYTHON_BIN=/path/to/universal2/python3.11 ./scripts/build_apps_py312.sh
```

빌드 스크립트는 선택된 Python dylib가 `MACOSX_DEPLOYMENT_TARGET`보다 높은 macOS를 요구하거나 macOS 12에 없는 `_mkfifoat`를 참조하면 즉시 중단합니다. Universal 모드에서는 Python dylib와 모든 필수 실행 파일을 `lipo -archs`로 확인하고, `x86_64`와 `arm64`가 모두 없으면 실패합니다. 기본 deployment target은 `12.0`입니다.

macOS 12부터 이후 macOS 릴리스까지 배포하려면 universal 모드와 deployment target 12.0을 같이 사용하세요. 이 설정은 Intel Mac과 Apple Silicon Mac용 실행 파일을 모두 포함하고, Mach-O minimum macOS 버전을 12.0 이하로 검증합니다.

```bash
cd /Volumes/data/python_bak/ship
MACOSX_DEPLOYMENT_TARGET=12.0 SHIP_MACOS_BUILD_MODE=universal ./scripts/build_apps_py312.sh
```

GitHub Actions에서도 같은 설정으로 `macos-universal-apps` artifact를 만듭니다.

이 릴리스 스크립트는 최종 `.app`의 실제 main executable과 sidecar executable 아키텍처를 출력합니다. sender는 `release/선적전송.app/Contents/MacOS/ship_sender`, `release/선적전송.app/Contents/MacOS/ship-sender-backend`, `release/선적전송.app/Contents/Resources/ship-sender-backend-bundle/ship-sender-backend`를 검사합니다. manager도 같은 방식으로 `ship_manager`, `ship-manager-backend` wrapper, bundled executable을 검사합니다. x86_64-only로 나오면 그 패키지는 Apple Silicon-native나 universal이 아니며, macOS 12의 Silicon Mac에서는 Rosetta 의존 패키지로만 취급해야 합니다.

```text
선적전송.app main executable architectures: x86_64
Warning: 선적전송.app is x86_64-only. Copying it to Apple Silicon macOS 12 will not make it native or universal; it will rely on Rosetta if that is available.
```

빌드가 끝나면 앱은 아래 위치에 모입니다.

```text
/Volumes/data/python_bak/ship/release/선적전송.app
/Volumes/data/python_bak/ship/release/선적관리.app
```

이 빌드는 Rust/Cargo가 필요합니다. `cargo --version`이 안 나오면 Rust를 설치한 뒤 다시 실행하세요.

```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
```


## Windows 앱 빌드

Windows 설치 프로그램은 Windows host 또는 GitHub Actions `windows-latest` runner에서 빌드합니다. Tauri 문서 기준 MSI는 Windows에서만 만들 수 있고, 이 프로젝트의 Python sidecar도 Windows용 PyInstaller 실행 파일을 Windows에서 만들어야 합니다. 기본 Windows 산출물은 NSIS `setup.exe`입니다.

```powershell
cd C:\path\to\ship
.\scripts\build_apps_windows.ps1 -Python python -Target x86_64-pc-windows-msvc
```

빌드가 끝나면 Windows 설치 파일은 `release-windows/`에 모입니다. GitHub Actions `Desktop Builds` workflow를 수동 실행하거나 `v*` 태그를 push하면 macOS universal zip과 Windows x64 installer artifact를 생성합니다.

## 현재 구현된 흐름

1. 선적전송 창에 Finder 폴더를 드래그앤드롭합니다.
2. 송신 Python 백엔드가 폴더 내부 파일/폴더 목록을 만듭니다.
3. 화면 왼쪽에서 선적 날짜를 연/월/일 콤보박스로 선택하고 메모를 입력합니다.
4. 오른쪽 파일 목록에서 폴더와 파일을 구분해 확인합니다.
5. 전송 버튼을 누르면 manifest가 사내 공유 SQLite DB에 저장됩니다.
6. 선적관리 화면은 같은 DB를 읽어서 왼쪽에 연도, 월, 일자와 마지막 폴더명을 표시합니다.
7. 왼쪽 항목을 누르면 오른쪽에 해당 폴더 내용이 표시됩니다.
8. 앱 내부 알림과 macOS 알림 호출부가 들어 있습니다.

## 테스트

```bash
cd /Volumes/data/python_bak/ship
PYTHONPATH=python python3 -m pytest
```

## 다음에 다듬을 부분

- 실제 파일 복사까지 포함할지, 목록만 보낼지 결정
- 선적관리 PC IP 저장 UI 추가
- 수신 시 즉시 알림을 위한 polling 대신 WebSocket 또는 Server-Sent Events 적용
- 전송 실패 재시도와 중복 선적 처리 정책 결정
- 기존 선적 도구의 `/Volumes/Shipping-1/batch/{show}` 경로 관례와 `Yeson_ship_work.app`, `shipping.icns` 패키징 자산 반영 여부 결정

## 기존 자산 참고

주변 폴더에 기존 선적/스케줄러 자산이 있습니다. 이번 골격은 사용자가 Finder에서 드래그한 임의 폴더를 전송하는 구조라 기존 경로 규칙을 강제하지 않았지만, 다음 단계에서 작품별 자동 경로 선택이 필요하면 아래 자산을 참고하세요.

- `/Volumes/data/python_bak/python/mkdir/new_vs/mix3.6_010726.py`: 기존 선적 파일 정리 로직과 `/Volumes/Shipping-1/batch/{show}` 경로 사용
- `/Volumes/data/python_bak/python/mkdir/new_vs/Yeson_ship_work.spec`: 기존 선적 PyInstaller 앱 패키징
- `/Volumes/data/python_bak/python/data2/spec_py312/YesonScheduler_v9_8.spec`: 기존 macOS 앱 패키징과 `shipping.icns` 아이콘 관례
