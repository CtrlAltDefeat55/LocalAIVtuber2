"""Scan this computer (CPU, RAM, GPUs, disk) and recommend models that will run well.

Every probe is independent and best-effort: when the OS blocks one (e.g. a
locked-down Windows policy stops PowerShell or WMI), the scan carries on and
records a plain-language note so the UI can tell the user what is missing.
Nothing here needs admin rights.
"""
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from typing import Optional

import psutil

from .paths import APP_ROOT

IS_WIN, IS_MAC = sys.platform == "win32", sys.platform == "darwin"
_NO_WINDOW = {"creationflags": subprocess.CREATE_NO_WINDOW} if IS_WIN else {}

# GPU memory the model needs beyond its file size (context cache + runtime buffers) at 8k context.
LLM_OVERHEAD_GB = 1.5
# Voice engines: approximate GPU memory while running.
VOICE_VRAM_GB = {"chatterbox": 4.0, "luxtts": 1.0, "omnivoice": 5.0, "tada": 6.0, "gptsovits": 3.0}


def _run(cmd, timeout=15) -> str:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, **_NO_WINDOW).stdout


# ---------------------------------------------------------------------------- probes

def _cpu(notes):
    name = platform.processor() or platform.machine()
    try:
        if IS_WIN:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as k:
                name = winreg.QueryValueEx(k, "ProcessorNameString")[0]
        elif IS_MAC:
            name = _run(["sysctl", "-n", "machdep.cpu.brand_string"]).strip() or name
        else:
            with open("/proc/cpuinfo", encoding="utf-8", errors="ignore") as f:
                m = re.search(r"model name\s*:\s*(.+)", f.read())
                name = m.group(1) if m else name
    except Exception as e:
        notes.append(f"Couldn't read the CPU model name ({type(e).__name__}); core counts are still accurate.")
    freq = None
    try:
        f = psutil.cpu_freq()
        freq = round(f.max / 1000, 2) if f and f.max else None
    except Exception:
        pass
    return {"name": " ".join(str(name).split()), "cores": psutil.cpu_count(logical=False),
            "threads": psutil.cpu_count(logical=True), "max_ghz": freq, "arch": platform.machine()}


def _ram():
    vm = psutil.virtual_memory()
    return {"total_gb": round(vm.total / 2**30, 1), "available_gb": round(vm.available / 2**30, 1)}


def _nvidia_gpus(notes) -> list:
    try:
        import pynvml
        pynvml.nvmlInit()
        gpus = []
        driver = pynvml.nvmlSystemGetDriverVersion()
        for i in range(pynvml.nvmlDeviceGetCount()):
            h = pynvml.nvmlDeviceGetHandleByIndex(i)
            name = pynvml.nvmlDeviceGetName(h)
            mem = pynvml.nvmlDeviceGetMemoryInfo(h)
            major, minor = pynvml.nvmlDeviceGetCudaComputeCapability(h)
            gpus.append({"vendor": "NVIDIA", "name": name if isinstance(name, str) else name.decode(),
                         "vram_gb": round(mem.total / 2**30, 1), "driver": driver if isinstance(driver, str) else driver.decode(),
                         "compute": float(f"{major}.{minor}"), "backend": "CUDA", "source": "NVML"})
        return gpus
    except Exception:
        pass  # NVML library missing or no NVIDIA GPU; try nvidia-smi
    smi = shutil.which("nvidia-smi")
    if not smi:
        return []
    try:
        out = _run([smi, "--query-gpu=name,memory.total,driver_version,compute_cap", "--format=csv,noheader,nounits"])
        gpus = []
        for line in out.strip().splitlines():
            name, mem, driver, cap = [x.strip() for x in line.split(",")[:4]]
            gpus.append({"vendor": "NVIDIA", "name": name, "vram_gb": round(float(mem) / 1024, 1), "driver": driver,
                         "compute": float(cap), "backend": "CUDA", "source": "nvidia-smi"})
        return gpus
    except Exception as e:
        notes.append(f"An NVIDIA GPU tool exists but couldn't be queried ({type(e).__name__}). "
                     "Updating the NVIDIA driver usually fixes this.")
        return []


def _windows_gpus(notes) -> list:
    """All display adapters from the registry (works for AMD/Intel; no PowerShell needed)."""
    gpus = []
    try:
        import winreg
        base = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base) as root:
            for i in range(winreg.QueryInfoKey(root)[0]):
                sub = winreg.EnumKey(root, i)
                if not sub.isdigit():
                    continue
                try:
                    with winreg.OpenKey(root, sub) as k:
                        name = winreg.QueryValueEx(k, "DriverDesc")[0]
                        try:
                            mem = winreg.QueryValueEx(k, "HardwareInformation.qwMemorySize")[0]
                        except OSError:
                            mem = winreg.QueryValueEx(k, "HardwareInformation.MemorySize")[0]
                        if isinstance(mem, bytes):
                            mem = int.from_bytes(mem[:8], "little")
                        try:
                            driver = winreg.QueryValueEx(k, "DriverVersion")[0]
                        except OSError:
                            driver = None
                except OSError:
                    continue  # adapter without memory info (e.g. remote display)
                vendor = "AMD" if re.search(r"AMD|Radeon", name, re.I) else "Intel" if "Intel" in name else \
                    "NVIDIA" if re.search(r"NVIDIA|GeForce|RTX|Quadro", name, re.I) else "Other"
                gpus.append({"vendor": vendor, "name": name, "vram_gb": round(int(mem) / 2**30, 1), "driver": driver,
                             "backend": "Vulkan", "source": "registry", "integrated": vendor == "Intel" and int(mem) < 2**30})
    except PermissionError:
        notes.append("Windows blocked reading the graphics adapter list (registry access denied). "
                     "AMD/Intel GPU details may be missing; NVIDIA cards are still detected.")
    except Exception as e:
        notes.append(f"Couldn't read the graphics adapter list from Windows ({type(e).__name__}).")
    return gpus


def _mac_gpus(notes, ram_gb) -> list:
    try:
        data = json.loads(_run(["system_profiler", "SPDisplaysDataType", "-json"], timeout=30))
        gpus = []
        for d in data.get("SPDisplaysDataType", []):
            name = d.get("sppci_model") or d.get("_name", "GPU")
            apple = platform.machine() == "arm64"
            gpus.append({"vendor": "Apple" if apple else d.get("spdisplays_vendor", ""), "name": name,
                         # Apple Silicon shares memory; macOS lets the GPU use roughly 70% of it.
                         "vram_gb": round(ram_gb * 0.7, 1) if apple else None,
                         "cores": d.get("sppci_cores"), "backend": "Metal", "unified": apple, "source": "system_profiler"})
        return gpus
    except Exception as e:
        notes.append(f"macOS didn't return GPU details ({type(e).__name__}). Assuming Apple Silicon shared memory.")
        return [{"vendor": "Apple", "name": "Apple GPU", "vram_gb": round(ram_gb * 0.7, 1), "backend": "Metal",
                 "unified": True, "source": "fallback"}] if platform.machine() == "arm64" else []


def _linux_gpus(notes) -> list:
    gpus = []
    if not os.path.isdir("/sys/class/drm"):
        return gpus  # headless machine / container: nothing to report
    try:
        for card in sorted(os.listdir("/sys/class/drm")):
            dev = f"/sys/class/drm/{card}/device"
            if not re.fullmatch(r"card\d+", card) or not os.path.exists(f"{dev}/vendor"):
                continue
            vendor_id = open(f"{dev}/vendor").read().strip()
            vendor = {"0x1002": "AMD", "0x8086": "Intel", "0x10de": "NVIDIA"}.get(vendor_id, vendor_id)
            if vendor == "NVIDIA":
                continue  # covered by the NVIDIA probe
            vram = None
            if os.path.exists(f"{dev}/mem_info_vram_total"):
                vram = round(int(open(f"{dev}/mem_info_vram_total").read()) / 2**30, 1)
            gpus.append({"vendor": vendor, "name": f"{vendor} GPU ({card})", "vram_gb": vram, "backend": "Vulkan",
                         "source": "sysfs", "integrated": vendor == "Intel"})
    except Exception as e:
        notes.append(f"Couldn't list GPUs from /sys ({type(e).__name__}).")
    return gpus


def scan() -> dict:
    notes = []
    cpu = _cpu(notes)
    ram = _ram()
    gpus = _nvidia_gpus(notes)
    if IS_WIN:
        names = {g["name"] for g in gpus}
        gpus += [g for g in _windows_gpus(notes) if g["vendor"] != "NVIDIA" or g["name"] not in names]
        # The registry also lists NVIDIA cards; keep them only if NVML/nvidia-smi was unavailable.
        if any(g["source"] in ("NVML", "nvidia-smi") for g in gpus):
            gpus = [g for g in gpus if not (g["vendor"] == "NVIDIA" and g["source"] == "registry")]
    elif IS_MAC:
        gpus += _mac_gpus(notes, ram["total_gb"])
    else:
        gpus += _linux_gpus(notes)
    try:
        disk = shutil.disk_usage(APP_ROOT)
        disk_info = {"free_gb": round(disk.free / 2**30, 1), "total_gb": round(disk.total / 2**30, 1)}
    except Exception:
        disk_info = None
        notes.append("Couldn't check free disk space.")
    info = {
        "os": {"name": {"win32": "Windows", "darwin": "macOS"}.get(sys.platform, "Linux"),
               "version": platform.release() if not IS_MAC else platform.mac_ver()[0]},
        "cpu": cpu, "ram": ram, "gpus": gpus, "disk": disk_info, "notes": notes,
    }
    info["recommendation"] = recommend(info)
    return info


# ---------------------------------------------------------------------------- recommendations

def best_gpu(info: dict) -> Optional[dict]:
    usable = [g for g in info["gpus"] if g.get("vram_gb") and not g.get("integrated")]
    if not usable:
        return None
    rank = {"NVIDIA": 3, "Apple": 3, "AMD": 2, "Intel": 1}
    return max(usable, key=lambda g: (rank.get(g["vendor"], 0), g["vram_gb"]))


def model_fit(size_gb: Optional[float], gpu_mem: float, ram_gb: float) -> dict:
    """How a model of `size_gb` will run: fully on GPU, split with the CPU, CPU only, or not at all."""
    if not size_gb:
        return {"level": "unknown", "label": "Size unknown"}
    need = size_gb + LLM_OVERHEAD_GB
    if gpu_mem >= need:
        return {"level": "great", "label": "Runs fully on your GPU (fast)", "need_gb": round(need, 1)}
    spill = need - gpu_mem
    if gpu_mem >= 4 and ram_gb - 6 >= spill:
        pct = int(min(gpu_mem / need, 1) * 100)
        return {"level": "ok", "label": f"About {pct}% on GPU, rest on CPU (slower replies)", "need_gb": round(need, 1)}
    if ram_gb - 6 >= need:
        return {"level": "slow", "label": "CPU only (slow)", "need_gb": round(need, 1)}
    return {"level": "no", "label": "Too large for this computer's memory", "need_gb": round(need, 1)}


def recommend(info: dict, catalog: Optional[list] = None) -> dict:
    ram = info["ram"]["total_gb"]
    gpu = best_gpu(info)
    gpu_mem = gpu["vram_gb"] if gpu else 0.0
    nvidia = bool(gpu and gpu["vendor"] == "NVIDIA")
    apple = bool(gpu and gpu.get("unified"))
    reasons = []

    if gpu_mem >= 15:
        llm, ctx = "Qwen3.8-27B-abliterated-IQ3_S", 8192
        reasons.append(f"{gpu['name']} has {gpu_mem:g} GB, enough to run Qwen3.8 27B entirely on the GPU.")
    elif gpu_mem >= 9:
        llm, ctx = "Gemma-4-12B-it-Q4", 8192
        reasons.append(f"{gpu['name']} has {gpu_mem:g} GB: Gemma 4 12B fits fully for quick replies. "
                       "Qwen3.8 27B would also work but part of it would run on the CPU.")
    elif gpu_mem >= 6:
        llm, ctx = ("Gemma-4-12B-it-Q4", 4096) if ram >= 16 else ("Aya-7b-gguf", 4096)
        reasons.append(f"{gpu['name']} has {gpu_mem:g} GB: "
                       + ("Gemma 4 12B runs partly on the CPU; a 7B model is faster if replies feel slow."
                          if ram >= 16 else "a 7B model fits fully on the GPU."))
    else:
        llm, ctx = "Aya-7b-gguf", 4096
        reasons.append("No GPU with enough memory was found, so a small 7B model is suggested. For better "
                       "conversation, connect LM Studio on a stronger PC or an online API on the Brain page.")
    if ram < 16:
        reasons.append(f"Only {ram:g} GB of system RAM: close other programs while streaming.")

    llm_need = {"Qwen3.8-27B-abliterated-IQ3_S": 13.5, "Gemma-4-12B-it-Q4": 9.0}.get(llm, 6.0)
    spare = gpu_mem - llm_need
    if (nvidia or apple) and spare >= VOICE_VRAM_GB["chatterbox"]:
        voice = "chatterbox"
        reasons.append("There is room left on the GPU for Chatterbox Turbo, the most natural English voice.")
    elif nvidia or apple:
        voice = "luxtts"
        reasons.append("The model uses most of the GPU, so LuxTTS (about 1 GB) keeps the voice fast. "
                       "Chatterbox Turbo also works if you pick a smaller brain.")
    else:
        voice = "luxtts"
        reasons.append("Voice engines need an NVIDIA or Apple GPU for speed; LuxTTS is the one that runs well on the CPU.")

    fits = {}
    for m in catalog or []:
        fits[m["id"]] = model_fit(m.get("size_gb"), gpu_mem, ram)
    voice_fits = {}
    for eid, need in VOICE_VRAM_GB.items():
        if not (nvidia or apple):
            voice_fits[eid] = {"level": "great" if eid == "luxtts" else "slow",
                               "label": "Runs on the CPU" if eid == "luxtts" else "CPU only (slow)"}
        elif gpu_mem - llm_need >= need:
            voice_fits[eid] = {"level": "great", "label": "Fits next to the recommended brain"}
        elif gpu_mem >= need:
            voice_fits[eid] = {"level": "ok", "label": "Fits, but not alongside a large brain"}
        else:
            voice_fits[eid] = {"level": "no", "label": "Not enough GPU memory"}

    return {"llm": llm, "context_size": ctx, "voice": voice, "gpu_mem_gb": gpu_mem,
            "gpu": gpu["name"] if gpu else None, "reasons": reasons, "model_fits": fits, "voice_fits": voice_fits}
