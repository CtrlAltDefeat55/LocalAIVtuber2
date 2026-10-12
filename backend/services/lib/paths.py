"""Single source of truth for app-owned locations.

Everything the app needs lives under APP_ROOT (the folder that contains
`backend/` and `frontend/`), so the whole folder can be moved or renamed.
Paths are derived from this file's location, never from the current
working directory.
"""
import os
import shutil
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
APP_ROOT = BACKEND_DIR.parent
FRONTEND_DIST = APP_ROOT / "frontend" / "dist"

# Installed runtimes (python envs, llama-server binaries) - created by the installer.
RUNTIME_DIR = APP_ROOT / "runtime"
LLAMA_DIR = RUNTIME_DIR / "llama"
ENGINE_ENVS_DIR = RUNTIME_DIR / "envs"
UV_BIN_DIR = RUNTIME_DIR / "uv"

# Reusable downloads (model weights from Hugging Face, torch hub, ...).
CACHE_DIR = APP_ROOT / "cache"
HF_HOME = CACHE_DIR / "huggingface"

# Disposable per-session scratch space; wiped on every start.
TEMP_DIR = CACHE_DIR / "tmp"

SETTINGS_FILE = BACKEND_DIR / "settings.json"
LLM_MODELS_DIR = BACKEND_DIR / "services" / "LLM" / "Models"
VOICES_DIR = BACKEND_DIR / "services" / "TTS" / "GPTsovits" / "models"
TTS_ENGINE_SCRIPT = BACKEND_DIR / "engines" / "tts_sidecar.py"


def configure_environment():
    """Point third-party caches into the app folder before those libraries import.

    Only sets variables that are not already defined, so a user who has
    deliberately configured a shared cache keeps it. The values are inherited
    by child processes (TTS engines, llama-server) and nothing else.
    """
    defaults = {
        "HF_HOME": HF_HOME,
        "TORCH_HOME": CACHE_DIR / "torch",
        "FASTEMBED_CACHE_PATH": CACHE_DIR / "fastembed",
        "NLTK_DATA": CACHE_DIR / "nltk_data",
        "MODELSCOPE_CACHE": CACHE_DIR / "modelscope",
        "UV_CACHE_DIR": CACHE_DIR / "uv",
        "UV_PYTHON_INSTALL_DIR": RUNTIME_DIR / "python",
    }
    for key, value in defaults.items():
        os.environ.setdefault(key, str(value))
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    os.environ["UV_PYTHON_PREFERENCE"] = "only-managed"  # engine envs use the app's own Python

    # Prefer app-local tools (ffmpeg next to server.py, bundled uv) over PATH.
    extra = [str(BACKEND_DIR), str(UV_BIN_DIR)]
    os.environ["PATH"] = os.pathsep.join(extra + [os.environ.get("PATH", "")])

    # Session scratch: anything left behind by a crash is reclaimed here.
    shutil.rmtree(TEMP_DIR, ignore_errors=True)
    TEMP_DIR.mkdir(parents=True, exist_ok=True)


def hf_token():
    """Token saved by the UI (or `huggingface-cli login`) in the app-local HF home."""
    token = os.environ.get("HF_TOKEN")
    if token:
        return token.strip()
    path = Path(os.environ.get("HF_HOME", HF_HOME)) / "token"
    try:
        return path.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def save_hf_token(token: str | None):
    path = Path(os.environ.get("HF_HOME", HF_HOME)) / "token"
    if token:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(token.strip(), encoding="utf-8")
    else:
        path.unlink(missing_ok=True)
