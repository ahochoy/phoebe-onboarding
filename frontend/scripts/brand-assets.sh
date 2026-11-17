#!/usr/bin/env bash
# Generate Larkspur Labs brand assets from the brand kit and two portrait photos.
# Usage: brand-assets.sh SRC_KIT MELINDA_JPG JORDAN_JPG
set -euo pipefail

if [ "$#" -ne 3 ]; then
  echo "usage: $0 SRC_KIT MELINDA_JPG JORDAN_JPG" >&2
  exit 2
fi
KIT="$1"; MELINDA="$2"; JORDAN="$3"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BRAND="$ROOT/src/assets/brand"
PEOPLE="$ROOT/src/assets/people"
PUBLIC="$ROOT/public"
mkdir -p "$BRAND" "$PEOPLE" "$PUBLIC/og"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# Poses at 256 and 512 px.
for pose in waving thinking pointing celebrating onboarding-checklist oops-error; do
  for n in 256 512; do
    cwebp -quiet -q 82 -alpha_q 90 -resize "$n" "$n" \
      "$KIT/phoebe/transparent/phoebe-$pose.png" -o "$BRAND/phoebe-$pose-$n.webp"
  done
done

# Avatar: head crop of the waving pose (square, centred on the head).
magick "$KIT/phoebe/transparent/phoebe-waving.png" -crop 480x480+230+0 +repage "$TMP/avatar.png"
for n in 32 64; do
  cwebp -quiet -q 82 -alpha_q 90 -resize "$n" "$n" "$TMP/avatar.png" -o "$BRAND/phoebe-avatar-$n.webp"
done

# People photos: centre square crop on the face, 192 px.
photo() {
  magick "$1" -crop 860x860+82+20 +repage "$TMP/photo.png"
  cwebp -quiet -q 80 -resize 192 192 "$TMP/photo.png" -o "$2"
}
photo "$MELINDA" "$PEOPLE/melinda-grant.webp"
photo "$JORDAN" "$PEOPLE/jordan-moore.webp"

# Logos and loader, copied as-is.
cp "$KIT/logo/larkspur-labs-logo.svg" "$BRAND/larkspur-logo.svg"
cp "$KIT/logo/larkspur-labs-mark.svg" "$BRAND/larkspur-mark.svg"
cp "$KIT/loader/larkspur-loader.svg" "$BRAND/larkspur-loader.svg"

# Favicons into public/ (replaces favicon.svg); the kit manifest is rewritten below.
for f in "$KIT"/favicon/*; do
  [ "$(basename "$f")" = "site.webmanifest" ] && continue
  cp "$f" "$PUBLIC/"
done
cat > "$PUBLIC/site.webmanifest" <<'JSON'
{
  "name": "Phoebe · Larkspur Labs",
  "short_name": "Phoebe",
  "icons": [
    {
      "src": "android-chrome-192x192.png",
      "sizes": "192x192",
      "type": "image/png"
    },
    {
      "src": "android-chrome-512x512.png",
      "sizes": "512x512",
      "type": "image/png"
    },
    {
      "src": "maskable-icon-512x512.png",
      "sizes": "512x512",
      "type": "image/png",
      "purpose": "maskable"
    }
  ],
  "theme_color": "#ffffff",
  "background_color": "#ffffff",
  "display": "standalone"
}
JSON

# Link preview.
magick "$KIT/social/larkspur-link-preview-1200x630.png" -background white -flatten -quality 85 "$PUBLIC/og/link-preview.jpg"
echo "brand assets written"
