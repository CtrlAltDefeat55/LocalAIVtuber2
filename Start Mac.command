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

if [ ! -x "$UV" ]; then
  echo "First start: downloading the setup tool (uv, about 20 MB)..."
  case "$(uname -s)-$(uname -m)" in
    Darwin-arm64) TARGET=aarch64-apple-darwin ;;
    Darwin-x86_64) TARGET=x86_64-apple-darwin ;;
    Linux-aarch64) TARGET=aarch64-unknown-linux-gnu ;;
    *) TARGET=x86_64-unknown-linux-gnu ;;
  esac
  mkdir -p "$DIR/runtime/uv"
  TMP="$(mktemp -d)"
  curl -fL --retry 3 "https://github.com/astral-sh/uv/releases/latest/download/uv-$TARGET.tar.gz" -o "$TMP/uv.tar.gz"
  tar -xzf "$TMP/uv.tar.gz" -C "$TMP"
  mv "$TMP"/uv-*/uv "$UV"
  rm -rf "$TMP"
  chmod +x "$UV"
fi

exec "$UV" run --no-project --python 3.11 "$DIR/launcher/launcher.py" --started-by "$(basename "$0")" "$@"
