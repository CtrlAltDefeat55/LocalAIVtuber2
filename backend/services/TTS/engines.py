"""Installs, starts and talks to the voice engines.

Every engine lives in its own Python environment under runtime/envs/<id>,
created with `uv` (fast, and it downloads the right Python by itself), and
runs as a sidecar process owned by this app.
"""
import os
import platform
import shutil
import socket
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path
from typing import Optional

import httpx

from services.lib.LAV_logger import logger
from services.lib.paths import BACKEND_DIR, ENGINE_ENVS_DIR, TTS_ENGINE_SCRIPT, UV_BIN_DIR, hf_token
from services.lib.process_manager import process_manager

GPTSOVITS_REQS = BACKEND_DIR / "services" / "TTS" / "GPTsovits" / "requirements.txt"
LUXTTS_COMMIT = "28ae6a61151684fffc9d1a7aa15eafa02286fe0b"

ENGINES = {
    "chatterbox": {
        "label": "Chatterbox Turbo",
        "summary": "Natural, expressive English voice cloning with very low latency. Best all-round choice.",
        "languages": ["en"],
        "speed": 4, "quality": 5,
        "vram": "~4 GB",
        "min_ref_seconds": 5.5,
        "python": "3.11",
        "packages": ["chatterbox-tts==0.1.7"],
        # chatterbox pins torch 2.6, which cannot run on RTX 50-series; 2.8 works for both.
        "overrides": ["torch==2.8.0", "torchaudio==2.8.0"],
        "torch": "2.8.0",
        "recommended": True,
    },
    "luxtts": {
        "label": "LuxTTS",
        "summary": "Fastest option (48 kHz, under 1 GB VRAM, runs on CPU too). Slightly less expressive.",
        "languages": ["en"],
        "speed": 5, "quality": 4,
        "vram": "~1 GB",
        "min_ref_seconds": 3,
        "python": "3.11",
        "packages": [
            "linacodec @ https://github.com/ysharma3501/LinaCodec/archive/refs/heads/main.zip",
            f"zipvoice @ https://github.com/ysharma3501/LuxTTS/archive/{LUXTTS_COMMIT}.zip",
        ],
        "find_links": ["https://k2-fsa.github.io/icefall/piper_phonemize.html"],
        "torch": "2.8.0",
    },
    "omnivoice": {
        "label": "OmniVoice",
        "summary": "High quality cloning in 600+ languages. Great for non-English characters; a bit slower to start each line.",
        "languages": ["multilingual"],
        "speed": 3, "quality": 5,
        "vram": "~5 GB",
        "min_ref_seconds": 3,
        "python": "3.11",
        "packages": ["omnivoice==0.2.1"],
        "torch": "2.8.0",
    },
    "tada": {
        "label": "TADA (Hume AI)",
        "summary": "Very stable, hallucination-free speech. 1B is English; 3B adds more languages but needs more VRAM.",
        "languages": ["en", "multilingual (3B)"],
        "speed": 3, "quality": 4,
        "vram": "~6 GB (1B) / ~12 GB (3B)",
        "min_ref_seconds": 3,
        "python": "3.11",
        "packages": ["hume-tada==0.1.9"],
        "torch": "2.8.0",
        "variants": {"1b": "TADA 1B (English, faster)", "3b": "TADA 3B (multilingual)"},
        "needs_token": "Uses Meta Llama 3.2. Accept the license at huggingface.co/meta-llama/Llama-3.2-1B "
                       "and huggingface.co/HumeAI/tada-1b, then add your Hugging Face token in Settings.",
    },
    "gptsovits": {
        "label": "GPT-SoVITS (classic)",
        "summary": "The engine earlier versions used. Supports English, Japanese, Chinese, Korean and Cantonese.",
        "languages": ["en", "ja", "zh", "ko", "yue"],
        "speed": 3, "quality": 3,
        "vram": "~3 GB",
        "min_ref_seconds": 3,
        "python": "3.10",
        "requirements_file": str(GPTSOVITS_REQS),
        "packages": ["huggingface_hub", "colorama", "nltk"],
        "torch": "2.8.0",
        # its checkpoints are full pickles; torch >= 2.6 refuses those unless told otherwise
        "env": {"TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD": "1"},
        "post_install": ["-c", "import nltk;[nltk.download(p, quiet=True) for p in "
                               "('averaged_perceptron_tagger','averaged_perceptron_tagger_eng','cmudict')]"],
    },
}


def find_uv() -> Optional[str]:
    for name in ("uv.exe", "uv"):
        candidate = UV_BIN_DIR / name
        if candidate.is_file():
            return str(candidate)
    return shutil.which("uv")


def detect_gpu() -> dict:
    """Pick the PyTorch build: CUDA wheel matched to the card, Metal on Apple Silicon, or CPU."""
    if sys.platform == "darwin":
        return {"kind": "mps" if platform.machine() == "arm64" else "cpu", "index": None}
    smi = shutil.which("nvidia-smi")
    if smi:
        try:
            out = subprocess.run([smi, "--query-gpu=name,compute_cap", "--format=csv,noheader"],
                                 capture_output=True, text=True, timeout=10).stdout.strip().splitlines()
            if out:
                name, cap = [x.strip() for x in out[0].split(",")[:2]]
                # CUDA 12.8 wheels cover RTX 20-50 series; GTX 10-series needs the 12.6 build.
                cuda = "cu128" if float(cap) >= 7.5 else "cu126"
                return {"kind": "cuda", "name": name, "index": f"https://download.pytorch.org/whl/{cuda}"}
        except Exception as e:
            logger.debug(f"nvidia-smi query failed: {e}")
    return {"kind": "cpu", "index": "https://download.pytorch.org/whl/cpu" if sys.platform != "darwin" else None}


def env_python(engine_id: str) -> Path:
    env = ENGINE_ENVS_DIR / engine_id
    return env / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class EngineManager:
    def __init__(self):
        self.state: dict[str, str] = {}
        self.errors: dict[str, Optional[str]] = {}
        self.logs: dict[str, deque] = {k: deque(maxlen=200) for k in ENGINES}
        self.step: dict[str, str] = {}
        self.ports: dict[str, int] = {}
        self.variants: dict[str, Optional[str]] = {}
        self._install_procs: dict[str, subprocess.Popen] = {}
        self._cancel: dict[str, bool] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ status

    def is_installed(self, engine_id: str) -> bool:
        return (ENGINE_ENVS_DIR / engine_id / ".installed").exists() and env_python(engine_id).exists()

    def engine_state(self, engine_id: str) -> str:
        state = self.state.get(engine_id)
        if state in ("installing", "starting", "error"):
            return state
        if state == "ready" and process_manager.is_server_running(self._proc_name(engine_id)):
            return "ready"
        return "stopped" if self.is_installed(engine_id) else "not_installed"

    def describe(self, engine_id: str) -> dict:
        spec = ENGINES[engine_id]
        logs = list(self.logs[engine_id]) + process_manager.get_server_logs(self._proc_name(engine_id))
        return {
            "id": engine_id,
            **{k: v for k, v in spec.items() if k in (
                "label", "summary", "languages", "speed", "quality", "vram", "min_ref_seconds",
                "recommended", "variants", "needs_token")},
            "state": self.engine_state(engine_id),
            "installed": self.is_installed(engine_id),
            "error": self.errors.get(engine_id),
            "step": self.step.get(engine_id),
            "variant": self.variants.get(engine_id),
            "has_token": bool(hf_token()) if spec.get("needs_token") else None,
            "log": logs[-40:],
        }

    def list(self) -> list:
        return [self.describe(k) for k in ENGINES]

    # ------------------------------------------------------------------ install

    def install(self, engine_id: str):
        with self._lock:
            if self.state.get(engine_id) == "installing":
                return
            self.state[engine_id] = "installing"
            self.errors[engine_id] = None
            self._cancel[engine_id] = False
        threading.Thread(target=self._install, args=(engine_id,), daemon=True).start()

    def cancel_install(self, engine_id: str):
        self._cancel[engine_id] = True
        proc = self._install_procs.get(engine_id)
        if proc and proc.poll() is None:
            proc.terminate()

    def _run(self, engine_id: str, cmd: list, env: Optional[dict] = None):
        if self._cancel.get(engine_id):
            raise RuntimeError("Installation cancelled")
        self.logs[engine_id].append("$ " + " ".join(str(c) for c in cmd[:6]) + (" ..." if len(cmd) > 6 else ""))
        kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
        proc = subprocess.Popen([str(c) for c in cmd], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="replace", env={**os.environ, **(env or {})},
                                **kwargs)
        self._install_procs[engine_id] = proc
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                self.logs[engine_id].append(line)
        proc.wait()
        if self._cancel.get(engine_id):
            raise RuntimeError("Installation cancelled")
        if proc.returncode != 0:
            tail = "\n".join(list(self.logs[engine_id])[-8:])
            raise RuntimeError(f"Step failed (exit code {proc.returncode}).\n{tail}")

    def _install(self, engine_id: str):
        spec = ENGINES[engine_id]
        env_dir = ENGINE_ENVS_DIR / engine_id
        try:
            uv = find_uv()
            if not uv:
                raise RuntimeError("The installer tool (uv) is missing. Run the start script again to repair.")
            self.stop(engine_id)
            (env_dir / ".installed").unlink(missing_ok=True)
            gpu = detect_gpu()
            py = env_python(engine_id)

            self.step[engine_id] = f"1/3 Creating Python {spec['python']} environment"
            self._run(engine_id, [uv, "venv", "--allow-existing", "--relocatable", "--python", spec["python"], env_dir])

            self.step[engine_id] = f"2/3 Installing PyTorch ({gpu['kind'].upper()})"
            torch_cmd = [uv, "pip", "install", "--python", py, f"torch=={spec['torch']}", f"torchaudio=={spec['torch']}"]
            if gpu.get("index"):
                torch_cmd += ["--index-url", gpu["index"]]
            self._run(engine_id, torch_cmd)

            self.step[engine_id] = f"3/3 Installing {spec['label']}"
            cmd = [uv, "pip", "install", "--python", py, *spec.get("packages", [])]
            if spec.get("requirements_file"):
                cmd += ["-r", spec["requirements_file"]]
            for link in spec.get("find_links", []):
                cmd += ["--find-links", link]
            # keep the CUDA torch we just installed instead of letting a package pull another build
            pins = list(spec.get("overrides", [])) or [f"torch=={spec['torch']}", f"torchaudio=={spec['torch']}"]
            overrides_file = env_dir / "overrides.txt"
            overrides_file.write_text("\n".join(pins) + "\n", encoding="utf-8")
            cmd += ["--override", overrides_file]
            if gpu.get("index"):
                cmd += ["--extra-index-url", gpu["index"], "--index-strategy", "unsafe-best-match"]
            self._run(engine_id, cmd)

            if spec.get("post_install"):
                self._run(engine_id, [py, *spec["post_install"]])

            (env_dir / ".installed").write_text(time.strftime("%Y-%m-%d %H:%M:%S"), encoding="utf-8")
            self.step[engine_id] = None
            self.state[engine_id] = "stopped"
            self.logs[engine_id].append(f"{spec['label']} installed.")
            logger.info(f"Voice engine installed: {spec['label']}")
        except Exception as e:
            self.step[engine_id] = None
            if self._cancel.get(engine_id):
                shutil.rmtree(env_dir, ignore_errors=True)  # never leave a half-built environment
                self.state.pop(engine_id, None)
                self.errors[engine_id] = None
                self.logs[engine_id].append("Installation cancelled.")
                logger.info(f"Installing {engine_id} cancelled")
            else:
                self.state[engine_id] = "error"
                self.errors[engine_id] = str(e)
                logger.error(f"Installing {engine_id} failed: {e}")
        finally:
            self._install_procs.pop(engine_id, None)

    def uninstall(self, engine_id: str):
        self.stop(engine_id)
        shutil.rmtree(ENGINE_ENVS_DIR / engine_id, ignore_errors=True)
        self.state.pop(engine_id, None)
        self.errors.pop(engine_id, None)

    # ------------------------------------------------------------------ run

    @staticmethod
    def _proc_name(engine_id: str) -> str:
        return f"TTS-{engine_id}"

    def start(self, engine_id: str, variant: Optional[str] = None, device: str = "auto"):
        """Blocking: start the sidecar (first start also downloads weights)."""
        if not self.is_installed(engine_id):
            raise RuntimeError(f"{ENGINES[engine_id]['label']} is not installed yet.")
        name = self._proc_name(engine_id)
        if (process_manager.is_server_running(name) and self.variants.get(engine_id) == variant
                and self.state.get(engine_id) == "ready"):
            return
        self.state[engine_id], self.errors[engine_id] = "starting", None
        port = _free_port()
        cmd = [env_python(engine_id), TTS_ENGINE_SCRIPT, "--engine", engine_id, "--port", port, "--device", device]
        if variant:
            cmd += ["--variant", variant]
        env = {"PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8", **ENGINES[engine_id].get("env", {})}
        token = hf_token()
        if token:
            env["HF_TOKEN"] = token
        ok, msg = process_manager.start_process(name, cmd, port, ready_message="SIDECAR READY", timeout=1800,
                                                cwd=str(BACKEND_DIR), env=env)
        if not ok:
            self.state[engine_id], self.errors[engine_id] = "error", _explain(msg)
            raise RuntimeError(self.errors[engine_id])
        self.ports[engine_id] = port
        self.variants[engine_id] = variant
        self.state[engine_id] = "ready"

    def stop(self, engine_id: str):
        process_manager.stop_server(self._proc_name(engine_id))
        if self.state.get(engine_id) in ("ready", "starting"):
            self.state[engine_id] = "stopped"

    def stop_all_except(self, keep: Optional[str]):
        for engine_id in ENGINES:
            if engine_id != keep:
                self.stop(engine_id)

    async def synthesize(self, engine_id: str, text: str, voice: dict, options: dict) -> bytes:
        port = self.ports.get(engine_id)
        if self.engine_state(engine_id) != "ready" or not port:
            raise RuntimeError(f"{ENGINES[engine_id]['label']} is not running")
        payload = {"text": text, "voice": voice, "options": options}
        async with httpx.AsyncClient(timeout=httpx.Timeout(connect=5, read=180, write=30, pool=200)) as client:
            r = await client.post(f"http://127.0.0.1:{port}/synthesize", json=payload)
        if r.status_code != 200:
            try:
                detail = r.json().get("error")
            except Exception:
                detail = r.text[:300]
            raise RuntimeError(_explain(detail or f"HTTP {r.status_code}"))
        return r.content


def _explain(msg: str) -> str:
    low = (msg or "").lower()
    if "longer than 5 seconds" in low:
        return "Chatterbox needs a reference clip longer than 5 seconds. Upload a longer sample for this voice."
    if "gated" in low or "401" in low or "403" in low or "access to model" in low:
        return ("This engine needs access to a gated Hugging Face model. Accept the license on huggingface.co "
                "and add your token in Settings.\n\n" + msg)
    if "out of memory" in low:
        return "Not enough GPU memory for this voice engine. Try LuxTTS, or unload a larger LLM.\n\n" + msg
    return msg
