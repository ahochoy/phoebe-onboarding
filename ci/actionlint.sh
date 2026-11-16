#!/usr/bin/env bash
# ci/actionlint.sh: lint .github/workflows with a pinned actionlint release.
# The binary is downloaded once into ~/.cache/phoebe and checked against the
# release's SHA256 (pinned below); after that it runs offline.
set -euo pipefail

VERSION=1.7.12
case "$(uname -s)_$(uname -m)" in
  Darwin_arm64) PLATFORM=darwin_arm64 SUM=aba9ced2dee8d27fecca3dc7feb1a7f9a52caefa1eb46f3271ea66b6e0e6953f ;;
  Darwin_x86_64) PLATFORM=darwin_amd64 SUM=5b44c3bc2255115c9b69e30efc0fecdf498fdb63c5d58e17084fd5f16324c644 ;;
  Linux_x86_64) PLATFORM=linux_amd64 SUM=8aca8db96f1b94770f1b0d72b6dddcb1ebb8123cb3712530b08cc387b349a3d8 ;;
  Linux_aarch64 | Linux_arm64) PLATFORM=linux_arm64 SUM=325e971b6ba9bfa504672e29be93c24981eeb1c07576d730e9f7c8805afff0c6 ;;
  *)
    echo "actionlint: unsupported platform $(uname -s)_$(uname -m)" >&2
    exit 1
    ;;
esac

DIR="${XDG_CACHE_HOME:-$HOME/.cache}/phoebe/actionlint-$VERSION-$PLATFORM"
BIN="$DIR/actionlint"

sha256() {
  if command -v sha256sum >/dev/null; then sha256sum "$1" | cut -d' ' -f1; else shasum -a 256 "$1" | cut -d' ' -f1; fi
}

if [ ! -x "$BIN" ]; then
  mkdir -p "$DIR"
  TMP="$(mktemp -d)"
  trap 'rm -rf "$TMP"' EXIT
  TARBALL="actionlint_${VERSION}_${PLATFORM}.tar.gz"
  curl -fsSLo "$TMP/$TARBALL" "https://github.com/rhysd/actionlint/releases/download/v$VERSION/$TARBALL"
  GOT="$(sha256 "$TMP/$TARBALL")"
  if [ "$GOT" != "$SUM" ]; then
    echo "actionlint: checksum mismatch for $TARBALL (got $GOT)" >&2
    exit 1
  fi
  tar -xzf "$TMP/$TARBALL" -C "$TMP" actionlint
  mv "$TMP/actionlint" "$BIN"
fi

cd "$(dirname "${BASH_SOURCE[0]}")/.."
"$BIN"
