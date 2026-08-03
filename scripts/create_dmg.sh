#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 3 ]; then
  printf 'Usage: %s <app-path> <output-dmg> <volume-name>\n' "$0" >&2
  exit 2
fi

APP_PATH="$1"
OUTPUT_DMG="$2"
VOLUME_NAME="$3"

[ -d "$APP_PATH" ] || { printf 'App bundle not found: %s\n' "$APP_PATH" >&2; exit 1; }
case "$APP_PATH" in
  *.app) ;;
  *) printf 'Expected .app bundle, got: %s\n' "$APP_PATH" >&2; exit 1 ;;
esac

APP_NAME="$(basename "$APP_PATH")"
OUTPUT_DIR="$(dirname "$OUTPUT_DMG")"
OUTPUT_NAME="$(basename "$OUTPUT_DMG")"
mkdir -p "$OUTPUT_DIR"
OUTPUT_DMG="$(cd "$OUTPUT_DIR" && pwd)/$OUTPUT_NAME"
TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/ship-dmg.XXXXXX")"
TMP_DIR="$(cd "$TMP_DIR" && pwd -P)"
STAGE_DIR="$TMP_DIR/stage"
MOUNT_DIR="$TMP_DIR/mount"
RW_DMG="$TMP_DIR/rw.dmg"
BACKGROUND_DIR="$STAGE_DIR/.background"
BACKGROUND_PNG="$BACKGROUND_DIR/background.png"
LAYOUT_SCRIPT="$TMP_DIR/layout.applescript"
DETACHED=1
DETACH_TARGET="$MOUNT_DIR"

is_mounted() {
  /sbin/mount | /usr/bin/grep -F " on $1 " >/dev/null 2>&1
}

detach_mount() {
  local mount_path="$1"
  local detach_target="$2"
  local attempt

  for attempt in 1 2 3 4 5; do
    if ! is_mounted "$mount_path"; then
      return 0
    fi
    if hdiutil detach "$detach_target" -quiet; then
      return 0
    fi
    sync
    sleep "$attempt"
  done

  printf 'Mount still busy after retries, forcing detach: %s\n' "$mount_path" >&2
  if hdiutil detach "$detach_target" -quiet -force; then
    return 0
  fi
  if ! is_mounted "$mount_path"; then
    return 0
  fi

  /usr/sbin/diskutil unmount force "$mount_path" >/dev/null 2>&1 || true
  hdiutil detach "$detach_target" -quiet -force || true
  if ! is_mounted "$mount_path"; then
    return 0
  fi

  printf 'Failed to detach mounted DMG target %s at %s\n' "$detach_target" "$mount_path" >&2
  return 1
}

cleanup() {
  if [ "$DETACHED" -eq 0 ]; then
    detach_mount "$MOUNT_DIR" "$DETACH_TARGET" || true
  fi
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

mkdir -p "$STAGE_DIR" "$MOUNT_DIR" "$BACKGROUND_DIR" "$(dirname "$OUTPUT_DMG")"
cp -R "$APP_PATH" "$STAGE_DIR/$APP_NAME"
ln -s /Applications "$STAGE_DIR/Applications"

python3 - "$BACKGROUND_PNG" <<'PYIMG'
from pathlib import Path
import struct
import sys
import zlib

path = Path(sys.argv[1])
width, height = 560, 360
bg = (246, 246, 244, 255)
arrow = (61, 105, 180, 255)
arrow_shadow = (35, 35, 35, 55)
text = (95, 95, 95, 255)

pixels = [[bg for _ in range(width)] for _ in range(height)]

def blend(x, y, color):
    if not (0 <= x < width and 0 <= y < height):
        return
    r, g, b, a = color
    br, bgc, bb, ba = pixels[y][x]
    alpha = a / 255
    pixels[y][x] = (
        round(r * alpha + br * (1 - alpha)),
        round(g * alpha + bgc * (1 - alpha)),
        round(b * alpha + bb * (1 - alpha)),
        255,
    )

def rect(x0, y0, x1, y1, color):
    for y in range(y0, y1):
        for x in range(x0, x1):
            blend(x, y, color)

def polygon(points, color):
    min_y = max(0, min(y for _, y in points))
    max_y = min(height - 1, max(y for _, y in points))
    for y in range(min_y, max_y + 1):
        hits = []
        for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1]):
            if y1 == y2:
                continue
            if (y >= min(y1, y2)) and (y < max(y1, y2)):
                hits.append(x1 + (y - y1) * (x2 - x1) / (y2 - y1))
        hits.sort()
        for left, right in zip(hits[0::2], hits[1::2]):
            for x in range(max(0, round(left)), min(width, round(right) + 1)):
                blend(x, y, color)

def arrow_at(dx, dy, color):
    rect(220 + dx, 167 + dy, 340 + dx, 181 + dy, color)
    polygon([(340 + dx, 145 + dy), (400 + dx, 174 + dy), (340 + dx, 203 + dy)], color)

# Subtle placement halos behind app and Applications icons.
for cx in (145, 445):
    for y in range(82, 260):
        for x in range(cx - 88, cx + 88):
            dist = ((x - cx) ** 2 / 88 ** 2) + ((y - 171) ** 2 / 74 ** 2)
            if dist <= 1:
                blend(x, y, (255, 255, 255, round(80 * (1 - dist))))

arrow_at(4, 5, arrow_shadow)
arrow_at(0, 0, arrow)

# Small dotted guide under the arrow.
for x in range(232, 390, 18):
    rect(x, 226, x + 8, 230, text)

raw = bytearray()
for row in pixels:
    raw.append(0)
    for pixel in row:
        raw.extend(pixel)

def chunk(kind, data):
    return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xFFFFFFFF)

png = b'\x89PNG\r\n\x1a\n'
png += chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0))
png += chunk(b'IDAT', zlib.compress(bytes(raw), 9))
png += chunk(b'IEND', b'')
path.write_bytes(png)
PYIMG

hdiutil create \
  -volname "$VOLUME_NAME" \
  -srcfolder "$STAGE_DIR" \
  -fs HFS+ \
  -fsargs '-c c=64,a=16,e=16' \
  -format UDRW \
  -ov \
  "$RW_DMG" \
  >/dev/null

ATTACH_OUTPUT="$(hdiutil attach "$RW_DMG" -readwrite -noverify -noautoopen -mountpoint "$MOUNT_DIR")"
while IFS= read -r line; do
  case "$line" in
    /dev/*)
      DETACH_TARGET="${line%%[[:space:]]*}"
      break
      ;;
  esac
done <<EOF
$ATTACH_OUTPUT
EOF
DETACHED=0

cat > "$LAYOUT_SCRIPT" <<'APPLESCRIPT'
on run argv
  set mountPath to item 1 of argv
  set appName to item 2 of argv
  set volumeFolder to POSIX file mountPath as alias
  set backgroundPicture to POSIX file (mountPath & "/.background/background.png") as alias
  tell application "Finder"
    tell folder volumeFolder
      open
      set current view of container window to icon view
      set toolbar visible of container window to false
      set statusbar visible of container window to false
      set the bounds of container window to {100, 100, 660, 460}
      set viewOptions to the icon view options of container window
      set arrangement of viewOptions to not arranged
      set icon size of viewOptions to 96
      set background picture of viewOptions to backgroundPicture
      set position of item appName of container window to {145, 175}
      set position of item "Applications" of container window to {445, 175}
      update without registering applications
      delay 1
      close
    end tell
  end tell
end run
APPLESCRIPT

osascript "$LAYOUT_SCRIPT" "$MOUNT_DIR" "$APP_NAME" >/dev/null
sync
sleep 2
detach_mount "$MOUNT_DIR" "$DETACH_TARGET"
DETACHED=1

rm -f "$OUTPUT_DMG"
hdiutil convert "$RW_DMG" -format UDZO -imagekey zlib-level=9 -o "$OUTPUT_DMG" >/dev/null
printf 'Created %s\n' "$OUTPUT_DMG"
