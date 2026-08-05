import os
import stat
import subprocess
import textwrap
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


REPO_ROOT = Path(__file__).resolve().parents[2]
CREATE_DMG = REPO_ROOT / "scripts" / "create_dmg.sh"


def write_executable(path: Path, content: str) -> None:
    path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


class CreateDmgTests(unittest.TestCase):
    def test_retries_transient_hdiutil_create_failure(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            state_dir = root / "state"
            state_dir.mkdir()
            app_path = root / "Demo.app"
            (app_path / "Contents" / "MacOS").mkdir(parents=True)
            (app_path / "Contents" / "MacOS" / "demo").write_text("demo", encoding="utf-8")
            output_dmg = root / "out" / "demo.dmg"

            write_executable(
                bin_dir / "hdiutil",
                """
                #!/usr/bin/env bash
                set -euo pipefail
                state_dir="$TEST_STATE_DIR"
                case "$1" in
                  create)
                    count_file="$state_dir/create-count"
                    count=0
                    if [ -f "$count_file" ]; then
                      count="$(cat "$count_file")"
                    fi
                    count=$((count + 1))
                    printf '%s' "$count" > "$count_file"
                    if [ "$count" -lt 6 ]; then
                      printf 'hdiutil: create failed - Resource busy\n' >&2
                      exit 1
                    fi
                    out="${@: -1}"
                    mkdir -p "$(dirname "$out")"
                    printf 'rw' > "$out"
                    ;;
                  attach)
                    mountpoint=""
                    while [ "$#" -gt 0 ]; do
                      if [ "$1" = "-mountpoint" ]; then
                        mountpoint="$2"
                        break
                      fi
                      shift
                    done
                    printf '/dev/disk99\tApple_HFS\t%s\n' "$mountpoint"
                    ;;
                  detach)
                    ;;
                  convert)
                    out=""
                    while [ "$#" -gt 0 ]; do
                      if [ "$1" = "-o" ]; then
                        out="$2"
                        break
                      fi
                      shift
                    done
                    mkdir -p "$(dirname "$out")"
                    printf 'dmg' > "$out"
                    ;;
                  *)
                    printf 'unexpected hdiutil command: %s\n' "$1" >&2
                    exit 2
                    ;;
                esac
                """,
            )
            write_executable(
                bin_dir / "osascript",
                """
                #!/usr/bin/env bash
                exit 0
                """,
            )

            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
            env["TEST_STATE_DIR"] = str(state_dir)
            env["SHIP_DMG_CREATE_RETRY_DELAY"] = "0"

            result = subprocess.run(
                [str(CREATE_DMG), str(app_path), str(output_dmg), "Demo"],
                cwd=REPO_ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((state_dir / "create-count").read_text(encoding="utf-8"), "6")
            self.assertEqual(output_dmg.read_text(encoding="utf-8"), "dmg")

    def test_retries_transient_hdiutil_convert_failure(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            state_dir = root / "state"
            state_dir.mkdir()
            app_path = root / "Demo.app"
            (app_path / "Contents" / "MacOS").mkdir(parents=True)
            (app_path / "Contents" / "MacOS" / "demo").write_text("demo", encoding="utf-8")
            output_dmg = root / "out" / "demo.dmg"

            write_executable(
                bin_dir / "hdiutil",
                """
                #!/usr/bin/env bash
                set -euo pipefail
                state_dir="$TEST_STATE_DIR"
                case "$1" in
                  create)
                    out="${@: -1}"
                    mkdir -p "$(dirname "$out")"
                    printf 'rw' > "$out"
                    ;;
                  attach)
                    mountpoint=""
                    while [ "$#" -gt 0 ]; do
                      if [ "$1" = "-mountpoint" ]; then
                        mountpoint="$2"
                        break
                      fi
                      shift
                    done
                    printf '/dev/disk99\tApple_HFS\t%s\n' "$mountpoint"
                    ;;
                  detach)
                    ;;
                  convert)
                    count_file="$state_dir/convert-count"
                    count=0
                    if [ -f "$count_file" ]; then
                      count="$(cat "$count_file")"
                    fi
                    count=$((count + 1))
                    printf '%s' "$count" > "$count_file"
                    if [ "$count" -lt 8 ]; then
                      printf 'hdiutil: convert failed - Resource temporarily unavailable\n' >&2
                      exit 1
                    fi
                    out=""
                    while [ "$#" -gt 0 ]; do
                      if [ "$1" = "-o" ]; then
                        out="$2"
                        break
                      fi
                      shift
                    done
                    mkdir -p "$(dirname "$out")"
                    printf 'dmg' > "$out"
                    ;;
                  *)
                    printf 'unexpected hdiutil command: %s\n' "$1" >&2
                    exit 2
                    ;;
                esac
                """,
            )
            write_executable(
                bin_dir / "osascript",
                """
                #!/usr/bin/env bash
                exit 0
                """,
            )

            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
            env["TEST_STATE_DIR"] = str(state_dir)
            env["SHIP_DMG_CONVERT_RETRY_DELAY"] = "0"

            result = subprocess.run(
                [str(CREATE_DMG), str(app_path), str(output_dmg), "Demo"],
                cwd=REPO_ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((state_dir / "convert-count").read_text(encoding="utf-8"), "8")
            self.assertEqual(output_dmg.read_text(encoding="utf-8"), "dmg")


if __name__ == "__main__":
    unittest.main()
