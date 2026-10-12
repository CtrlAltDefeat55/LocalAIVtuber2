"""Used by the launcher during first-run setup (runs in the app's main Python environment).

  python tools/setup_assets.py engine chatterbox     install a voice engine
  python tools/setup_assets.py model <model_id>      download a language model and select it
  python tools/setup_assets.py models                list catalog models as JSON
  python tools/setup_assets.py hardware [--json]     scan this PC and recommend models
"""
import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.lib.paths import SETTINGS_FILE, configure_environment  # noqa: E402

configure_environment()


def set_setting(key, value):
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            settings = json.load(f)
    except (OSError, json.JSONDecodeError):
        settings = {}
    settings[key] = value
    tmp = str(SETTINGS_FILE) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=4, ensure_ascii=False)
    os.replace(tmp, SETTINGS_FILE)


def install_engine(engine_id: str) -> int:
    from services.TTS.engines import ENGINES, EngineManager
    if engine_id not in ENGINES:
        print(f"Unknown engine {engine_id}. Choices: {', '.join(ENGINES)}")
        return 2
    manager = EngineManager()
    if manager.is_installed(engine_id):
        print(f"{ENGINES[engine_id]['label']} is already installed.")
        return 0
    manager.state[engine_id] = "installing"
    shown = 0
    import threading
    t = threading.Thread(target=manager._install, args=(engine_id,))
    t.start()
    last_step = None
    while t.is_alive() or shown < len(manager.logs[engine_id]):
        logs = list(manager.logs[engine_id])
        step = manager.step.get(engine_id)
        if step and step != last_step:
            print(f"  -> {step}", flush=True)
            last_step = step
        for line in logs[shown:]:
            if line.startswith("$") or "Downloading" in line or "Installed" in line or "error" in line.lower():
                print(f"     {line[:160]}", flush=True)
        shown = len(logs)
        time.sleep(0.5)
    if manager.state.get(engine_id) == "error":
        print(f"Installing {engine_id} failed:\n{manager.errors.get(engine_id)}")
        return 1
    set_setting("tts.engine", engine_id)
    return 0


async def _download_model(model_id: str) -> int:
    from services.LLM.LLM import LLM
    from services.LLM.routes import resolve_files, start_download

    llm = LLM()
    model = llm.get_model(model_id)
    if not model:
        print(f"Unknown model {model_id}")
        return 2
    set_setting("llm.model_id", model["id"])
    if model["file_exists"]:
        print(f"{model['displayName']} is already downloaded.")
        return 0
    try:
        files, local = await resolve_files(model)
    except Exception as e:
        print(f"Could not find the model files on Hugging Face: {e}")
        return 1
    job = start_download(llm, model, files, local)
    while job.status in ("starting", "downloading"):
        d = job.to_dict()
        total = d["total_size"] or 1
        bar = int(30 * d["downloaded_size"] / total)
        speed = d["speed_bps"] / 1e6
        print(f"\r  [{'#' * bar}{'.' * (30 - bar)}] {d['progress']:5.1f}%  "
              f"{d['downloaded_size'] / 1e9:5.2f}/{total / 1e9:.2f} GB  {speed:6.1f} MB/s ", end="", flush=True)
        await asyncio.sleep(1)
    print()
    if job.status != "completed":
        print(f"Download failed: {job.error}. Run the start script again to resume.")
        return 1
    return 0


def hardware_report(as_json: bool) -> int:
    from services.LLM.LLM import LLM
    from services.lib import hardware
    info = hardware.scan()
    info["recommendation"] = hardware.recommend(info, LLM().all_model_data)
    if as_json:
        print("HARDWARE_JSON " + json.dumps(info))
        return 0
    rec = info["recommendation"]
    cpu, ram = info["cpu"], info["ram"]
    print(f"  CPU : {cpu['name']} ({cpu['cores']} cores / {cpu['threads']} threads)")
    print(f"  RAM : {ram['total_gb']:g} GB ({ram['available_gb']:g} GB free right now)")
    if info["gpus"]:
        for g in info["gpus"]:
            mem = f"{g['vram_gb']:g} GB" if g.get("vram_gb") else "memory unknown"
            print(f"  GPU : {g['name']} ({mem}{', shared with system RAM' if g.get('unified') else ''})")
    else:
        print("  GPU : none detected")
    if info.get("disk"):
        print(f"  Disk: {info['disk']['free_gb']:g} GB free in the app folder's drive")
    for note in info["notes"]:
        print(f"  [!] {note}")
    print("\n  Recommendation for this PC:")
    for reason in rec["reasons"]:
        print(f"   - {reason}")
    return 0


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    cmd = sys.argv[1]
    if cmd == "engine":
        return install_engine(sys.argv[2])
    if cmd == "model":
        return asyncio.run(_download_model(sys.argv[2]))
    if cmd == "hardware":
        return hardware_report("--json" in sys.argv)
    if cmd == "models":
        from services.LLM.LLM import LLM
        print(json.dumps([{k: m.get(k) for k in ("id", "displayName", "size_hint", "vram_hint", "file_exists")}
                          for m in LLM().all_model_data]))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
