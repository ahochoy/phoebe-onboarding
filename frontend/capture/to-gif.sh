#!/usr/bin/env bash
# Turns the capture video into the README GIF: at most 15 s, 12 fps, 800 px wide, two-pass
# palette. Writes to a temp file and replaces the output only when the GIF is small enough,
# so a failed run never clobbers the last good GIF. MAX_BYTES overrides the 5 MB cap.
# Usage: to-gif.sh <input.webm> <output.gif>
set -euo pipefail

in="${1:?usage: to-gif.sh <input.webm> <output.gif>}"
out="${2:?usage: to-gif.sh <input.webm> <output.gif>}"
max="${MAX_BYTES:-5000000}"

command -v ffmpeg >/dev/null || { echo "ffmpeg not found (brew install ffmpeg)" >&2; exit 1; }
[ -s "$in" ] || { echo "no video at $in: did the capture run?" >&2; exit 1; }

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
filters="fps=12,scale=800:-1:flags=lanczos"
ffmpeg -loglevel error -y -t 15 -i "$in" -vf "$filters,palettegen=stats_mode=diff" "$tmp/palette.png"
ffmpeg -loglevel error -y -t 15 -i "$in" -i "$tmp/palette.png" \
  -lavfi "$filters [x]; [x][1:v] paletteuse=dither=bayer:bayer_scale=5" "$tmp/out.gif"

size="$(wc -c < "$tmp/out.gif" | tr -d ' ')"
if [ "$size" -gt "$max" ]; then
  echo "GIF is $(awk "BEGIN { printf \"%.1f\", $size / 1000000 }") MB, over the $(awk "BEGIN { printf \"%.1f\", $max / 1000000 }") MB cap; $out left unchanged" >&2
  exit 1
fi
mkdir -p "$(dirname "$out")"
mv "$tmp/out.gif" "$out"
echo "wrote $out ($size bytes)"
