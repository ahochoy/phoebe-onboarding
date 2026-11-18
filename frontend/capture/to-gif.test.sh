#!/usr/bin/env bash
# Offline check for to-gif.sh: a generated test clip, no AWS. Run: bash frontend/capture/to-gif.test.sh
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
fail() { echo "FAIL: $*" >&2; exit 1; }

ffmpeg -loglevel error -f lavfi -i testsrc=size=1280x800:rate=30 -t 3 "$tmp/in.webm"

"$here/to-gif.sh" "$tmp/in.webm" "$tmp/out.gif" || fail "conversion exited non-zero"
[ -s "$tmp/out.gif" ] || fail "no GIF written"
width="$(ffprobe -v error -select_streams v:0 -show_entries stream=width -of csv=p=0 "$tmp/out.gif")"
[ "$width" = 800 ] || fail "width is $width, want 800"

if "$here/to-gif.sh" "$tmp/missing.webm" "$tmp/out2.gif" 2>/dev/null; then fail "missing input accepted"; fi
[ ! -e "$tmp/out2.gif" ] || fail "output written for a missing input"

printf 'old' > "$tmp/keep.gif"
if msg="$(MAX_BYTES=1 "$here/to-gif.sh" "$tmp/in.webm" "$tmp/keep.gif" 2>&1)"; then fail "oversized GIF accepted"; fi
[[ "$msg" == *MB* ]] || fail "size message missing MB: $msg"
[ "$(cat "$tmp/keep.gif")" = old ] || fail "existing GIF overwritten"

echo "to-gif: OK"
