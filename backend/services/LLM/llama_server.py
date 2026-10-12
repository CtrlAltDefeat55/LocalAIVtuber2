"""Runs llama.cpp's `llama-server` as an owned child process.

llama-server is used instead of the old llama-cpp-python bindings because
it ships prebuilt for CUDA, Vulkan, Metal and CPU, supports the newest model
architectures (Qwen3.8, Gemma 4, ...) and automatically fits GPU layers and
context to the available VRAM.
"""
import os
import shutil
import socket
import sys
from pathlib import Path
from typing import Optional

import httpx

from services.lib.LAV_logger import logger
from services.lib.paths import LLAMA_DIR
from services.lib.process_manager import process_manager

PROCESS_NAME = "LLM"
EXE = "llama-server.exe" if sys.platform == "win32" else "llama-server"


def find_llama_server() -> Optional[Path]:
    override = os.environ.get("LAV_LLAMA_SERVER")
    if override and Path(override).is_file():
        return Path(override)
    if LLAMA_DIR.exists():
        direct = LLAMA_DIR / EXE
        if direct.is_file():
            return direct
        for found in LLAMA_DIR.rglob(EXE):  # release archives may nest a folder
            return found
    on_path = shutil.which("llama-server")
    return Path(on_path) if on_path else None


def _free_port(preferred: int) -> int:
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", preferred))
            return preferred
        except OSError:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]


class LlamaServer:
    def __init__(self, preferred_port: int = 8012):
        self.preferred_port = preferred_port
        self.port: Optional[int] = None
        self.model_path: Optional[str] = None
        self.mmproj_path: Optional[str] = None

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def is_running(self) -> bool:
        return process_manager.is_server_running(PROCESS_NAME)

    def _healthy(self) -> bool:
        try:
            return httpx.get(f"{self.base_url}/health", timeout=2).status_code == 200
        except httpx.HTTPError:
            return False

    def start(self, model_path: str, mmproj_path: Optional[str] = None, context_size: int = 8192,
              gpu_layers: str = "auto", extra_args: Optional[list] = None, is_cancelled=None):
        binary = find_llama_server()
        if not binary:
            raise RuntimeError("The LLM runtime (llama-server) is not installed. Run the start script again "
                               "to repair the installation, or set LAV_LLAMA_SERVER to a llama-server binary.")
        self.stop()
        self.port = _free_port(self.preferred_port)
        cmd = [binary, "-m", model_path, "--host", "127.0.0.1", "--port", str(self.port),
               "-c", str(int(context_size)), "--jinja", "--no-webui"]
        if mmproj_path:
            cmd += ["--mmproj", mmproj_path]
        if gpu_layers not in (None, "", "auto"):
            cmd += ["-ngl", str(gpu_layers)]  # "auto" lets llama.cpp fit layers to free VRAM
        cmd += extra_args or []
        logger.info(f"Starting llama-server: {' '.join(map(str, cmd))}")
        ok, msg = process_manager.start_process(
            PROCESS_NAME, cmd, self.port, ready_check=self._healthy, timeout=600,
            cwd=str(binary.parent), is_cancelled=is_cancelled)
        if not ok:
            raise RuntimeError(_explain_failure(msg))
        self.model_path, self.mmproj_path = model_path, mmproj_path

    def stop(self):
        process_manager.stop_server(PROCESS_NAME)
        self.model_path = self.mmproj_path = None


def _explain_failure(msg: str) -> str:
    low = msg.lower()
    if "out of memory" in low or "failed to allocate" in low or "cudamalloc" in low:
        return ("Not enough GPU memory for this model. Lower the context size, set GPU layers to a smaller "
                "number, or choose a smaller model.\n\n" + msg)
    if "unknown model architecture" in low:
        return ("This llama-server build is too old for this model. Run the start script again to update "
                "the LLM runtime.\n\n" + msg)
    return msg
