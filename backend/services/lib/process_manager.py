"""Owns every helper process the app starts (RVC, TTS engines, llama-server).

Children are placed in their own process group and, on Windows, in a Job
Object configured to kill them when this process exits - so closing the
console window or a crash cannot leave a GPU-hogging server behind.
Only processes started here are ever stopped; nothing is killed by name.
"""
import atexit
import os
import signal
import subprocess
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Dict, Optional, Tuple

from .LAV_logger import logger
from .startup_progress import startup_progress

LOG_LINES_KEPT = 300  # bounded in-memory diagnostics per process; nothing is written to disk


@dataclass
class ServerProcess:
    process: subprocess.Popen
    name: str
    port: int
    ready_event: threading.Event
    logs: deque = field(default_factory=lambda: deque(maxlen=LOG_LINES_KEPT))


class _WindowsJob:
    """Kill-on-close Job Object so children never outlive the app on Windows."""

    def __init__(self):
        self.handle = None
        if sys.platform != "win32":
            return
        try:
            import ctypes
            from ctypes import wintypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

            class IO_COUNTERS(ctypes.Structure):
                _fields_ = [(n, ctypes.c_ulonglong) for n in (
                    "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                    "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

            class BASIC(ctypes.Structure):
                _fields_ = [
                    ("PerProcessUserTimeLimit", ctypes.c_int64),
                    ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD),
                    ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t),
                    ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t),
                    ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD),
                ]

            class EXTENDED(ctypes.Structure):
                _fields_ = [
                    ("BasicLimitInformation", BASIC),
                    ("IoInfo", IO_COUNTERS),
                    ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t),
                ]

            kernel32.CreateJobObjectW.restype = wintypes.HANDLE
            job = kernel32.CreateJobObjectW(None, None)
            info = EXTENDED()
            info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            ok = kernel32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info))
            if job and ok:
                self.handle = job
                self._kernel32 = kernel32
        except Exception as e:  # never block startup over this
            logger.debug(f"Job object unavailable: {e}")

    def assign(self, process: subprocess.Popen):
        if self.handle:
            try:
                self._kernel32.AssignProcessToJobObject(self.handle, int(process._handle))
            except Exception as e:
                logger.debug(f"Could not assign process to job: {e}")


class ProcessManager:
    def __init__(self):
        self.processes: Dict[str, ServerProcess] = {}
        self._lock = threading.Lock()
        self._job = _WindowsJob()
        atexit.register(self.stop_all_servers)

    def _read_output(self, pipe, proc: ServerProcess, ready_message: Optional[str]):
        try:
            for line in pipe:
                line = line.rstrip()
                if not line:
                    continue
                proc.logs.append(line)
                logger.info(f"{proc.name}: {line}")
                if ready_message and ready_message in line:
                    proc.ready_event.set()
        except Exception as e:
            logger.debug(f"Stopped reading {proc.name} output: {e}")

    def start_process(
        self,
        name: str,
        cmd: list,
        port: int,
        ready_message: Optional[str] = None,
        ready_check: Optional[Callable[[], bool]] = None,
        timeout: float = 60,
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        show_progress: bool = False,
        is_cancelled: Optional[Callable[[], bool]] = None,
    ) -> Tuple[bool, str]:
        """Start an owned process and wait until it reports ready, exits, or times out."""
        self.stop_server(name)
        start_time = time.time()
        if show_progress:
            startup_progress.show_step(f"Starting {name}")

        kwargs = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        else:
            kwargs["start_new_session"] = True

        try:
            process = subprocess.Popen(
                [str(c) for c in cmd],
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env={**os.environ, **(env or {})},
                **kwargs,
            )
        except Exception as e:
            msg = f"{name} failed to start: {e}"
            logger.error(msg)
            return False, msg

        self._job.assign(process)
        proc = ServerProcess(process=process, name=name, port=port, ready_event=threading.Event())
        with self._lock:
            self.processes[name] = proc
        threading.Thread(target=self._read_output, args=(process.stdout, proc, ready_message), daemon=True).start()

        deadline = time.time() + timeout
        while time.time() < deadline:
            if proc.ready_event.is_set() or (ready_check and ready_check()):
                msg = f"{name} ready in {time.time() - start_time:.1f}s"
                if show_progress:
                    startup_progress.complete_step(msg)
                return True, msg
            if process.poll() is not None:
                tail = "\n".join(list(proc.logs)[-15:])
                self.stop_server(name)
                return False, f"{name} exited during startup (code {process.returncode}).\n{tail}"
            if is_cancelled and is_cancelled():
                self.stop_server(name)
                return False, f"{name} start cancelled"
            time.sleep(0.25)

        self.stop_server(name)
        msg = f"{name} did not become ready within {timeout:.0f}s"
        if show_progress:
            startup_progress.complete_step(msg)
        return False, msg

    def start_server_process(self, name, python_path, script_path, port, ready_message="Uvicorn running on",
                             timeout=30, cwd=None, env=None) -> Tuple[bool, str]:
        """Compatibility wrapper used by the RVC plugin."""
        if not os.path.exists(python_path):
            return False, f"{name} runtime not installed"
        if not os.path.exists(script_path):
            return False, f"{name} server script not found"
        return self.start_process(name, [python_path, script_path], port, ready_message=ready_message,
                                  timeout=timeout, cwd=cwd, env=env, show_progress=True)

    def stop_server(self, name: str, grace: float = 5.0) -> bool:
        with self._lock:
            proc = self.processes.pop(name, None)
        if not proc:
            return False
        p = proc.process
        if p.poll() is not None:
            if p.stdout:
                p.stdout.close()
            return True
        try:
            if sys.platform == "win32":
                # Helpers keep no state worth flushing; TerminateProcess is immediate.
                # The tree kill below still runs if a grandchild keeps it alive.
                p.terminate()
            else:
                os.killpg(p.pid, signal.SIGTERM)
        except Exception:
            p.terminate()
        try:
            p.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            logger.warning(f"{name} did not exit in {grace:.0f}s, killing it")
            try:
                if sys.platform == "win32":
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True)
                else:
                    os.killpg(p.pid, signal.SIGKILL)
            except Exception:
                p.kill()
            try:
                p.wait(timeout=grace)
            except subprocess.TimeoutExpired:
                pass
        if p.stdout:
            p.stdout.close()
        logger.info(f"{name} stopped")
        return True

    def stop_all_servers(self):
        for name in list(self.processes.keys()):
            self.stop_server(name)

    def get_server_logs(self, name: str) -> list:
        proc = self.processes.get(name)
        return list(proc.logs) if proc else []

    def is_server_running(self, name: str) -> bool:
        proc = self.processes.get(name)
        return bool(proc) and proc.process.poll() is None


process_manager = ProcessManager()
