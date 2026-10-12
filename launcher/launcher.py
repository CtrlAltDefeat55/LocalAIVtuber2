"""Local AI VTuber launcher: first-run setup, repair/update, and starting the app.

Started by "Start Windows.bat", "Start Mac.command" or "Start Linux.sh" through
the bundled `uv`, so it runs on a private Python without anything installed on
the computer. Uses only the standard library.

  (no options)     install anything missing, then open the app
  --update         also update the LLM runtime and Python packages
  --setup          re-run the hardware check and the model / voice choices
  --no-window      run the server without opening a window (e.g. for OBS only)

Everything is kept inside this folder (runtime/, cache/), so the folder can be
moved or renamed; nothing is written to system locations except the optional
desktop/start-menu shortcuts.
"""
import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import signal
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
import webbrowser
import zipfile
from pathlib import Path

APP_NAME = "Local AI VTuber"
ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
RUNTIME = ROOT / "runtime"
CACHE = ROOT / "cache"
MAIN_ENV = RUNTIME / "envs" / "main"
LLAMA_DIR = RUNTIME / "llama"
STATE_FILE = RUNTIME / "setup-state.json"
ICON_DIR = ROOT / "launcher"
PORT = int(os.environ.get("LAV_PORT", "8000"))
URL = f"http://127.0.0.1:{PORT}"
IS_WIN, IS_MAC = sys.platform == "win32", sys.platform == "darwin"
PY_VERSION = "3.11"
START_SCRIPTS = {"win32": "Start Windows.bat", "darwin": "Start Mac.command", "linux": "Start Linux.sh"}
MY_SCRIPT = START_SCRIPTS["win32" if IS_WIN else "darwin" if IS_MAC else "linux"]
OTHER_SCRIPTS_DIR = ROOT / "Other start scripts"

os.environ.setdefault("UV_PYTHON_INSTALL_DIR", str(RUNTIME / "python"))
os.environ.setdefault("UV_CACHE_DIR", str(CACHE / "uv"))
os.environ.setdefault("HF_HOME", str(CACHE / "huggingface"))
os.environ["UV_NO_MODIFY_PATH"] = "1"
os.environ["UV_PYTHON_PREFERENCE"] = "only-managed"  # private Python in runtime/python, never the system one


# ---------------------------------------------------------------------------- console helpers

def say(msg=""):
    print(msg, flush=True)


def step(msg):
    say(f"\n==> {msg}")


def fail(msg):
    say(f"\n[!] {msg}")
    say("    Fix the problem above and run the start script again; finished steps are skipped.")
    if IS_WIN:
        input("\nPress Enter to close...")
    sys.exit(1)


def ask(question, options, default):
    """Numbered choice with a default (Enter). Non-interactive runs take the default."""
    if not sys.stdin or not sys.stdin.isatty():
        return default
    say(question)
    for i, (key, label) in enumerate(options, 1):
        mark = "  (recommended)" if key == default else ""
        say(f"  {i}. {label}{mark}")
    while True:
        try:
            ans = input(f"Choose 1-{len(options)} [Enter = recommended]: ").strip()
        except EOFError:
            return default
        if not ans:
            return default
        if ans.isdigit() and 1 <= int(ans) <= len(options):
            return options[int(ans) - 1][0]


def load_state():
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def run(cmd, **kw):
    say("    $ " + " ".join(str(c) for c in cmd[:5]) + (" ..." if len(cmd) > 5 else ""))
    proc = subprocess.run([str(c) for c in cmd], **kw)
    if proc.returncode != 0:
        fail(f"Command failed with exit code {proc.returncode}: {cmd[0]}")
    return proc


def download(url, dest: Path, label=None):
    """Download with a simple progress line; resumes via .part files."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    have = part.stat().st_size if part.exists() else 0
    req = urllib.request.Request(url, headers={"User-Agent": "LocalAIVtuber-launcher"})
    if have:
        req.add_header("Range", f"bytes={have}-")
    try:
        resp = urllib.request.urlopen(req, timeout=60)
    except urllib.error.HTTPError as e:
        if e.code == 416:
            part.replace(dest)
            return dest
        raise
    with resp:
        if resp.status == 200:
            have = 0
        total = have + int(resp.headers.get("Content-Length") or 0)
        with open(part, "ab" if have else "wb") as f:
            last = 0
            while True:
                chunk = resp.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                have += len(chunk)
                if time.time() - last > 0.5:
                    pct = f"{have * 100 / total:5.1f}%" if total else ""
                    print(f"\r    {label or dest.name}: {have / 1e6:8.1f} MB {pct}", end="", flush=True)
                    last = time.time()
    print()
    part.replace(dest)
    return dest


def extract(archive: Path, target: Path):
    """Extract zip/tar.gz, flattening a single top-level folder."""
    tmp = Path(tempfile.mkdtemp(dir=target.parent))
    try:
        if archive.name.endswith(".zip"):
            with zipfile.ZipFile(archive) as z:
                z.extractall(tmp)
        else:
            with tarfile.open(archive) as t:
                t.extractall(tmp, filter="data") if hasattr(tarfile, "data_filter") else t.extractall(tmp)
        entries = list(tmp.iterdir())
        src = entries[0] if len(entries) == 1 and entries[0].is_dir() else tmp
        target.mkdir(parents=True, exist_ok=True)
        for item in src.iterdir():
            dest = target / item.name
            if dest.exists():
                shutil.rmtree(dest) if dest.is_dir() else dest.unlink()
            shutil.move(str(item), dest)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------- hardware

def detect_gpu():
    info = {"kind": "cpu", "name": None, "vram_gb": 0, "driver": 0.0, "compute": 0.0}
    if IS_MAC:
        info["kind"] = "metal" if platform.machine() == "arm64" else "cpu"
        try:
            mem = int(subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True).stdout.strip())
            info["vram_gb"] = round(mem / 2**30 * 0.7)  # unified memory usable by the GPU
        except Exception:
            pass
        return info
    smi = shutil.which("nvidia-smi")
    if smi:
        try:
            out = subprocess.run([smi, "--query-gpu=name,memory.total,driver_version,compute_cap",
                                  "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=15).stdout
            name, mem, driver, cap = [x.strip() for x in out.strip().splitlines()[0].split(",")[:4]]
            info.update(kind="cuda", name=name, vram_gb=round(int(float(mem)) / 1024),
                        driver=float(driver.split(".")[0] + "." + driver.split(".")[1]), compute=float(cap))
            return info
        except Exception:
            pass
    if IS_WIN:
        info["kind"] = "vulkan"  # AMD / Intel GPUs: llama.cpp runs on Vulkan; voice engines use the CPU
    elif shutil.which("vulkaninfo"):
        info["kind"] = "vulkan"
    return info


def torch_index(gpu):
    if gpu["kind"] == "cuda":
        return "https://download.pytorch.org/whl/" + ("cu128" if gpu["compute"] >= 7.5 else "cu126")
    if IS_MAC:
        return None  # PyPI wheels include Metal (MPS)
    return "https://download.pytorch.org/whl/cpu"


# ---------------------------------------------------------------------------- setup steps

def uv_bin():
    for name in ("uv.exe", "uv"):
        p = RUNTIME / "uv" / name
        if p.exists():
            return str(p)
    found = shutil.which("uv")
    if not found:
        fail(f"The uv tool is missing. Start the app with “{MY_SCRIPT}”.")
    return found


def env_python(env: Path) -> Path:
    return env / ("Scripts/python.exe" if IS_WIN else "bin/python")


def requirements_hash():
    return hashlib.sha256((BACKEND / "requirements.txt").read_bytes()).hexdigest()[:16]


def setup_main_env(state, gpu, update):
    py = env_python(MAIN_ENV)
    want = {"reqs": requirements_hash(), "torch": torch_index(gpu) or "pypi"}
    if py.exists() and state.get("main_env") == want and not update:
        return
    uv = uv_bin()
    step("Setting up the app's Python environment (first run downloads ~3 GB, later runs skip this)")
    run([uv, "venv", "--allow-existing", "--relocatable", "--python", PY_VERSION, MAIN_ENV])
    torch_cmd = [uv, "pip", "install", "--python", py, "torch==2.8.0", "torchvision==0.23.0", "torchaudio==2.8.0"]
    if torch_index(gpu):
        torch_cmd += ["--index-url", torch_index(gpu)]
    run(torch_cmd)
    run([uv, "pip", "install", "--python", py, "-r", BACKEND / "requirements.txt",
         "--override", write_override(["torch==2.8.0", "torchvision==0.23.0", "torchaudio==2.8.0"])]
        + (["--extra-index-url", torch_index(gpu), "--index-strategy", "unsafe-best-match"] if torch_index(gpu) else [])
        + (["--upgrade"] if update else []))
    state["main_env"] = want
    save_state(state)


def write_override(lines):
    path = RUNTIME / "overrides.txt"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def llama_asset_patterns(gpu):
    """Regexes for the llama.cpp release assets that match this computer, best first."""
    if IS_WIN:
        if gpu["kind"] == "cuda":
            cuda = r"13\.\d+" if gpu["driver"] >= 580 else r"12\.\d+"
            return [rf"llama-.*-bin-win-cuda-{cuda}-x64\.zip$", r"llama-.*-bin-win-vulkan-x64\.zip$",
                    r"llama-.*-bin-win-cpu-x64\.zip$"], rf"cudart-llama-bin-win-cuda-{cuda}-x64\.zip$"
        return [r"llama-.*-bin-win-vulkan-x64\.zip$", r"llama-.*-bin-win-cpu-x64\.zip$"], None
    if IS_MAC:
        arch = "arm64" if platform.machine() == "arm64" else "x64"
        return [rf"llama-.*-bin-macos-{arch}\.(zip|tar\.gz)$"], None
    if gpu["kind"] == "cuda":
        return [r"llama-.*-bin-ubuntu-cuda-12\.\d+-x64\.tar\.gz$", r"llama-.*-bin-ubuntu-vulkan-x64\.tar\.gz$",
                r"llama-.*-bin-ubuntu-x64\.tar\.gz$"], r"cudart-llama-.*-bin-ubuntu-cuda-12\.\d+-x64\.tar\.gz$"
    if gpu["kind"] == "vulkan":
        return [r"llama-.*-bin-ubuntu-vulkan-x64\.tar\.gz$", r"llama-.*-bin-ubuntu-x64\.tar\.gz$"], None
    return [r"llama-.*-bin-ubuntu-x64\.tar\.gz$"], None


def setup_llama(state, gpu, update):
    exe = "llama-server.exe" if IS_WIN else "llama-server"
    installed = LLAMA_DIR.exists() and any(LLAMA_DIR.rglob(exe))
    if installed and not update:
        return
    step("Downloading the LLM runtime (llama.cpp) for your hardware")
    try:
        req = urllib.request.Request("https://api.github.com/repos/ggml-org/llama.cpp/releases/latest",
                                     headers={"User-Agent": "LocalAIVtuber-launcher", "Accept": "application/vnd.github+json"})
        release = json.load(urllib.request.urlopen(req, timeout=60))
    except Exception as e:
        if installed:
            say(f"    Could not check for updates ({e}); keeping the installed runtime.")
            return
        fail(f"Could not reach GitHub to download llama.cpp: {e}")
    if installed and release["tag_name"] == state.get("llama_tag"):
        say(f"    Already up to date ({release['tag_name']}).")
        return
    names = {a["name"]: a["browser_download_url"] for a in release["assets"]}
    patterns, cudart = llama_asset_patterns(gpu)
    asset = next((n for p in patterns for n in names if re.search(p, n)), None)
    if not asset:
        fail(f"No llama.cpp build found for this system in release {release['tag_name']}.")
    say(f"    Release {release['tag_name']}: {asset}")
    tmp = CACHE / "downloads"
    if LLAMA_DIR.exists():
        shutil.rmtree(LLAMA_DIR)
    extract(download(names[asset], tmp / asset), LLAMA_DIR)
    if cudart and "cuda" in asset:
        extra = next((n for n in names if re.search(cudart, n)), None)
        if extra:
            extract(download(names[extra], tmp / extra), LLAMA_DIR)
    shutil.rmtree(tmp, ignore_errors=True)
    if not IS_WIN:
        for f in LLAMA_DIR.rglob("*"):
            if f.is_file() and (f.name.startswith("llama-") or f.suffix in (".so", ".dylib")):
                f.chmod(f.stat().st_mode | 0o755)
    state["llama_tag"] = release["tag_name"]
    state["llama_asset"] = asset
    save_state(state)


def relocate_envs(state):
    """After the folder was moved/renamed, point each environment at the bundled Python again.

    Only the `home`/`base-*` lines of runtime/envs/*/pyvenv.cfg are rewritten, and only when
    they point into the previous app folder. Everything else in a relocatable env is relative.
    """
    old = state.get("root")
    if not old or old == str(ROOT):
        state["root"] = str(ROOT)
        save_state(state)
        return
    step(f"App folder moved from {old} - updating internal paths")
    for cfg in (RUNTIME / "envs").glob("*/pyvenv.cfg"):
        lines = cfg.read_text(encoding="utf-8").splitlines()
        fixed = []
        for line in lines:
            key, sep, value = line.partition("=")
            value = value.strip()
            if sep and key.strip() in ("home", "base-prefix", "base-exec-prefix", "base-executable") and value.startswith(old):
                line = f"{key.strip()} = {str(ROOT) + value[len(old):]}"
            fixed.append(line)
        cfg.write_text("\n".join(fixed) + "\n", encoding="utf-8")
        say(f"    updated {cfg.parent.name}")
    state["root"] = str(ROOT)
    state.pop("shortcuts_for", None)  # re-point the desktop shortcut at the new folder
    save_state(state)


def setup_frontend():
    if (ROOT / "frontend" / "dist" / "index.html").exists():
        return
    step("Building the user interface (only needed for source checkouts)")
    npm = shutil.which("npm")
    if not npm:
        fail("frontend/dist is missing and Node.js is not installed. Use the release zip, or install "
             "Node.js 20+ from nodejs.org and run the start script again.")
    run([npm, "ci"], cwd=ROOT / "frontend", shell=IS_WIN)
    run([npm, "run", "build"], cwd=ROOT / "frontend", shell=IS_WIN)


def backend_tool(*args):
    return subprocess.run([str(env_python(MAIN_ENV)), str(BACKEND / "tools" / "setup_assets.py"), *args],
                          cwd=str(BACKEND)).returncode


def hardware_scan():
    """Full scan from the app environment (CPU, RAM, every GPU, blocked probes)."""
    try:
        out = subprocess.run([str(env_python(MAIN_ENV)), str(BACKEND / "tools" / "setup_assets.py"), "hardware", "--json"],
                             cwd=str(BACKEND), capture_output=True, text=True, timeout=120)
        line = next((l for l in out.stdout.splitlines() if l.startswith("HARDWARE_JSON ")), None)
        return json.loads(line[len("HARDWARE_JSON "):]) if line else None
    except Exception as e:
        say(f"    (Hardware scan failed: {e})")
        return None


def print_hardware(info):
    cpu, ram = info["cpu"], info["ram"]
    say(f"    CPU : {cpu['name']} ({cpu['cores']} cores / {cpu['threads']} threads)")
    say(f"    RAM : {ram['total_gb']:g} GB")
    for g in info["gpus"] or [{"name": "none detected"}]:
        mem = f" ({g['vram_gb']:g} GB{' shared' if g.get('unified') else ''})" if g.get("vram_gb") else ""
        say(f"    GPU : {g['name']}{mem}")
    if info.get("disk"):
        say(f"    Disk: {info['disk']['free_gb']:g} GB free")
    for note in info["notes"]:
        say(f"    [!] {note}")
    if info["notes"]:
        say("    Some details could not be read (see above); the recommendation uses what was found.")


def choose_assets(state, gpu, force):
    if state.get("assets_chosen") and not force:
        return
    step("Checking your computer")
    info = hardware_scan()
    if info:
        print_hardware(info)
        rec = info["recommendation"]
        default_llm, default_voice = rec["llm"], rec["voice"]
        say("\n    Recommendation:")
        for reason in rec["reasons"]:
            say(f"     - {reason}")
        fits = rec.get("model_fits", {})
        vfits = rec.get("voice_fits", {})
    else:
        say("    The detailed scan didn't run; using basic GPU detection instead.")
        vram = gpu["vram_gb"]
        default_llm = "Qwen3.8-27B-abliterated-IQ3_S" if vram >= 15 else "Gemma-4-12B-it-Q4" if vram >= 6 else "Aya-7b-gguf"
        default_voice = "chatterbox" if gpu["kind"] in ("cuda", "metal") else "luxtts"
        fits, vfits = {}, {}

    def fit(mid, table):
        return f"  [{table[mid]['label']}]" if mid in table else ""

    llm = ask("\nWhich brain (language model) should be downloaded now?", [
        ("Qwen3.8-27B-abliterated-IQ3_S", "Qwen3.8 27B Abliterated IQ3_S - best conversation, ~12 GB" + fit("Qwen3.8-27B-abliterated-IQ3_S", fits)),
        ("Gemma-4-12B-it-Q4", "Gemma 4 12B Q4 - quicker on mid-range GPUs, ~7.5 GB" + fit("Gemma-4-12B-it-Q4", fits)),
        ("Aya-7b-gguf", "Aya 7B - small and light, ~4.4 GB" + fit("Aya-7b-gguf", fits)),
        ("api", "None - I'll connect LM Studio / Ollama / an online API in the app (Brain page)"),
        ("skip", "Skip for now"),
    ], default_llm)
    voice = ask("\nWhich voice engine should be installed now?", [
        ("chatterbox", "Chatterbox Turbo - natural, low latency (English)" + fit("chatterbox", vfits)),
        ("luxtts", "LuxTTS - fastest, tiny, works on CPU (English)" + fit("luxtts", vfits)),
        ("omnivoice", "OmniVoice - 600+ languages" + fit("omnivoice", vfits)),
        ("api", "None - I'll connect Voicebox / ElevenLabs / another API in the app (Voice page)"),
        ("skip", "Skip for now"),
    ], default_voice)
    state["assets"] = {"llm": llm, "voice": voice}
    state["assets_chosen"] = True
    save_state(state)


def install_assets(state):
    assets = state.get("assets", {})
    if assets.get("voice") not in (None, "skip", "api") and not state.get("voice_done"):
        step(f"Installing the voice engine ({assets['voice']}) - several minutes, downloads a few GB")
        if backend_tool("engine", assets["voice"]) == 0:
            state["voice_done"] = True
            save_state(state)
        else:
            say("    Voice engine install failed; you can retry from the Voice page.")
    if assets.get("llm") not in (None, "skip", "api") and not state.get("llm_done"):
        step("Downloading the language model (resumes if interrupted)")
        if backend_tool("model", assets["llm"]) == 0:
            state["llm_done"] = True
            save_state(state)
        else:
            say("    Model download did not finish; it resumes next start, or use the Brain page.")


# ---------------------------------------------------------------------------- shortcuts

def tidy_start_scripts():
    """Keep only this computer's start script in the app folder; park the others in a subfolder
    so nobody double-clicks the wrong one. Nothing is deleted - they still work from there."""
    moved = []
    for name in START_SCRIPTS.values():
        src = ROOT / name
        if name == MY_SCRIPT or not src.exists():
            continue
        OTHER_SCRIPTS_DIR.mkdir(exist_ok=True)
        dest = OTHER_SCRIPTS_DIR / name
        try:
            if dest.exists():
                dest.unlink()
            shutil.move(str(src), dest)
            moved.append(name)
        except OSError as e:
            say(f"    (Couldn't move {name}: {e})")
    # an old single "start.*" launcher from earlier versions would also be confusing
    for legacy in ("start.bat", "start.sh", "start.command"):
        if (ROOT / legacy).exists() and (ROOT / "launcher" / "launcher.py").exists():
            OTHER_SCRIPTS_DIR.mkdir(exist_ok=True)
            try:
                shutil.move(str(ROOT / legacy), OTHER_SCRIPTS_DIR / legacy)
                moved.append(legacy)
            except OSError:
                pass
    if moved:
        readme = OTHER_SCRIPTS_DIR / "README.txt"
        readme.write_text("These start scripts are for other operating systems. They were moved here so the "
                          f"app folder only shows “{MY_SCRIPT}”.\nIf you copy this folder to another kind of "
                          "computer, run the matching script from here.\n", encoding="utf-8")
        say(f"    Tidied up: moved {', '.join(moved)} into “{OTHER_SCRIPTS_DIR.name}”.")


def create_shortcuts(state):
    """Desktop + Start-menu/Applications entry with the app icon. Re-created if the folder moved."""
    if state.get("shortcuts_for") == str(ROOT):
        return
    try:
        if IS_WIN:
            target = ROOT / MY_SCRIPT
            icon = ICON_DIR / "app-icon.ico"
            ps = (
                "$s=New-Object -ComObject WScript.Shell;"
                "foreach($d in @([Environment]::GetFolderPath('Desktop'),"
                "[Environment]::GetFolderPath('Programs'))){"
                f"$l=$s.CreateShortcut((Join-Path $d '{APP_NAME}.lnk'));"
                f"$l.TargetPath='{target}';$l.WorkingDirectory='{ROOT}';"
                f"$l.IconLocation='{icon},0';$l.WindowStyle=7;"
                "$l.Description='Local AI VTuber';$l.Save()}"
            )
            subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
                           capture_output=True, timeout=60)
        elif IS_MAC:
            app = ROOT / f"{APP_NAME}.app"
            macos = app / "Contents" / "MacOS"
            res = app / "Contents" / "Resources"
            macos.mkdir(parents=True, exist_ok=True)
            res.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ICON_DIR / "app-icon.icns", res / "app-icon.icns")
            launcher = macos / "LocalAIVtuber"
            # Finds its own folder at run time, so moving the app folder keeps it working.
            launcher.write_text('#!/bin/bash\nDIR="$(cd "$(dirname "$0")/../../.." && pwd)"\n'
                                f'open -a Terminal "$DIR/{MY_SCRIPT}"\n', encoding="utf-8")
            launcher.chmod(0o755)
            (app / "Contents" / "Info.plist").write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleName</key><string>{APP_NAME}</string>
<key>CFBundleDisplayName</key><string>{APP_NAME}</string>
<key>CFBundleIdentifier</key><string>io.localaivtuber.app</string>
<key>CFBundleExecutable</key><string>LocalAIVtuber</string>
<key>CFBundleIconFile</key><string>app-icon</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>LSMinimumSystemVersion</key><string>11.0</string>
</dict></plist>
""", encoding="utf-8")
            desktop = Path.home() / "Desktop" / f"{APP_NAME}.app"
            if desktop.is_symlink() or desktop.exists():
                desktop.unlink()
            desktop.symlink_to(app)
        else:
            entry = f"""[Desktop Entry]
Type=Application
Name={APP_NAME}
Comment=Local AI VTuber
Exec="{ROOT / MY_SCRIPT}"
Path={ROOT}
Icon={ICON_DIR / 'app-icon.png'}
Terminal=true
Categories=AudioVideo;
"""
            for d in (Path.home() / ".local/share/applications", Path.home() / "Desktop"):
                if d.exists():
                    f = d / "local-ai-vtuber.desktop"
                    f.write_text(entry, encoding="utf-8")
                    f.chmod(0o755)
        state["shortcuts_for"] = str(ROOT)
        save_state(state)
        say(f"    Shortcut “{APP_NAME}” added to your desktop.")
    except Exception as e:
        say(f"    (Could not create a desktop shortcut: {e})")


# ---------------------------------------------------------------------------- run

def server_alive():
    try:
        with urllib.request.urlopen(f"{URL}/api/system/status", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def port_busy():
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", PORT)) == 0


def find_app_browser():
    """A Chromium browser that supports --app windows (Edge ships with Windows)."""
    candidates = []
    if IS_WIN:
        for base in (os.environ.get("PROGRAMFILES(X86)"), os.environ.get("PROGRAMFILES"), os.environ.get("LOCALAPPDATA")):
            if base:
                candidates += [Path(base) / "Microsoft/Edge/Application/msedge.exe",
                               Path(base) / "Google/Chrome/Application/chrome.exe",
                               Path(base) / "BraveSoftware/Brave-Browser/Application/brave.exe"]
    elif IS_MAC:
        for app in ("Google Chrome", "Microsoft Edge", "Brave Browser", "Chromium"):
            candidates.append(Path(f"/Applications/{app}.app/Contents/MacOS/{app}"))
    else:
        for name in ("google-chrome", "chromium", "chromium-browser", "microsoft-edge", "brave-browser"):
            if shutil.which(name):
                candidates.append(Path(shutil.which(name)))
    return next((c for c in candidates if c.exists()), None)


def open_window():
    """Open the app in its own window. Returns the browser process when we own it."""
    browser = find_app_browser()
    if browser:
        profile = CACHE / "app-window"
        return subprocess.Popen([str(browser), f"--app={URL}", f"--user-data-dir={profile}",
                                 "--window-size=1440,900", "--no-first-run", "--no-default-browser-check",
                                 "--autoplay-policy=no-user-gesture-required"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    webbrowser.open(URL)
    return None


def start_app(no_window=False):
    if server_alive():
        say("The app is already running - opening its window.")
        if not no_window:
            open_window()
        return
    if port_busy():
        fail(f"Port {PORT} is used by another program. Close it, or set LAV_PORT to another port.")
    step("Starting Local AI VTuber")
    env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8", "LAV_PORT": str(PORT)}
    kwargs = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if IS_WIN else {"start_new_session": True}
    server = subprocess.Popen([str(env_python(MAIN_ENV)), str(BACKEND / "server.py")], cwd=str(BACKEND), env=env, **kwargs)

    def stop_server(*_):
        if server.poll() is None:
            try:
                urllib.request.urlopen(urllib.request.Request(f"{URL}/api/system/shutdown", method="POST"), timeout=3)
                server.wait(timeout=20)
            except Exception:
                server.terminate()
                try:
                    server.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    server.kill()

    signal.signal(signal.SIGINT, lambda *_: (stop_server(), sys.exit(0)))
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, lambda *_: (stop_server(), sys.exit(0)))

    for _ in range(240):
        if server.poll() is not None:
            fail("The app server stopped during startup. See the messages above.")
        if server_alive():
            break
        time.sleep(0.5)
    else:
        stop_server()
        fail("The app server did not start within 2 minutes.")

    say(f"\n    {APP_NAME} is running at {URL}")
    if no_window:
        say("    Press Ctrl+C to stop.")
        server.wait()
        return
    window = open_window()
    if window:
        try:  # lets the performance monitor show the window's own GPU/CPU use
            req = urllib.request.Request(f"{URL}/api/system/window", data=json.dumps({"pid": window.pid}).encode(),
                                         headers={"Content-Type": "application/json"}, method="POST")
            urllib.request.urlopen(req, timeout=3).close()
        except Exception:
            pass
        say("    Close the app window (or use Quit in the app) to stop everything.")
        while server.poll() is None and window.poll() is None:
            time.sleep(1)
        stop_server()  # window closed -> stop the model, voice and server
    else:
        say("    Opened in your browser. Use Quit in the app (or close this window) to stop everything.")
        server.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--update", action="store_true", help="update the LLM runtime and Python packages")
    parser.add_argument("--setup", action="store_true", help="choose the model and voice engine again")
    parser.add_argument("--no-window", action="store_true", help="do not open the app window")
    parser.add_argument("--install-only", action="store_true", help="set everything up but do not start")
    parser.add_argument("--started-by", default=None, help=argparse.SUPPRESS)
    args = parser.parse_args()

    say(f"{APP_NAME} - folder: {ROOT}")
    for d in (RUNTIME, CACHE):
        d.mkdir(parents=True, exist_ok=True)
    state = load_state()
    if args.setup:
        state.pop("voice_done", None)
        state.pop("llm_done", None)
    relocate_envs(state)
    tidy_start_scripts()
    gpu = detect_gpu()
    setup_frontend()
    setup_main_env(state, gpu, args.update)
    setup_llama(state, gpu, args.update)
    choose_assets(state, gpu, args.setup)
    install_assets(state)
    create_shortcuts(state)
    if not args.install_only:
        start_app(args.no_window)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
