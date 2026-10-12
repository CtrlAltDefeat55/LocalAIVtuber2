#!/bin/bash
# macOS: double-click in Finder. Installs on first run, then starts Local AI VTuber. Everything stays inside this folder.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
# Works from the app folder, or from "Other start scripts" inside it.
if [ ! -f "$DIR/launcher/launcher.py" ] && [ -f "$DIR/../launcher/launcher.py" ]; then DIR="$(cd "$DIR/.." && pwd)"; fi
cd "$DIR"
export UV_PYTHON_INSTALL_DIR="$DIR/runtime/python"
export UV_CACHE_DIR="$DIR/cache/uv"
export UV_NO_MODIFY_PATH=1
export UV_PYTHON_PREFERENCE=only-managed
UV="$DIR/runtime/uv/uv"

# A missing, half-downloaded or damaged uv is detected here and fetched again.
if ! "$UV" --version >/dev/null 2>&1; then
  if [ -e "$UV" ]; then echo "The setup tool (uv) is damaged - downloading it again..."
  else echo "First start: downloading the setup tool (uv, about 20 MB)..."; fi
  case "$(uname -s)-$(uname -m)" in
    Darwin-arm64) TARGET=aarch64-apple-darwin ;;
    Darwin-x86_64) TARGET=x86_64-apple-darwin ;;
    Linux-aarch64) TARGET=aarch64-unknown-linux-gnu ;;
    *) TARGET=x86_64-unknown-linux-gnu ;;
  esac
  mkdir -p "$DIR/runtime/uv"
  TMP="$DIR/runtime/uv/unpack"   # inside the app folder, so the final move is a single rename
  rm -rf "$TMP"; mkdir -p "$TMP"
  if ! curl -fL --retry 5 --retry-delay 3 -C - "https://github.com/astral-sh/uv/releases/latest/download/uv-$TARGET.tar.gz" -o "$TMP/uv.tar.gz" \
     || ! tar -xzf "$TMP/uv.tar.gz" -C "$TMP"; then
    echo "Could not download uv. Check your internet connection and run this script again."
    rm -rf "$TMP"; exit 1
  fi
  chmod +x "$TMP"/uv-*/uv
  mv -f "$TMP"/uv-*/uv "$UV"
  rm -rf "$TMP"
fi

# Reinstall the private Python if it is missing or damaged (the launcher runs on it).
"$UV" run --no-project --python 3.11 python -c "import encodings, json, zipfile, ssl" >/dev/null 2>&1 \
  || "$UV" python install --reinstall 3.11 || true

exec "$UV" run --no-project --python 3.11 "$DIR/launcher/launcher.py" --started-by "$(basename "$0")" "$@"
