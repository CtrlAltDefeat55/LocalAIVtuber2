"""Fast checks for logic that is easy to break silently. Run: python -m unittest discover backend/tests"""
import io
import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.lib.downloads import pick_gguf, pick_mmproj  # noqa: E402


def files(*names):
    return [{"path": n, "size": 1} for n in names]


class PickGGUF(unittest.TestCase):
    def test_huihui_iq3_s_skips_experimental_variants(self):
        listing = files(
            "Huihui-Qwen3.8-27B-abliterated-GSQ-RCO-IQ3_S.gguf",
            "Huihui-Qwen3.8-27B-abliterated-UD-IQ3_S.gguf",
            "Huihui-Qwen3.8-27B-abliterated-mtp-IQ3_S.gguf",
            "Huihui-Qwen3.8-27B-abliterated-Q4_K.gguf",
            "mmproj-model-bf16.gguf",
        )
        chosen = pick_gguf(listing, "IQ3_S", ["mtp", "swift", "gsq"])
        self.assertEqual([f["path"] for f in chosen], ["Huihui-Qwen3.8-27B-abliterated-UD-IQ3_S.gguf"])

    def test_quant_must_match_whole_token(self):
        listing = files("m-Q4_K_M.gguf", "m-Q4_K_S.gguf")
        self.assertEqual(pick_gguf(listing, "Q4_K"), [])
        self.assertEqual(pick_gguf(listing, "q4_k_m")[0]["path"], "m-Q4_K_M.gguf")
        self.assertEqual(pick_gguf(listing, "IQ3_XS"), [])

    def test_split_models_return_all_parts_in_order(self):
        listing = files("Q8_0/m-Q8_0-00002-of-00002.gguf", "Q8_0/m-Q8_0-00001-of-00002.gguf", "m-Q4_K_M.gguf")
        chosen = [f["path"] for f in pick_gguf(listing, "Q8_0")]
        self.assertEqual(chosen, ["Q8_0/m-Q8_0-00001-of-00002.gguf", "Q8_0/m-Q8_0-00002-of-00002.gguf"])

    def test_mmproj_prefers_f16(self):
        listing = files("mmproj-BF16.gguf", "mmproj-F16.gguf", "model.gguf")
        self.assertEqual(pick_mmproj(listing)["path"], "mmproj-F16.gguf")
        self.assertIsNone(pick_mmproj(files("model.gguf")))


class Speakable(unittest.TestCase):
    def test_strips_actions_markdown_and_emoji(self):
        from services.TTS.TTS import speakable
        self.assertEqual(speakable("*waves* Hello **chat**! 😀✨"), "Hello chat!")
        self.assertEqual(speakable("2 * 3 = 6"), "2 3 = 6")
        self.assertEqual(speakable("😀"), "")
        self.assertEqual(speakable("I *really* mean it"), "I mean it")


def wav_bytes(seconds=1.0, sr=16000):
    import numpy as np
    import soundfile as sf
    buf = io.BytesIO()
    sf.write(buf, np.zeros(int(seconds * sr), dtype="float32"), sr, format="WAV")
    return buf.getvalue()


class VoiceLibraryTests(unittest.TestCase):
    def setUp(self):
        from services.TTS.voice_library import VoiceLibrary
        self.tmp = tempfile.TemporaryDirectory()
        self.lib = VoiceLibrary(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_add_replace_delete(self):
        v = self.lib.save("Aya", wav_bytes(6), "hello", "en")
        self.assertAlmostEqual(v["duration"], 6.0, places=1)
        with self.assertRaises(FileExistsError):
            self.lib.save("Aya", wav_bytes(), "x", "en")
        v = self.lib.save("Aya", None, "new words", "ja", replace=True)  # edit text only, keep audio
        self.assertEqual((v["reference_text"], v["language"], round(v["duration"])), ("new words", "ja", 6))
        self.assertTrue(self.lib.delete("Aya"))
        self.assertEqual(self.lib.list(), [])

    def test_rejects_unsafe_names_and_bad_audio(self):
        for name in ("../evil", "a/b", "", "x" * 61):
            with self.assertRaises(ValueError):
                self.lib.save(name, wav_bytes(), "", "en")
        with self.assertRaises(ValueError):
            self.lib.save("Bad", b"not audio at all", "", "en")
        self.assertFalse((Path(self.tmp.name) / "Bad" / "reference.wav").exists())


class CharacterUploads(unittest.TestCase):
    def setUp(self):
        from services.Character.characterManager import CharacterManager
        self.tmp = tempfile.TemporaryDirectory()
        self.cm = CharacterManager()
        self.cm.base_path = Path(self.tmp.name)
        self.cm.live2d_path = self.cm.base_path / "live2D" / "models"
        self.cm.vrm_path = self.cm.base_path / "VRM3D" / "models"
        self.cm.live2d_path.mkdir(parents=True)
        self.cm.vrm_path.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def make_zip(self, entries):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            for name, data in entries.items():
                z.writestr(name, data)
        return buf.getvalue()

    def test_zip_install_finds_nested_model_and_reports_missing_textures(self):
        model = json.dumps({"FileReferences": {"Moc": "m.moc3", "Textures": ["tex/t0.png", "tex/t1.png"]}})
        data = self.make_zip({"Export/Hiyori/hiyori.model3.json": model, "Export/Hiyori/m.moc3": b"x",
                              "Export/Hiyori/tex/t0.png": b"png", "__MACOSX/junk": b""})
        ok, msg = self.cm.upload_live2d_zip(data, "hiyori.zip")
        self.assertTrue(ok, msg)
        models = self.cm.get_live2d_models()
        self.assertEqual(models[0]["name"], "Hiyori")
        self.assertEqual(models[0]["missing"], ["tex/t1.png"])
        ok, msg = self.cm.upload_live2d_zip(data, "hiyori.zip")
        self.assertFalse(ok)  # no silent overwrite
        ok, msg = self.cm.upload_live2d_zip(data, "other.zip", replace=True, target_name="Hiyori")
        self.assertTrue(ok, msg)

    def test_zip_path_traversal_is_rejected(self):
        data = self.make_zip({"m/x.model3.json": "{}", "m/../../../escape.txt": b"bad"})
        ok, _ = self.cm.upload_live2d_zip(data, "m.zip")
        self.assertFalse(ok)
        self.assertFalse((Path(self.tmp.name).parent / "escape.txt").exists())
        self.assertEqual(self.cm.get_live2d_models(), [])

    def test_vrm_requires_gltf_and_replace_flag(self):
        self.assertFalse(self.cm.upload_vrm_model(b"nope", "a.vrm")[0])
        self.assertTrue(self.cm.upload_vrm_model(b"glTF....", "a.vrm")[0])
        self.assertFalse(self.cm.upload_vrm_model(b"glTF....", "a.vrm")[0])
        self.assertTrue(self.cm.upload_vrm_model(b"glTF2...", "a.vrm", replace=True)[0])


class ModelCatalog(unittest.TestCase):
    def test_local_json_and_loose_gguf(self):
        from services.LLM.LLM import LLM
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Qwen").mkdir()
            (root / "Qwen" / "metadata.json").write_text(json.dumps({"displayName": "Qwen", "repo": "a/b", "quant": "IQ3_S"}))
            (root / "Qwen" / "local.json").write_text(json.dumps({"fileName": "q.gguf", "mmproj_path": "mmproj.gguf"}))
            (root / "Qwen" / "q.gguf").write_bytes(b"0" * 10)
            (root / "loose").mkdir()
            (root / "loose" / "My-Model.Q4_K_M.gguf").write_bytes(b"0")
            (root / "loose" / "My-Model-00002-of-00002.gguf").write_bytes(b"0")
            llm = LLM.__new__(LLM)
            llm.models_directory = str(root)
            llm.current_model_data = None
            llm._load_available_models()
            by_id = {m["id"]: m for m in llm.all_model_data}
            self.assertTrue(by_id["Qwen"]["file_exists"])
            self.assertFalse(by_id["Qwen"]["mmproj_exists"])
            self.assertIn("file:loose/My-Model.Q4_K_M.gguf", by_id)
            self.assertEqual(len(by_id), 2)  # split part 2 is not listed separately
            self.assertTrue(llm.current_model_data["file_exists"])  # defaults to a downloaded model


if __name__ == "__main__":
    unittest.main()


class SidecarProtocol(unittest.TestCase):
    def test_synthesize_returns_wav_and_caches_voice(self):
        import importlib.util
        import threading
        import urllib.request
        from http.server import ThreadingHTTPServer
        import numpy as np
        import soundfile as sf

        spec = importlib.util.spec_from_file_location("sidecar", Path(__file__).resolve().parents[1] / "engines" / "tts_sidecar.py")
        sidecar = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sidecar)

        class Fake(sidecar.Engine):
            sample_rate = 22050
            encodes = 0

            def encode_voice(self, voice):
                Fake.encodes += 1
                return voice["reference_text"]

            def synthesize(self, text, voice, options):
                self.prepare_voice(voice)
                return np.full(2205, 0.5, dtype=np.float32)

        with tempfile.TemporaryDirectory() as tmp:
            ref = Path(tmp) / "ref.wav"
            ref.write_bytes(wav_bytes())
            server = ThreadingHTTPServer(("127.0.0.1", 0), sidecar.make_handler(Fake("cpu", None), "fake", threading.Lock()))
            threading.Thread(target=server.serve_forever, daemon=True).start()
            url = f"http://127.0.0.1:{server.server_address[1]}"
            body = json.dumps({"text": "hi", "voice": {"audio_path": str(ref), "reference_text": "r"}}).encode()
            for _ in range(2):
                req = urllib.request.Request(url + "/synthesize", data=body, headers={"Content-Type": "application/json"})
                audio, sr = sf.read(io.BytesIO(urllib.request.urlopen(req).read()))
            server.shutdown()
            self.assertEqual((sr, len(audio)), (22050, 2205))
            self.assertEqual(Fake.encodes, 1)  # reference encoded once, reused for the next line


@unittest.skipIf(sys.platform == "win32", "uses an executable Python script as a fake binary")
class LLMServerLifecycle(unittest.TestCase):
    def test_load_stream_continue_unload(self):
        import asyncio
        from services.LLM.LLM import LLM
        from services.lib.process_manager import process_manager

        fake = Path(__file__).resolve().parent / "fake_llama_server.py"
        os.environ["LAV_LLAMA_SERVER"] = str(fake)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                (Path(tmp) / "m").mkdir()
                (Path(tmp) / "m" / "metadata.json").write_text(json.dumps({"displayName": "M", "fileName": "m.gguf"}))
                (Path(tmp) / "m" / "m.gguf").write_bytes(b"0")
                from services.LLM import LLM as llm_module
                original = llm_module.LLM_MODELS_DIR
                llm_module.LLM_MODELS_DIR = Path(tmp)
                try:
                    llm = LLM()
                finally:
                    llm_module.LLM_MODELS_DIR = original
                self.assertEqual(llm.status()["state"], "stopped")

                async def collect(gen):
                    return "".join([c async for c in gen])

                reply = asyncio.run(collect(llm.get_completion("hi", [], "sys")))
                self.assertEqual(reply, "Hello there!")  # <think> block hidden
                self.assertEqual(llm.status()["state"], "ready")
                self.assertTrue(process_manager.is_server_running("LLM"))

                cont = asyncio.run(collect(llm.complete_current_response(
                    [{"role": "user", "content": "q"}, {"role": "assistant", "content": "partial"}], "sys")))
                self.assertEqual(cont, "continued text")

                llm.unload_model()
                self.assertFalse(process_manager.is_server_running("LLM"))
                self.assertEqual(llm.status()["state"], "stopped")
        finally:
            os.environ.pop("LAV_LLAMA_SERVER", None)


class RemoteProviders(unittest.TestCase):
    """LM Studio-style LLM API and a Voicebox-style voice API, exercised over real HTTP."""

    def setUp(self):
        import socket
        import subprocess
        import time
        import httpx
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            self.port = s.getsockname()[1]
        fake = Path(__file__).resolve().parent / "fake_llama_server.py"
        self.proc = subprocess.Popen([sys.executable, str(fake), "-m", "x", "--port", str(self.port), "--require-key"],
                                     stdout=subprocess.DEVNULL)
        for _ in range(50):
            try:
                httpx.get(f"http://127.0.0.1:{self.port}/health", timeout=0.5)
                break
            except httpx.HTTPError:
                time.sleep(0.1)

    def tearDown(self):
        self.proc.terminate()
        self.proc.wait()

    def test_remote_llm_lists_models_and_streams_with_key(self):
        import asyncio
        from unittest import mock
        from services.LLM import remote
        from services.LLM.LLM import LLM

        base = remote.normalize_url(f"127.0.0.1:{self.port}", "lmstudio")
        self.assertEqual(base, f"http://127.0.0.1:{self.port}/v1")
        self.assertEqual(asyncio.run(remote.list_models(base, "sk-test")), ["gemma-4-12b", "qwen3.8-27b"])

        llm = LLM()
        llm.set_remote(preset="lmstudio", base_url=base, model="qwen3.8-27b")
        llm.set_provider("remote")

        async def collect():
            return "".join([c async for c in llm.get_completion("hi", [], "sys")])

        with mock.patch("services.LLM.LLM.get_secret", return_value="sk-test"):
            self.assertEqual(asyncio.run(collect()), "Hello there!")
            self.assertEqual(llm.status()["state"], "ready")
        with mock.patch("services.LLM.LLM.get_secret", return_value="wrong"):
            with self.assertRaises(RuntimeError) as ctx:
                asyncio.run(collect())
            self.assertIn("API key", str(ctx.exception))
            self.assertEqual(llm.status()["state"], "error")

    def test_unconfigured_remote_explains_itself(self):
        import asyncio
        from services.LLM.LLM import LLM
        llm = LLM()
        llm.set_provider("remote")
        with self.assertRaises(RuntimeError) as ctx:
            asyncio.run(llm.ensure_loaded())
        self.assertIn("Brain page", str(ctx.exception))

    def test_voicebox_profiles_and_generate(self):
        import asyncio
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from services.TTS import remote

        seen = {}

        class Voicebox(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                body = json.dumps([{"id": "p1", "name": "Aya", "language": "ja"}]).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                seen.update(json.loads(self.rfile.read(int(self.headers["Content-Length"]))), path=self.path)
                body = wav_bytes(0.5)
                self.send_response(200)
                self.send_header("Content-Type", "audio/wav")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Voicebox)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = remote.normalize_url(f"127.0.0.1:{server.server_address[1]}", "voicebox")
        try:
            voices = asyncio.run(remote.list_voices("voicebox", base, None))
            self.assertEqual(voices[0]["name"], "Aya")
            audio, media = asyncio.run(remote.synthesize("voicebox", base, None, "hello", "p1", None, "ja"))
        finally:
            server.shutdown()
        self.assertEqual(media, "audio/wav")
        self.assertGreater(len(audio), 1000)
        self.assertEqual((seen["path"], seen["profile_id"], seen["language"]), ("/generate/stream", "p1", "ja"))


class HardwareRecommendations(unittest.TestCase):
    def info(self, gpus, ram=32):
        return {"ram": {"total_gb": ram}, "gpus": gpus}

    def test_tiers(self):
        from services.lib.hardware import recommend
        nv = lambda gb: [{"vendor": "NVIDIA", "name": f"RTX {gb}GB", "vram_gb": gb}]
        catalog = [{"id": "Qwen3.8-27B-abliterated-IQ3_S", "size_gb": 12.0}, {"id": "Gemma-4-12B-it-Q4", "size_gb": 7.5}]
        r24 = recommend(self.info(nv(24)), catalog)
        self.assertEqual((r24["llm"], r24["voice"]), ("Qwen3.8-27B-abliterated-IQ3_S", "chatterbox"))
        self.assertEqual(r24["model_fits"]["Qwen3.8-27B-abliterated-IQ3_S"]["level"], "great")
        r16 = recommend(self.info(nv(16)), catalog)
        self.assertEqual((r16["llm"], r16["voice"]), ("Qwen3.8-27B-abliterated-IQ3_S", "luxtts"))
        r12 = recommend(self.info(nv(12)), catalog)
        self.assertEqual(r12["llm"], "Gemma-4-12B-it-Q4")
        self.assertEqual(r12["model_fits"]["Qwen3.8-27B-abliterated-IQ3_S"]["level"], "ok")  # split GPU/CPU
        r8 = recommend(self.info(nv(8)), catalog)
        self.assertEqual(r8["llm"], "Gemma-4-12B-it-Q4")
        cpu = recommend(self.info([], ram=8), catalog)
        self.assertEqual((cpu["llm"], cpu["voice"]), ("Aya-7b-gguf", "luxtts"))
        self.assertEqual(cpu["model_fits"]["Qwen3.8-27B-abliterated-IQ3_S"]["level"], "no")
        igpu = recommend(self.info([{"vendor": "Intel", "name": "UHD", "vram_gb": 0.1, "integrated": True}]), catalog)
        self.assertIsNone(igpu["gpu"])  # integrated graphics are not counted as a usable GPU
        mac = recommend(self.info([{"vendor": "Apple", "name": "M3 Max", "vram_gb": 45, "unified": True}], ram=64), catalog)
        self.assertEqual((mac["llm"], mac["voice"]), ("Qwen3.8-27B-abliterated-IQ3_S", "chatterbox"))


class UsageAttribution(unittest.TestCase):
    """GPU memory is attributed to the right part of the app, whichever source provides it."""

    def make(self):
        from services.lib.monitor import UsageMonitor
        m = UsageMonitor()
        groups = {"llm": {101, 102}, "voice": {201}, "window": {301}, "app": {1}}
        return m, groups

    def test_nvml_per_process(self):
        from types import SimpleNamespace as NS
        m, groups = self.make()

        class FakeNVML:
            NVML_TEMPERATURE_GPU = 0
            def nvmlDeviceGetCount(self): return 1
            def nvmlDeviceGetHandleByIndex(self, i): return "h"
            def nvmlDeviceGetName(self, h): return "RTX Test"
            def nvmlDeviceGetMemoryInfo(self, h): return NS(total=16 * 2**30, used=11 * 2**30)
            def nvmlDeviceGetUtilizationRates(self, h): return NS(gpu=57)
            def nvmlDeviceGetTemperature(self, h, k): return 61
            def nvmlDeviceGetComputeRunningProcesses(self, h): return [NS(pid=102, usedGpuMemory=9 * 2**30), NS(pid=201, usedGpuMemory=None)]
            def nvmlDeviceGetGraphicsRunningProcesses(self, h): return [NS(pid=301, usedGpuMemory=2**30), NS(pid=999, usedGpuMemory=2**30)]

        m._nvml = FakeNVML()
        g = m._nvidia(groups, [])[0]
        self.assertEqual((g["util_pct"], g["temp_c"], g["per_app"]), (57, 61, True))
        self.assertAlmostEqual(g["by_vram"]["llm"], 9.0)
        self.assertAlmostEqual(g["by_vram"]["window"], 1.0)
        self.assertEqual(g["by_vram"]["voice"], 0.0)  # "not available" values are skipped, not counted as huge

    def test_windows_counters_fill_in_and_cover_amd(self):
        import time
        from services.lib.monitor import _pid_from
        m, groups = self.make()
        self.assertEqual(_pid_from("pid_102_luid_0x0_0x1_phys_0_eng_0_engtype_3D"), 102)
        self.assertIsNone(_pid_from("luid_0x0_phys_0"))
        m._win_counters = {"per_pid": {101: {"mem": 6 * 2**30, "util": 40.0}, 201: {"mem": 2**30, "util": 10.0}},
                           "adapter_used": 9 * 2**30, "total_util": 55.0, "time": time.time()}
        # NVIDIA under Windows WDDM: NVML had totals but no per-app memory
        nv = [{"name": "RTX", "vram_total_gb": 12, "vram_used_gb": 9, "util_pct": 55, "temp_c": None,
               "by_vram": {c: 0.0 for c in ("llm", "voice", "window", "app")}, "by_util": {}, "per_app": False}]
        g = m._apply_windows_counters(nv, groups, [])[0]
        self.assertTrue(g["per_app"])
        self.assertAlmostEqual(g["by_vram"]["llm"], 6.0)
        self.assertAlmostEqual(g["by_util"]["voice"], 10.0)
        # AMD: counters are the only source; total VRAM comes from the hardware scan
        amd = m._apply_windows_counters([], groups, [{"name": "Radeon RX 7800 XT", "vram_gb": 16}])[0]
        self.assertEqual((amd["name"], amd["vram_total_gb"], round(amd["vram_used_gb"])), ("Radeon RX 7800 XT", 16, 9))


class Integrity(unittest.TestCase):
    """Damaged installs are found precisely so only they get reinstalled / restored."""

    def _fake_env(self, root: Path):
        import base64
        import hashlib
        sp = root / "lib" / "python3.11" / "site-packages"
        (sp / "demo").mkdir(parents=True)
        body = b"print('hello')\n"
        (sp / "demo" / "__init__.py").write_bytes(body)
        digest = base64.urlsafe_b64encode(hashlib.sha256(body).digest()).rstrip(b"=").decode()
        info = sp / "demo-1.2.dist-info"
        info.mkdir()
        (info / "METADATA").write_text("Metadata-Version: 2.1\nName: demo\nVersion: 1.2\n\n")
        (info / "direct_url.json").write_text(json.dumps({"url": "https://example.com/demo.zip", "archive_info": {}}))
        (info / "RECORD").write_text(f"demo/__init__.py,sha256={digest},{len(body)}\n"
                                     f"../../../bin/demo,sha256=XXXX,1\ndemo-1.2.dist-info/RECORD,,\n")
        return sp

    def test_env_quick_and_deep(self):
        from services.lib.integrity import check_env
        with tempfile.TemporaryDirectory() as tmp:
            sp = self._fake_env(Path(tmp))
            self.assertEqual(check_env(Path(tmp), deep=True), [])  # scripts outside site-packages are ignored
            f = sp / "demo" / "__init__.py"
            f.write_bytes(b"print('hellO')\n")  # same size, different bytes
            self.assertEqual(check_env(Path(tmp)), [])
            broken = check_env(Path(tmp), deep=True)
            self.assertEqual(broken[0]["requirement"], "demo @ https://example.com/demo.zip")
            f.unlink()
            self.assertIn("missing demo/__init__.py", check_env(Path(tmp))[0]["problems"])

    def test_app_files_skip_user_data(self):
        from services.lib.integrity import build_manifest, check_app_files
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for rel in ("backend/server.py", "backend/settings.json", "Start Linux.sh",
                        "backend/services/Character/VRM3D/models/a.vrm"):
                (root / rel).parent.mkdir(parents=True, exist_ok=True)
                (root / rel).write_text("x")
            manifest = build_manifest(root, ["backend/server.py", "backend/settings.json", "Start Linux.sh",
                                             "backend/services/Character/VRM3D/models/a.vrm"], "1.0")
            for rel in ("backend/settings.json", "Start Linux.sh", "backend/services/Character/VRM3D/models/a.vrm"):
                (root / rel).unlink()
            (root / "backend/server.py").write_text("y")
            self.assertEqual(check_app_files(root, manifest), [])
            self.assertEqual(check_app_files(root, manifest, deep=True), ["backend/server.py"])


class SettingsRecovery(unittest.TestCase):
    def test_damaged_settings_restored_from_backup(self):
        import importlib
        server = importlib.import_module("server")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            mgr = server.SettingsManager(path)
            mgr.save_settings({"a": 1})
            mgr.save_settings({"a": 2})  # previous version becomes the backup
            path.write_text('{"a": 3', encoding="utf-8")  # half-written / damaged
            self.assertEqual(server.SettingsManager(path).settings, {"a": 1})
            self.assertTrue((Path(tmp) / "settings.json.damaged").exists())
            self.assertEqual(json.loads(path.read_text()), {"a": 1})
