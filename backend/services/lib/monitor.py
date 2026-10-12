"""Live resource usage split by what is using it: the LLM, the voice engine, the app window,
the app itself, and everything else on the computer.

Sources, best first: psutil (CPU/RAM per process), NVML (NVIDIA totals and per-process
VRAM), Windows GPU performance counters via WMI (per-process VRAM/GPU% for any vendor,
including when NVML can't attribute memory under the Windows display driver model).
Whatever a platform blocks is reported in `notes` instead of failing.

Sampling only happens while the UI is asking for it, so an idle app costs nothing.
"""
import json
import os
import subprocess
import sys
import threading
import time
from typing import Dict, Optional, Set

import psutil

from .LAV_logger import logger
from .process_manager import process_manager

IS_WIN, IS_MAC = sys.platform == "win32", sys.platform == "darwin"
COMPONENTS = ("llm", "voice", "window", "app")
GB = 2 ** 30


class UsageMonitor:
    def __init__(self):
        self._procs: Dict[int, psutil.Process] = {}
        self.window_pids: Set[int] = set()
        self._lock = threading.Lock()
        self._cache: Optional[dict] = None
        self._cache_time = 0.0
        self._last_request = 0.0
        self._nvml = None
        self._nvml_failed = False
        self._win_counters: dict = {}
        self._win_counter_note: Optional[str] = None
        self._win_thread: Optional[threading.Thread] = None
        psutil.cpu_percent(None)  # prime the system-wide counter

    # ------------------------------------------------------------------ which process is what

    def register_window(self, pid: int):
        """The launcher tells us the app-window browser process so its GPU/CPU use is attributed."""
        if psutil.pid_exists(pid):
            self.window_pids.add(pid)

    def _tree(self, pid: Optional[int]) -> Set[int]:
        if not pid:
            return set()
        try:
            p = psutil.Process(pid)
            return {pid} | {c.pid for c in p.children(recursive=True)}
        except psutil.Error:
            return set()

    def _component_pids(self) -> Dict[str, Set[int]]:
        procs = dict(process_manager.processes)
        llm = self._tree(procs["LLM"].process.pid) if "LLM" in procs else set()
        voice = set()
        for name, sp in procs.items():
            if name.startswith("TTS-") or name == "RVC":
                voice |= self._tree(sp.process.pid)
        window = set()
        for pid in list(self.window_pids):
            tree = self._tree(pid)
            if not tree:
                self.window_pids.discard(pid)
            window |= tree
        app = self._tree(os.getpid()) - llm - voice
        return {"llm": llm, "voice": voice, "window": window, "app": app}

    def _proc(self, pid: int) -> Optional[psutil.Process]:
        p = self._procs.get(pid)
        if p is None:
            try:
                p = psutil.Process(pid)
                p.cpu_percent(None)
                self._procs[pid] = p
            except psutil.Error:
                return None
        return p

    # ------------------------------------------------------------------ GPU sources

    def _nvml_handle(self):
        if self._nvml or self._nvml_failed:
            return self._nvml
        try:
            import pynvml
            pynvml.nvmlInit()
            self._nvml = pynvml
        except Exception:
            self._nvml_failed = True
        return self._nvml

    def _nvidia(self, groups: Dict[str, Set[int]], notes: list) -> list:
        nv = self._nvml_handle()
        if not nv:
            return []
        gpus = []
        for i in range(nv.nvmlDeviceGetCount()):
            h = nv.nvmlDeviceGetHandleByIndex(i)
            name = nv.nvmlDeviceGetName(h)
            mem = nv.nvmlDeviceGetMemoryInfo(h)
            try:
                util = nv.nvmlDeviceGetUtilizationRates(h).gpu
            except Exception:
                util = None
            try:
                temp = nv.nvmlDeviceGetTemperature(h, nv.NVML_TEMPERATURE_GPU)
            except Exception:
                temp = None
            by_vram = {c: 0.0 for c in COMPONENTS}
            attributed = False
            try:
                plist = list(nv.nvmlDeviceGetComputeRunningProcesses(h)) + list(nv.nvmlDeviceGetGraphicsRunningProcesses(h))
                for p in plist:
                    used = getattr(p, "usedGpuMemory", None)
                    if used is None or used > mem.total:  # "not available" under Windows WDDM
                        continue
                    for comp, pids in groups.items():
                        if p.pid in pids:
                            by_vram[comp] += used / GB
                            attributed = True
            except Exception:
                pass
            gpus.append({
                "name": name if isinstance(name, str) else name.decode(),
                "vram_total_gb": mem.total / GB, "vram_used_gb": mem.used / GB,
                "util_pct": util, "temp_c": temp, "by_vram": by_vram, "by_util": {},
                "per_app": attributed,
            })
        return gpus

    def _start_windows_counters(self):
        if not IS_WIN or (self._win_thread and self._win_thread.is_alive()):
            return
        self._win_thread = threading.Thread(target=self._windows_counter_loop, daemon=True)
        self._win_thread.start()

    def _windows_counter_loop(self):
        script = (
            "$m=Get-CimInstance Win32_PerfFormattedData_GPUPerformanceCounters_GPUProcessMemory -ErrorAction Stop|"
            "Select-Object Name,DedicatedUsage;"
            "$e=Get-CimInstance Win32_PerfFormattedData_GPUPerformanceCounters_GPUEngine -ErrorAction Stop|"
            "Where-Object {$_.UtilizationPercentage -gt 0}|Select-Object Name,UtilizationPercentage;"
            "$a=Get-CimInstance Win32_PerfFormattedData_GPUPerformanceCounters_GPUAdapterMemory -ErrorAction Stop|"
            "Select-Object Name,DedicatedUsage;"
            "@{mem=@($m);eng=@($e);adapter=@($a)}|ConvertTo-Json -Compress -Depth 3"
        )
        while time.time() - self._last_request < 15:
            try:
                out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                                     capture_output=True, text=True, timeout=20,
                                     creationflags=subprocess.CREATE_NO_WINDOW)
                if out.returncode != 0 or not out.stdout.strip():
                    raise RuntimeError((out.stderr or "no output").strip().splitlines()[-1][:200])
                data = json.loads(out.stdout)
                per_pid: Dict[int, dict] = {}
                for row in data.get("mem") or []:
                    pid = _pid_from(row.get("Name", ""))
                    if pid:
                        per_pid.setdefault(pid, {"mem": 0, "util": 0.0})["mem"] += int(row.get("DedicatedUsage") or 0)
                for row in data.get("eng") or []:
                    pid = _pid_from(row.get("Name", ""))
                    if pid:
                        per_pid.setdefault(pid, {"mem": 0, "util": 0.0})["util"] += float(row.get("UtilizationPercentage") or 0)
                adapter_used = sum(int(r.get("DedicatedUsage") or 0) for r in data.get("adapter") or [])
                total_util = sum(v["util"] for v in per_pid.values())
                self._win_counters = {"per_pid": per_pid, "adapter_used": adapter_used,
                                      "total_util": min(total_util, 100.0), "time": time.time()}
                self._win_counter_note = None
            except FileNotFoundError:
                self._win_counter_note = "PowerShell isn't available, so per-app GPU usage can't be read."
                return
            except Exception as e:
                self._win_counter_note = ("Windows blocked the GPU performance counters (per-app GPU usage). "
                                          f"Totals are still shown when the driver provides them. Details: {e}")
                logger.debug(f"GPU counters unavailable: {e}")
            time.sleep(3)

    def _apply_windows_counters(self, gpus: list, groups: Dict[str, Set[int]], gpu_info: list):
        data = self._win_counters
        if not data or time.time() - data["time"] > 20:
            return gpus
        by_vram = {c: 0.0 for c in COMPONENTS}
        by_util = {c: 0.0 for c in COMPONENTS}
        for pid, v in data["per_pid"].items():
            for comp, pids in groups.items():
                if pid in pids:
                    by_vram[comp] += v["mem"] / GB
                    by_util[comp] += v["util"]
        if gpus:  # NVIDIA via NVML: fill in what NVML couldn't attribute
            g = gpus[0]
            if not g["per_app"]:
                g["by_vram"], g["per_app"] = by_vram, True
            g["by_util"] = by_util
            return gpus
        # AMD / Intel: everything comes from the counters
        best = max((x for x in gpu_info if x.get("vram_gb")), key=lambda x: x["vram_gb"], default=None)
        return [{
            "name": best["name"] if best else "GPU",
            "vram_total_gb": best["vram_gb"] if best else None,
            "vram_used_gb": data["adapter_used"] / GB, "util_pct": data["total_util"], "temp_c": None,
            "by_vram": by_vram, "by_util": by_util, "per_app": True,
        }]

    # ------------------------------------------------------------------ sample

    def sample(self, gpu_info: Optional[list] = None) -> dict:
        self._last_request = time.time()
        with self._lock:
            if self._cache and time.time() - self._cache_time < 1.5:
                return self._cache
            notes = []
            groups = self._component_pids()
            ncpu = psutil.cpu_count() or 1
            cpu_by = {c: 0.0 for c in COMPONENTS}
            ram_by = {c: 0.0 for c in COMPONENTS}
            for comp, pids in groups.items():
                for pid in pids:
                    p = self._proc(pid)
                    if not p:
                        continue
                    try:
                        cpu_by[comp] += p.cpu_percent(None) / ncpu
                        ram_by[comp] += p.memory_info().rss / GB
                    except psutil.Error:
                        self._procs.pop(pid, None)
            alive = set().union(*groups.values())
            for pid in list(self._procs):
                if pid not in alive:
                    self._procs.pop(pid, None)

            vm = psutil.virtual_memory()
            gpus = []
            try:
                gpus = self._nvidia(groups, notes)
            except Exception as e:
                notes.append(f"The NVIDIA driver didn't return GPU readings ({type(e).__name__}).")
            if IS_WIN:
                self._start_windows_counters()
                gpus = self._apply_windows_counters(gpus, groups, gpu_info or [])
                if self._win_counter_note:
                    notes.append(self._win_counter_note)
            if IS_MAC:
                notes.append("macOS shares memory between the CPU and GPU, so the model's memory is counted under RAM "
                             "and per-app GPU usage isn't available.")
            elif not gpus:
                notes.append("No GPU readings available on this system; showing CPU and RAM only.")
            elif gpus and not gpus[0]["per_app"]:
                notes.append("The graphics driver doesn't report memory per app here, so GPU memory is shown as a total.")

            self._cache = {
                "time": time.time(),
                "cpu": {"total_pct": psutil.cpu_percent(None), "by": cpu_by, "threads": ncpu},
                "ram": {"total_gb": vm.total / GB, "used_gb": (vm.total - vm.available) / GB, "by": ram_by},
                "gpus": gpus,
                "notes": notes,
            }
            self._cache_time = time.time()
            return self._cache


def _pid_from(name: str) -> Optional[int]:
    # WMI instance names look like "pid_1234_luid_0x00000000_0x0000C3D5_phys_0_eng_0_engtype_3D"
    if name.startswith("pid_"):
        try:
            return int(name.split("_")[1])
        except (IndexError, ValueError):
            return None
    return None


usage_monitor = UsageMonitor()
