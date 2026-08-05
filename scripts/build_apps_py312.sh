#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
RELEASE_DIR="$ROOT_DIR/release"
MACOS_DEPLOYMENT_TARGET="${MACOSX_DEPLOYMENT_TARGET:-12.0}"
export MACOSX_DEPLOYMENT_TARGET="$MACOS_DEPLOYMENT_TARGET"
SHIP_MACOS_BUILD_MODE="${SHIP_MACOS_BUILD_MODE:-native}"
case "$SHIP_MACOS_BUILD_MODE" in
  native|universal) ;;
  *) printf '%s\n' "Unsupported SHIP_MACOS_BUILD_MODE=$SHIP_MACOS_BUILD_MODE. Use native or universal." >&2; exit 1 ;;
esac
if [ -z "${PYTHON_RUNTIME_VERSION:-}" ]; then
  if [ "$SHIP_MACOS_BUILD_MODE" = "universal" ]; then
    PYTHON_RUNTIME_VERSION="3.11"
  else
    PYTHON_RUNTIME_VERSION="3.9"
  fi
fi
PYTHON_RUNTIME_COMPACT="${PYTHON_RUNTIME_VERSION//./}"
PYTHON_BIN="${PYTHON_BIN:-${PYTHON311:-${PYTHON312:-}}}"
VENV_DIR="$ROOT_DIR/.venv$PYTHON_RUNTIME_COMPACT"
BUILD_DIR="$ROOT_DIR/build/py$PYTHON_RUNTIME_COMPACT"
PYTHON_RUNTIME_CACHE_DIR="$ROOT_DIR/build/python-runtime-cache"
PYTHON39_RELEASE="3.9.13"
PYTHON39_PACKAGE_NAME="python-$PYTHON39_RELEASE-macosx10.9.pkg"
PYTHON39_PACKAGE_URL="https://www.python.org/ftp/python/$PYTHON39_RELEASE/$PYTHON39_PACKAGE_NAME"
PYTHON311_RELEASE="3.11.9"
PYTHON311_PACKAGE_NAME="python-$PYTHON311_RELEASE-macos11.pkg"
PYTHON311_PACKAGE_URL="https://www.python.org/ftp/python/$PYTHON311_RELEASE/$PYTHON311_PACKAGE_NAME"
VENDORED_FRAMEWORKS_DIR=""

fail() {
  printf '%s\n' "$1" >&2
  exit 1
}

run_without_python_dyld() {
  env -u DYLD_FRAMEWORK_PATH -u DYLD_LIBRARY_PATH "$@"
}

install_python_framework_payload() {
  local expanded_dir="$1"
  local framework_path="$2"
  local python_version="$3"
  local payload_dir=""

  while IFS= read -r -d '' candidate_dir; do
    if [ -d "$candidate_dir/Versions/$python_version" ]; then
      payload_dir="$candidate_dir"
      break
    fi
  done < <(find "$expanded_dir" -type d -name Payload -print0)

  if [ -z "$payload_dir" ]; then
    fail "Python framework payload for $python_version was not found under $expanded_dir. The python.org pkg layout changed; inspect the expanded pkg and update extraction."
  fi

  mkdir -p "$(dirname "$framework_path")"
  cp -R "$payload_dir" "$framework_path"
}

ensure_vendored_python39() {
  local package_path="$PYTHON_RUNTIME_CACHE_DIR/$PYTHON39_PACKAGE_NAME"
  local expanded_dir="$PYTHON_RUNTIME_CACHE_DIR/python-$PYTHON39_RELEASE-macosx10.9-expanded"
  local runtime_root="$PYTHON_RUNTIME_CACHE_DIR/python-$PYTHON39_RELEASE-macosx10.9-root"
  local framework_path="$runtime_root/Library/Frameworks/Python.framework"

  if [ ! -x "$framework_path/Versions/3.9/bin/python3.9" ]; then
    mkdir -p "$PYTHON_RUNTIME_CACHE_DIR"
    if [ ! -f "$package_path" ]; then
      printf 'Downloading macOS 12-compatible Python %s runtime...\n' "$PYTHON39_RELEASE"
      curl -fL "$PYTHON39_PACKAGE_URL" -o "$package_path"
    fi

    rm -rf "$expanded_dir" "$runtime_root"
    pkgutil --expand-full "$package_path" "$expanded_dir"
    install_python_framework_payload "$expanded_dir" "$framework_path" "3.9"
  fi

  VENDORED_FRAMEWORKS_DIR="$runtime_root/Library/Frameworks"
  export DYLD_FRAMEWORK_PATH="$VENDORED_FRAMEWORKS_DIR${DYLD_FRAMEWORK_PATH:+:$DYLD_FRAMEWORK_PATH}"
  export DYLD_LIBRARY_PATH="$framework_path/Versions/3.9/lib${DYLD_LIBRARY_PATH:+:$DYLD_LIBRARY_PATH}"
  PYTHON_BIN="$framework_path/Versions/3.9/bin/python3.9"
}

ensure_vendored_python311_universal2() {
  local package_path="$PYTHON_RUNTIME_CACHE_DIR/$PYTHON311_PACKAGE_NAME"
  local expanded_dir="$PYTHON_RUNTIME_CACHE_DIR/python-$PYTHON311_RELEASE-macos11-expanded"
  local runtime_root="$PYTHON_RUNTIME_CACHE_DIR/python-$PYTHON311_RELEASE-macos11-root"
  local framework_path="$runtime_root/Library/Frameworks/Python.framework"

  if [ ! -x "$framework_path/Versions/3.11/bin/python3.11" ]; then
    mkdir -p "$PYTHON_RUNTIME_CACHE_DIR"
    if [ ! -f "$package_path" ]; then
      printf 'Downloading macOS universal2 Python %s runtime...\n' "$PYTHON311_RELEASE"
      curl -fL "$PYTHON311_PACKAGE_URL" -o "$package_path"
    fi

    rm -rf "$expanded_dir" "$runtime_root"
    pkgutil --expand-full "$package_path" "$expanded_dir"
    install_python_framework_payload "$expanded_dir" "$framework_path" "3.11"
  fi

  VENDORED_FRAMEWORKS_DIR="$runtime_root/Library/Frameworks"
  export DYLD_FRAMEWORK_PATH="$VENDORED_FRAMEWORKS_DIR${DYLD_FRAMEWORK_PATH:+:$DYLD_FRAMEWORK_PATH}"
  export DYLD_LIBRARY_PATH="$framework_path/Versions/3.11/lib${DYLD_LIBRARY_PATH:+:$DYLD_LIBRARY_PATH}"
  PYTHON_BIN="$framework_path/Versions/3.11/bin/python3.11"
}

if [ -z "$PYTHON_BIN" ]; then
  case "$PYTHON_RUNTIME_VERSION" in
    3.9)
      if [ "$SHIP_MACOS_BUILD_MODE" = "universal" ]; then
        fail "Universal build requires a universal2 Python runtime. The default Python 3.9.13 macosx10.9 runtime is x86_64-only. Use PYTHON_RUNTIME_VERSION=3.11 for the official universal2 runtime, or set PYTHON_BIN=/path/to/universal2/python."
      fi
      ensure_vendored_python39
      ;;
    3.11) ensure_vendored_python311_universal2 ;;
    3.12) PYTHON_BIN="${PYTHON_BIN:-python3.12}" ;;
    *) fail "Unsupported PYTHON_RUNTIME_VERSION=$PYTHON_RUNTIME_VERSION. Use 3.9, 3.11, 3.12 with PYTHON_BIN, or provide PYTHON_BIN=/path/to/python." ;;
  esac
fi

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  fail "Python runtime not found: $PYTHON_BIN"
fi

PYTHON_BIN="$(command -v "$PYTHON_BIN")"

python_dylib_path() {
  local python_bin="$1"

  "$python_bin" - <<'PY'
from pathlib import Path
import sys
import sysconfig

candidates: list[Path] = []
instsoname = sysconfig.get_config_var("INSTSONAME") or sysconfig.get_config_var("LDLIBRARY")
framework_prefix = sysconfig.get_config_var("PYTHONFRAMEWORKPREFIX")
libdir = sysconfig.get_config_var("LIBDIR")
ldlibrary = sysconfig.get_config_var("LDLIBRARY")

if instsoname:
    install_name = Path(instsoname)
    if install_name.is_absolute():
        candidates.append(install_name)
    if framework_prefix:
        candidates.append(Path(framework_prefix) / install_name)
    for prefix in {Path(sys.base_prefix), Path(sys.prefix), Path(sys.exec_prefix)}:
        candidates.append(prefix / install_name)
        candidates.append(prefix / install_name.name)

if libdir and ldlibrary:
    candidates.append(Path(libdir) / ldlibrary)

for candidate in candidates:
    if candidate.exists():
        print(candidate)
        raise SystemExit(0)

raise SystemExit("could not locate Python dynamic library")
PY
}

macho_min_macos() {
  local binary_path="$1"

  "$PYTHON_BIN" - "$binary_path" <<'PY'
import subprocess
import sys
import os

env = os.environ.copy()
env.pop("DYLD_FRAMEWORK_PATH", None)
env.pop("DYLD_LIBRARY_PATH", None)
output = subprocess.check_output(["otool", "-l", sys.argv[1]], text=True, env=env)
mode = None
for line in output.splitlines():
    text = line.strip()
    if text == "cmd LC_BUILD_VERSION":
        mode = "build"
        continue
    if text == "cmd LC_VERSION_MIN_MACOSX":
        mode = "version_min"
        continue
    if mode == "build" and text.startswith("minos "):
        print(text.split()[1])
        raise SystemExit(0)
    if mode == "version_min" and text.startswith("version "):
        print(text.split()[1])
        raise SystemExit(0)

raise SystemExit("could not read Mach-O minimum macOS version")
PY
}

version_lte() {
  local left="$1"
  local right="$2"

  "$PYTHON_BIN" - "$left" "$right" <<'PY'
import sys

def parts(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in value.split("."))

left = parts(sys.argv[1])
right = parts(sys.argv[2])
width = max(len(left), len(right))
left = left + (0,) * (width - len(left))
right = right + (0,) * (width - len(right))
raise SystemExit(0 if left <= right else 1)
PY
}

binary_architectures() {
  local binary_path="$1"

  if ! command -v lipo >/dev/null 2>&1; then
    fail "lipo is required to verify Mach-O architectures. Install Xcode Command Line Tools with: xcode-select --install"
  fi
  if [ ! -e "$binary_path" ]; then
    fail "Expected executable is missing: $binary_path"
  fi
  run_without_python_dyld lipo -archs "$binary_path" 2>/dev/null || fail "Unable to read Mach-O architectures with lipo: $binary_path"
}

archs_include() {
  local architectures="$1"
  local required_arch="$2"

  case " $architectures " in
    *" $required_arch "*) return 0 ;;
    *) return 1 ;;
  esac
}

require_universal_macho() {
  local label="$1"
  local binary_path="$2"
  local architectures

  architectures="$(binary_architectures "$binary_path")"
  if ! archs_include "$architectures" "x86_64" || ! archs_include "$architectures" "arm64"; then
    fail "Universal build artifact is not universal: $label at $binary_path reports '$architectures'. Expected both x86_64 and arm64. Rebuild with SHIP_MACOS_BUILD_MODE=universal, a universal2 Python interpreter, PyInstaller --target-arch universal2, and Tauri --target universal-apple-darwin."
  fi
  printf '%s architectures: %s\n' "$label" "$architectures"
}

validate_python_runtime() {
  local label="$1"
  local python_bin="$2"
  local python_version
  local dylib_path
  local min_macos

  python_version="$($python_bin -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
  if [ "$python_version" != "$PYTHON_RUNTIME_VERSION" ]; then
    fail "$label must be Python $PYTHON_RUNTIME_VERSION, but found Python $python_version at $python_bin."
  fi

  dylib_path="$(python_dylib_path "$python_bin")"
  if [ "$SHIP_MACOS_BUILD_MODE" = "universal" ]; then
    require_universal_macho "$label Python dylib" "$dylib_path"
  fi
  min_macos="$(macho_min_macos "$dylib_path")"
  if ! version_lte "$min_macos" "$MACOS_DEPLOYMENT_TARGET"; then
    fail "$label uses a Python runtime built for macOS $min_macos: $dylib_path
macOS 12 release builds require a Python runtime with minimum macOS <= $MACOS_DEPLOYMENT_TARGET.
Use the default runtime for the selected build mode, or provide a compatible runtime with PYTHON_BIN=/path/to/python."
  fi

  if version_lte "$MACOS_DEPLOYMENT_TARGET" "12.999" && run_without_python_dyld nm -m "$dylib_path" 2>/dev/null | grep -q 'external _mkfifoat'; then
    fail "$label references _mkfifoat in $dylib_path, which is not available on macOS 12.
Use the default runtime for the selected build mode, or provide a Python build made for macOS 12 or older with PYTHON_BIN=/path/to/python."
  fi

  printf 'Using %s: %s (Python dylib min macOS %s)\n' "$label" "$python_bin" "$min_macos"
}

venv_matches_python() {
  local cfg_path="$VENV_DIR/pyvenv.cfg"

  [ -x "$VENV_DIR/bin/python" ] && [ -f "$cfg_path" ] || return 1
  "$PYTHON_BIN" - "$cfg_path" "$PYTHON_BIN" <<'PY'
from pathlib import Path
import sys

cfg_path = Path(sys.argv[1])
selected = Path(sys.argv[2]).resolve()
executable = None
for line in cfg_path.read_text().splitlines():
    if line.startswith("executable = "):
        executable = line.split(" = ", 1)[1]
        break

if executable is None:
    raise SystemExit(1)
raise SystemExit(0 if Path(executable).resolve() == selected else 1)
PY
}

validate_python_runtime "selected Python" "$PYTHON_BIN"

if [ -d "$VENV_DIR" ] && ! venv_matches_python; then
  printf 'Removing %s because it was created from a different Python runtime.\n' "$VENV_DIR" >&2
  rm -rf "$VENV_DIR"
fi

if [ ! -d "$VENV_DIR" ]; then
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

validate_python_runtime "build venv" "$VENV_DIR/bin/python"

if [ "$SHIP_MACOS_BUILD_MODE" = "universal" ]; then
  TARGET_TRIPLE="universal-apple-darwin"
  TAURI_BUILD_ARGS=(build --bundles app --target universal-apple-darwin)
  PYINSTALLER_ARCH_ARGS=(--target-arch universal2)
  WRAPPER_TARGET_TRIPLES=(x86_64-apple-darwin aarch64-apple-darwin universal-apple-darwin)
  WRAPPER_CC_ARCH_ARGS=(-arch x86_64 -arch arm64)
else
  if command -v rustc >/dev/null 2>&1; then
    TARGET_TRIPLE="$(run_without_python_dyld rustc --print host-tuple)"
  else
    case "$(uname -m)" in
      arm64) TARGET_TRIPLE="aarch64-apple-darwin" ;;
      x86_64) TARGET_TRIPLE="x86_64-apple-darwin" ;;
      *) printf 'Unsupported macOS architecture: %s\n' "$(uname -m)" >&2; exit 1 ;;
    esac
  fi
  TAURI_BUILD_ARGS=(build)
  case "$(uname -m)" in
    arm64) PYINSTALLER_ARCH_ARGS=(--target-arch arm64) ;;
    x86_64) PYINSTALLER_ARCH_ARGS=(--target-arch x86_64) ;;
    *) printf 'Unsupported macOS architecture: %s\n' "$(uname -m)" >&2; exit 1 ;;
  esac
  WRAPPER_TARGET_TRIPLES=("$TARGET_TRIPLE")
  WRAPPER_CC_ARCH_ARGS=()
fi

mkdir -p "$BUILD_DIR" "$RELEASE_DIR" \
  "$ROOT_DIR/apps/sender/src-tauri/binaries" \
  "$ROOT_DIR/apps/manager/src-tauri/binaries"

create_sidecar_wrapper() {
  local wrapper_path="$1"
  local bundle_dir="$2"
  local executable_name="$3"
  local source_path="$BUILD_DIR/sidecar-wrapper-$executable_name.c"

  cat > "$source_path" <<'EOF'
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#ifndef BUNDLE_DIR
#error BUNDLE_DIR is required
#endif

#ifndef EXECUTABLE_NAME
#error EXECUTABLE_NAME is required
#endif

int main(int argc, char **argv) {
  char self_path[PATH_MAX];
  const char *argv0 = argc > 0 ? argv[0] : NULL;

  if (argv0 == NULL || realpath(argv0, self_path) == NULL) {
    fprintf(stderr, "failed to resolve sidecar wrapper path\n");
    return 127;
  }

  char *last_slash = strrchr(self_path, '/');
  if (last_slash == NULL) {
    fprintf(stderr, "failed to locate sidecar wrapper directory\n");
    return 127;
  }
  *last_slash = '\0';

  char target_path[PATH_MAX];
  int written = snprintf(
      target_path,
      sizeof(target_path),
      "%s/%s/%s",
      self_path,
      BUNDLE_DIR,
      EXECUTABLE_NAME);
  if (written < 0 || (size_t)written >= sizeof(target_path)) {
    fprintf(stderr, "sidecar target path is too long\n");
    return 127;
  }

  char **child_argv = calloc((size_t)argc + 1, sizeof(char *));
  if (child_argv == NULL) {
    perror("calloc");
    return 127;
  }

  child_argv[0] = target_path;
  for (int index = 1; index < argc; index += 1) {
    child_argv[index] = argv[index];
  }

  execv(target_path, child_argv);
  perror(target_path);
  free(child_argv);
  return 127;
}
EOF
  run_without_python_dyld cc -Os -Wall -Wextra \
    ${WRAPPER_CC_ARCH_ARGS[@]+"${WRAPPER_CC_ARCH_ARGS[@]}"} \
    -mmacosx-version-min="$MACOS_DEPLOYMENT_TARGET" \
    -DBUNDLE_DIR="\"$bundle_dir\"" \
    -DEXECUTABLE_NAME="\"$executable_name\"" \
    "$source_path" \
    -o "$wrapper_path"
  chmod +x "$wrapper_path"
}

install_sidecar_bundle() {
  local source_dir="$1"
  local target_dir="$2"
  local executable_name="$3"

  rm -rf "$target_dir"
  mkdir -p "$(dirname "$target_dir")"
  cp -R "$source_dir" "$target_dir"
  chmod +x "$target_dir/$executable_name"
}

sign_macho_file() {
  local file_path="$1"

  case "$(run_without_python_dyld file -b "$file_path")" in
    *Mach-O*) run_without_python_dyld codesign --force --sign - --timestamp=none "$file_path" ;;
  esac
}

sign_macho_files() {
  local root_dir="$1"

  [ -d "$root_dir" ] || return 0
  while IFS= read -r -d '' file_path; do
    sign_macho_file "$file_path"
  done < <(find "$root_dir" -type f -print0)
}

sign_macos_executables() {
  local app_path="$1"
  local main_executable="$2"
  local macos_dir="$app_path/Contents/MacOS"
  local main_executable_path="$macos_dir/$main_executable"

  [ -d "$macos_dir" ] || return 0
  while IFS= read -r -d '' file_path; do
    [ "$file_path" = "$main_executable_path" ] && continue
    sign_macho_file "$file_path"
  done < <(find "$macos_dir" -type f -print0)

  [ -f "$main_executable_path" ] && sign_macho_file "$main_executable_path"
}

sign_release_app() {
  local app_path="$1"
  local main_executable="$2"

  sign_macho_files "$app_path/Contents/Resources"
  sign_macho_files "$app_path/Contents/Frameworks"
  sign_macho_files "$app_path/Contents/PlugIns"
  sign_macos_executables "$app_path" "$main_executable"
  run_without_python_dyld codesign --force --deep --sign - --timestamp=none "$app_path"
}

bundle_architectures() {
  local binary_path="$1"

  if command -v lipo >/dev/null 2>&1; then
    run_without_python_dyld lipo -archs "$binary_path" 2>/dev/null && return 0
  fi

  run_without_python_dyld file -b "$binary_path"
}

report_release_architecture() {
  local app_path="$1"
  local app_label="$2"
  local executable_name="$3"
  local executable_path="$app_path/Contents/MacOS/$executable_name"
  local architectures

  if [ ! -e "$executable_path" ]; then
    fail "$app_label expected release executable is missing: $executable_path"
  fi

  architectures="$(bundle_architectures "$executable_path")"
  printf '%s main executable architectures: %s\n' "$app_label" "$architectures"

  case " $architectures " in
    *" arm64 "* )
      case " $architectures " in
        *" x86_64 "* )
          printf '%s is a universal build.\n' "$app_label"
          ;;
        *)
          printf '%s is arm64-native for Apple Silicon.\n' "$app_label"
          ;;
      esac
      ;;
    *" x86_64 "* )
      printf 'Warning: %s is x86_64-only. Copying it to Apple Silicon macOS 12 will not make it native or universal; it will rely on Rosetta if that is available.\n' "$app_label"
      ;;
    *)
      printf 'Warning: %s architecture could not be classified from %s.\n' "$app_label" "$architectures"
      ;;
  esac
}

report_release_executable_architecture() {
  local label="$1"
  local executable_path="$2"
  local architectures

  architectures="$(binary_architectures "$executable_path")"
  printf '%s architectures: %s\n' "$label" "$architectures"
  if [ "$SHIP_MACOS_BUILD_MODE" = "universal" ]; then
    if ! archs_include "$architectures" "x86_64" || ! archs_include "$architectures" "arm64"; then
      fail "Universal build artifact is not universal: $label at $executable_path reports '$architectures'. Expected both x86_64 and arm64."
    fi
  fi
}

verify_release_app_architectures() {
  local app_path="$1"
  local app_label="$2"
  local main_executable="$3"
  local sidecar_wrapper="$4"
  local sidecar_bundle="$5"

  report_release_executable_architecture "$app_label main executable" "$app_path/Contents/MacOS/$main_executable"
  report_release_executable_architecture "$app_label sidecar wrapper" "$app_path/Contents/MacOS/$sidecar_wrapper"
  report_release_executable_architecture "$app_label bundled sidecar executable" "$app_path/Contents/Resources/$sidecar_bundle/$sidecar_wrapper"
}

tool_location() {
  local tool_name="$1"

  command -v "$tool_name" 2>/dev/null || printf 'not found'
}

rustup_target_help() {
  if command -v rustup >/dev/null 2>&1; then
    printf 'Run: rustup target add x86_64-apple-darwin aarch64-apple-darwin'
  else
    printf 'rustup is not in PATH. Install Rust via rustup from https://rustup.rs, then run: rustup target add x86_64-apple-darwin aarch64-apple-darwin'
  fi
}

preflight_universal_rust_targets() {
  local rustc_path
  local cargo_path
  local rust_target
  local probe_source="$BUILD_DIR/universal-rust-target-probe.rs"
  local probe_output
  local probe_log
  local rustup_help
  local rustc_output

  rustc_path="$(tool_location rustc)"
  cargo_path="$(tool_location cargo)"

  if [ "$cargo_path" = "not found" ]; then
    fail "Universal Tauri build requires Cargo before PyInstaller/npm work starts, but cargo is not installed. rustc: $rustc_path. Install Rust via rustup from https://rustup.rs, then run: rustup target add x86_64-apple-darwin aarch64-apple-darwin"
  fi
  if [ "$rustc_path" = "not found" ]; then
    fail "Universal Tauri build requires rustc before PyInstaller/npm work starts, but rustc is not installed. cargo: $cargo_path. Install Rust via rustup from https://rustup.rs, then run: rustup target add x86_64-apple-darwin aarch64-apple-darwin"
  fi

  printf 'fn main() {}\n' > "$probe_source"
  for rust_target in x86_64-apple-darwin aarch64-apple-darwin; do
    probe_output="$BUILD_DIR/universal-rust-target-probe-$rust_target.rmeta"
    probe_log="$BUILD_DIR/universal-rust-target-probe-$rust_target.log"
    if ! run_without_python_dyld rustc \
      --crate-name ship_universal_target_probe \
      --target "$rust_target" \
      --emit=metadata \
      "$probe_source" \
      -o "$probe_output" \
      >"$probe_log" 2>&1; then
      rustup_help="$(rustup_target_help)"
      rustc_output="$(cat "$probe_log")"
      fail "Universal Tauri build is missing a usable Rust std/core target: $rust_target.
rustc: $rustc_path
cargo: $cargo_path
$rustup_help
rustc probe output:
$rustc_output"
    fi
    printf 'Rust target preflight passed for %s.\n' "$rust_target"
  done
}

if [ "$SHIP_MACOS_BUILD_MODE" = "universal" ]; then
  preflight_universal_rust_targets
fi

"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/python" -m pip install pyinstaller "psd-tools>=1.10,<2"

rm -rf \
  "$BUILD_DIR/dist/ship-sender-backend" \
  "$BUILD_DIR/dist/ship-manager-backend"

"$VENV_DIR/bin/python" -m PyInstaller \
  --clean \
  ${PYINSTALLER_ARCH_ARGS[@]+"${PYINSTALLER_ARCH_ARGS[@]}"} \
  --name ship-sender-backend \
  --collect-submodules psd_tools \
  --paths "$ROOT_DIR/python" \
  --distpath "$BUILD_DIR/dist" \
  --workpath "$BUILD_DIR/work-sender" \
  --specpath "$BUILD_DIR/spec" \
  "$ROOT_DIR/python/ship_sender_app.py"

"$VENV_DIR/bin/python" -m PyInstaller \
  --clean \
  ${PYINSTALLER_ARCH_ARGS[@]+"${PYINSTALLER_ARCH_ARGS[@]}"} \
  --name ship-manager-backend \
  --collect-submodules psd_tools \
  --paths "$ROOT_DIR/python" \
  --distpath "$BUILD_DIR/dist" \
  --workpath "$BUILD_DIR/work-manager" \
  --specpath "$BUILD_DIR/spec" \
  "$ROOT_DIR/python/ship_manager_app.py"

if [ "$SHIP_MACOS_BUILD_MODE" = "universal" ]; then
  require_universal_macho "PyInstaller sender sidecar executable" "$BUILD_DIR/dist/ship-sender-backend/ship-sender-backend"
  require_universal_macho "PyInstaller manager sidecar executable" "$BUILD_DIR/dist/ship-manager-backend/ship-manager-backend"
fi

for wrapper_target_triple in "${WRAPPER_TARGET_TRIPLES[@]}"; do
  create_sidecar_wrapper \
    "$ROOT_DIR/apps/sender/src-tauri/binaries/ship-sender-backend-$wrapper_target_triple" \
    "../Resources/ship-sender-backend-bundle" \
    "ship-sender-backend"
  create_sidecar_wrapper \
    "$ROOT_DIR/apps/manager/src-tauri/binaries/ship-manager-backend-$wrapper_target_triple" \
    "../Resources/ship-manager-backend-bundle" \
    "ship-manager-backend"
  if [ "$SHIP_MACOS_BUILD_MODE" = "universal" ]; then
    require_universal_macho "sender sidecar wrapper $wrapper_target_triple" "$ROOT_DIR/apps/sender/src-tauri/binaries/ship-sender-backend-$wrapper_target_triple"
    require_universal_macho "manager sidecar wrapper $wrapper_target_triple" "$ROOT_DIR/apps/manager/src-tauri/binaries/ship-manager-backend-$wrapper_target_triple"
  fi
done

if [ ! -d "$ROOT_DIR/apps/sender/node_modules" ]; then
  run_without_python_dyld npm install --prefix "$ROOT_DIR/apps/sender"
fi
if [ ! -d "$ROOT_DIR/apps/manager/node_modules" ]; then
  run_without_python_dyld npm install --prefix "$ROOT_DIR/apps/manager"
fi
if [ ! -d "$ROOT_DIR/apps/log-viewer/node_modules" ]; then
  run_without_python_dyld npm install --prefix "$ROOT_DIR/apps/log-viewer"
fi

run_without_python_dyld npm --prefix "$ROOT_DIR/apps/sender" run build
run_without_python_dyld npm --prefix "$ROOT_DIR/apps/manager" run build
run_without_python_dyld npm --prefix "$ROOT_DIR/apps/log-viewer" run build

if ! command -v cargo >/dev/null 2>&1; then
  printf '\nPython %s sidecars and frontend builds are ready.\n' "$PYTHON_RUNTIME_VERSION" >&2
  printf 'Tauri .app build requires Rust/Cargo, but cargo is not installed.\n' >&2
  printf 'Install Rust, then run this script again: https://rustup.rs\n' >&2
  exit 2
fi
if [ "$SHIP_MACOS_BUILD_MODE" = "universal" ]; then
  if ! command -v rustc >/dev/null 2>&1; then
    fail "Universal Tauri build requires rustc and both macOS Rust targets. Install Rust with rustup, then run: rustup target add x86_64-apple-darwin aarch64-apple-darwin"
  fi
  for rust_target in x86_64-apple-darwin aarch64-apple-darwin; do
    if ! run_without_python_dyld rustc --print target-libdir --target "$rust_target" >/dev/null 2>&1; then
      fail "Universal Tauri build is missing Rust target $rust_target. Install it with: rustup target add $rust_target"
    fi
  done
fi

run_without_python_dyld npm --prefix "$ROOT_DIR/apps/sender" run tauri -- "${TAURI_BUILD_ARGS[@]}"
run_without_python_dyld npm --prefix "$ROOT_DIR/apps/manager" run tauri -- "${TAURI_BUILD_ARGS[@]}"
run_without_python_dyld npm --prefix "$ROOT_DIR/apps/log-viewer" run tauri -- "${TAURI_BUILD_ARGS[@]}"

rm -rf "$RELEASE_DIR/선적전송.app" "$RELEASE_DIR/선적관리.app" "$RELEASE_DIR/전송로그.app"
if [ "$SHIP_MACOS_BUILD_MODE" = "universal" ]; then
  SENDER_APP_BUILD_PATH="$ROOT_DIR/apps/sender/src-tauri/target/universal-apple-darwin/release/bundle/macos/선적전송.app"
  MANAGER_APP_BUILD_PATH="$ROOT_DIR/apps/manager/src-tauri/target/universal-apple-darwin/release/bundle/macos/선적관리.app"
  LOG_VIEWER_APP_BUILD_PATH="$ROOT_DIR/apps/log-viewer/src-tauri/target/universal-apple-darwin/release/bundle/macos/전송로그.app"
else
  SENDER_APP_BUILD_PATH="$ROOT_DIR/apps/sender/src-tauri/target/release/bundle/macos/선적전송.app"
  MANAGER_APP_BUILD_PATH="$ROOT_DIR/apps/manager/src-tauri/target/release/bundle/macos/선적관리.app"
  LOG_VIEWER_APP_BUILD_PATH="$ROOT_DIR/apps/log-viewer/src-tauri/target/release/bundle/macos/전송로그.app"
fi
[ -d "$SENDER_APP_BUILD_PATH" ] || fail "Sender .app bundle was not produced at $SENDER_APP_BUILD_PATH. Check the preceding Tauri build output."
[ -d "$MANAGER_APP_BUILD_PATH" ] || fail "Manager .app bundle was not produced at $MANAGER_APP_BUILD_PATH. Check the preceding Tauri build output."
[ -d "$LOG_VIEWER_APP_BUILD_PATH" ] || fail "Log viewer .app bundle was not produced at $LOG_VIEWER_APP_BUILD_PATH. Check the preceding Tauri build output."

install_sidecar_bundle \
  "$BUILD_DIR/dist/ship-sender-backend" \
  "$SENDER_APP_BUILD_PATH/Contents/Resources/ship-sender-backend-bundle" \
  "ship-sender-backend"
install_sidecar_bundle \
  "$BUILD_DIR/dist/ship-manager-backend" \
  "$MANAGER_APP_BUILD_PATH/Contents/Resources/ship-manager-backend-bundle" \
  "ship-manager-backend"

cp -R "$SENDER_APP_BUILD_PATH" "$RELEASE_DIR/"
cp -R "$MANAGER_APP_BUILD_PATH" "$RELEASE_DIR/"
cp -R "$LOG_VIEWER_APP_BUILD_PATH" "$RELEASE_DIR/"

if command -v codesign >/dev/null 2>&1; then
  sign_release_app "$RELEASE_DIR/선적전송.app" "ship_sender"
  sign_release_app "$RELEASE_DIR/선적관리.app" "ship_manager"
  sign_release_app "$RELEASE_DIR/전송로그.app" "ship_log_viewer"
else
  printf 'codesign not found; copied .app bundles are left unsigned.\n' >&2
fi

if [ "$SHIP_MACOS_BUILD_MODE" = "universal" ]; then
  verify_release_app_architectures "$RELEASE_DIR/선적전송.app" "선적전송.app" "ship_sender" "ship-sender-backend" "ship-sender-backend-bundle"
  verify_release_app_architectures "$RELEASE_DIR/선적관리.app" "선적관리.app" "ship_manager" "ship-manager-backend" "ship-manager-backend-bundle"
  report_release_executable_architecture "전송로그.app main executable" "$RELEASE_DIR/전송로그.app/Contents/MacOS/ship_log_viewer"
else
  report_release_architecture "$RELEASE_DIR/선적전송.app" "선적전송.app" "ship_sender"
  report_release_architecture "$RELEASE_DIR/선적관리.app" "선적관리.app" "ship_manager"
  report_release_architecture "$RELEASE_DIR/전송로그.app" "전송로그.app" "ship_log_viewer"
  report_release_executable_architecture "선적전송.app sidecar wrapper" "$RELEASE_DIR/선적전송.app/Contents/MacOS/ship-sender-backend"
  report_release_executable_architecture "선적전송.app bundled sidecar executable" "$RELEASE_DIR/선적전송.app/Contents/Resources/ship-sender-backend-bundle/ship-sender-backend"
  report_release_executable_architecture "선적관리.app sidecar wrapper" "$RELEASE_DIR/선적관리.app/Contents/MacOS/ship-manager-backend"
  report_release_executable_architecture "선적관리.app bundled sidecar executable" "$RELEASE_DIR/선적관리.app/Contents/Resources/ship-manager-backend-bundle/ship-manager-backend"
fi

printf '\nBuild complete:\n%s\n%s\n%s\n' "$RELEASE_DIR/선적전송.app" "$RELEASE_DIR/선적관리.app" "$RELEASE_DIR/전송로그.app"
printf '\nRelease notes:\n'
printf -- '- Python backends are bundled as PyInstaller onedir sidecar bundles inside Contents/Resources.\n'
printf -- '- The copied .app does not need a separate Python install; Python runtime files are inside the sidecar bundle directory.\n'
printf -- '- macOS deployment target: %s. The selected Python %s runtime was validated before packaging.\n' "$MACOS_DEPLOYMENT_TARGET" "$PYTHON_RUNTIME_VERSION"
printf -- '- Build mode: %s. Tauri target: %s.\n' "$SHIP_MACOS_BUILD_MODE" "$TARGET_TRIPLE"
if [ "$SHIP_MACOS_BUILD_MODE" = "universal" ]; then
  printf -- '- Universal mode passed lipo verification for sender/manager main executables, sidecar wrappers, bundled PyInstaller executables, and the log viewer main executable.\n'
else
  printf -- '- Native mode is intentionally thin. If the final app reports x86_64-only, keep it as an x86_64/Rosetta package or rebuild with SHIP_MACOS_BUILD_MODE=universal before shipping to macOS 12 Silicon Macs.\n'
fi
printf -- '- Sender DB lookup includes /System/Volumes/Data/USA_DB, /USA_DB, //Mserver/USA_DB, and /System/Volumes/Data/mnt/USA_DB paths; /health reports the exact DB path used.\n'
