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
