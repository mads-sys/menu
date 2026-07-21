#!/bin/bash
BASE=https://raw.githubusercontent.com/novnc/noVNC/master/core
DEST=novnc/core

files=(
    "decoders/raw.js"
    "decoders/zlib.js"
    "decoders/zrle.js"
    "decoders/hextile.js"
    "decoders/rre.js"
    "decoders/tight.js"
    "decoders/tightpng.js"
    "decoders/copyrect.js"
    "decoders/h264.js"
    "rfb.js"
    "websock.js"
    "display.js"
    "inflator.js"
    "deflator.js"
    "ra2.js"
    "encodings.js"
    "base64.js"
    "util/int.js"
    "util/logging.js"
    "util/strings.js"
    "util/browser.js"
    "util/element.js"
    "util/events.js"
    "util/eventtarget.js"
    "util/cursor.js"
    "input/keyboard.js"
    "input/domkeytable.js"
    "input/fixedkeys.js"
    "input/gesturehandler.js"
    "input/keysym.js"
    "input/keysymdef.js"
    "input/util.js"
    "input/vkeys.js"
    "input/xtscancodes.js"
)

for f in "${files[@]}"; do
    url="$BASE/$f"
    dest="$DEST/$f"
    mkdir -p "$(dirname $dest)"
    size_before=$(wc -c < "$dest" 2>/dev/null || echo 0)
    curl -fsSL "$url" -o "$dest"
    size_after=$(wc -c < "$dest")
    echo "$f: ${size_before}B -> ${size_after}B"
done

echo "Concluído!"
