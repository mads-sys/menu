#!/bin/bash
BASE=https://raw.githubusercontent.com/novnc/noVNC/master/core
DEST=novnc/core

files=(
    "clipboard.js"
    "crypto/crypto.js"
    "crypto/aes.js"
    "crypto/bigint.js"
    "crypto/des.js"
    "crypto/dh.js"
    "crypto/md5.js"
    "crypto/rsa.js"
)

for f in "${files[@]}"; do
    url="$BASE/$f"
    dest="$DEST/$f"
    mkdir -p "$(dirname $dest)"
    result=$(curl -fsSL "$url" -o "$dest" 2>&1)
    size=$(wc -c < "$dest" 2>/dev/null || echo 0)
    if [ "$size" -gt 10 ]; then
        echo "OK  $f (${size}B)"
    else
        echo "FAIL $f"
        rm -f "$dest"
    fi
done

echo ""
echo "=== Verificando todos imports do rfb.js ==="
grep "^import" novnc/core/rfb.js | while read line; do
    # extrai o caminho do import
    path=$(echo "$line" | grep -oP "(?<=['\"])\./[^'\"]+(?=['\"])")
    if [ -n "$path" ]; then
        full="novnc/core/${path#./}"
        if [ -f "$full" ]; then
            size=$(wc -c < "$full")
            echo "  OK  $path (${size}B)"
        else
            echo "  MISS $path  <- FALTANDO!"
        fi
    fi
done
echo "Concluído!"
