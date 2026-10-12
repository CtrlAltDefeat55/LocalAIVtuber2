"""Text-to-speech engine host.

Runs inside an engine's own Python environment (runtime/envs/<engine>) so
engines with conflicting dependencies (e.g. different `transformers`
versions) never clash with each other or with the main app.

Only the standard library is used for the HTTP layer. Protocol:
  GET  /health                 -> {"ok": true, "engine": ..., "sample_rate": ...}
  POST /synthesize  JSON       -> audio/wav bytes
       {"text", "voice": {"name", "audio_path", "reference_text", "language"}, "options": {...}}
Prints "SIDECAR READY" once the model is loaded.
"""
import argparse
import io
import json
import os
import sys
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def pick_device(requested: str) -> str:
    import torch
    if requested and requested != "auto":
        return requested
    if torch.cuda.is_available():
        return "cuda"
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def to_numpy(audio) -> np.ndarray:
    if hasattr(audio, "detach"):
        audio = audio.detach().float().cpu().numpy()
    audio = np.asarray(audio, dtype=np.float32)
    return audio.reshape(-1)


class Engine:
    sample_rate = 24000

    def __init__(self, device: str, variant: str | None):
        self.device = device
        self.variant = variant
        self._voice_key = None
        self._voice_cache = None

    def prepare_voice(self, voice: dict):
        """Encode the reference voice once and reuse it until a different voice is requested."""
        key = (voice.get("audio_path"), os.path.getmtime(voice["audio_path"]), voice.get("reference_text"))
        if key != self._voice_key:
            self._voice_cache = self.encode_voice(voice)
            self._voice_key = key
        return self._voice_cache

    def encode_voice(self, voice: dict):
        return voice

    def synthesize(self, text: str, voice: dict, options: dict) -> np.ndarray:
        raise NotImplementedError


class ChatterboxTurbo(Engine):
    def __init__(self, device, variant):
        super().__init__(device, variant)
        from chatterbox.tts_turbo import ChatterboxTurboTTS
        self.model = ChatterboxTurboTTS.from_pretrained(device=device)
        self.sample_rate = self.model.sr

    def encode_voice(self, voice):
        self.model.prepare_conditionals(voice["audio_path"])  # needs > 5 s of reference audio
        return True

    def synthesize(self, text, voice, options):
        self.prepare_voice(voice)
        wav = self.model.generate(text, temperature=float(options.get("temperature", 0.8)))
        return to_numpy(wav)


class OmniVoiceEngine(Engine):
    def __init__(self, device, variant):
        super().__init__(device, variant)
        import torch
        from omnivoice import OmniVoice
        dtype = torch.float16 if device == "cuda" else torch.float32
        self.model = OmniVoice.from_pretrained("k2-fsa/OmniVoice", device_map=device, dtype=dtype)
        self.sample_rate = self.model.sampling_rate or 24000

    def encode_voice(self, voice):
        return self.model.create_voice_clone_prompt(voice["audio_path"], ref_text=voice.get("reference_text") or None)

    def synthesize(self, text, voice, options):
        prompt = self.prepare_voice(voice)
        kwargs = {}
        if options.get("speed"):
            kwargs["speed"] = float(options["speed"])
        if options.get("steps"):
            kwargs["num_step"] = int(options["steps"])
        audios = self.model.generate(text=text, language=voice.get("language") or None,
                                     voice_clone_prompt=prompt, **kwargs)
        return to_numpy(audios[0])


class LuxTTSEngine(Engine):
    sample_rate = 48000

    def __init__(self, device, variant):
        super().__init__(device, variant)
        from zipvoice.luxvoice import LuxTTS
        threads = max(1, (os.cpu_count() or 4) // 2)
        self.model = LuxTTS("YatharthS/LuxTTS", device=device, threads=threads)

    def encode_voice(self, voice):
        return self.model.encode_prompt(voice["audio_path"], duration=5, rms=0.01)

    def synthesize(self, text, voice, options):
        prompt = self.prepare_voice(voice)
        wav = self.model.generate_speech(text, prompt, num_steps=int(options.get("steps", 4)),
                                         t_shift=float(options.get("t_shift", 0.9)),
                                         speed=float(options.get("speed", 1.0)),
                                         return_smooth=bool(options.get("smooth", False)))
        return to_numpy(wav)


class TadaEngine(Engine):
    def __init__(self, device, variant):
        super().__init__(device, variant)
        import torch
        from tada.modules.encoder import Encoder
        from tada.modules.tada import TadaForCausalLM
        repo = "HumeAI/tada-3b-ml" if variant == "3b" else "HumeAI/tada-1b"
        dtype = torch.bfloat16 if device == "cuda" else torch.float32
        self.torch = torch
        self.encoder = Encoder.from_pretrained("HumeAI/tada-codec", subfolder="encoder").to(device)
        self.model = TadaForCausalLM.from_pretrained(repo, torch_dtype=dtype).to(device)
        self.model.eval()

    def encode_voice(self, voice):
        import torchaudio
        audio, sr = torchaudio.load(voice["audio_path"])
        audio = audio.mean(dim=0, keepdim=True).to(self.device)
        with self.torch.no_grad():
            return self.encoder(audio, text=[voice.get("reference_text") or ""], sample_rate=sr)

    def synthesize(self, text, voice, options):
        prompt = self.prepare_voice(voice)
        with self.torch.no_grad():
            out = self.model.generate(prompt=prompt, text=text)
        if not out.audio or out.audio[0] is None:
            raise RuntimeError("TADA produced no audio for this text")
        return to_numpy(out.audio[0])


class GptSovitsEngine(Engine):
    def __init__(self, device, variant):
        super().__init__(device, variant)
        os.chdir(BACKEND_DIR)  # its config uses paths relative to backend/
        sys.path.insert(0, BACKEND_DIR)
        from services.TTS.GPTsovits.GptSovits import GptSovits
        self.engine = GptSovits(device=device)
        self.sample_rate = 32000

    def synthesize(self, text, voice, options):
        sr, audio = self.engine.synthesize_raw(text, voice["audio_path"], voice.get("reference_text", ""),
                                               voice.get("language", "en"), options)
        self.sample_rate = sr
        audio = np.asarray(audio)
        if audio.dtype == np.int16:
            audio = audio.astype(np.float32) / 32768.0
        return audio.reshape(-1)


ENGINES = {
    "chatterbox": ChatterboxTurbo,
    "omnivoice": OmniVoiceEngine,
    "luxtts": LuxTTSEngine,
    "tada": TadaEngine,
    "gptsovits": GptSovitsEngine,
}


def make_handler(engine: Engine, name: str, lock: threading.Lock):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # keep the console quiet; errors are reported explicitly

        def _json(self, code, payload):
            body = json.dumps(payload).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/health":
                self._json(200, {"ok": True, "engine": name, "sample_rate": engine.sample_rate,
                                 "device": engine.device})
            else:
                self._json(404, {"error": "not found"})

        def do_POST(self):
            if self.path != "/synthesize":
                return self._json(404, {"error": "not found"})
            try:
                req = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                text = (req.get("text") or "").strip()
                if not text:
                    return self._json(400, {"error": "text is empty"})
                with lock:  # one GPU job at a time; requests queue in order
                    audio = engine.synthesize(text, req["voice"], req.get("options") or {})
                import soundfile as sf
                buf = io.BytesIO()
                sf.write(buf, np.clip(audio, -1, 1), int(engine.sample_rate), format="WAV", subtype="PCM_16")
                data = buf.getvalue()
                self.send_response(200)
                self.send_header("Content-Type", "audio/wav")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except Exception as e:
                traceback.print_exc()
                self._json(500, {"error": f"{type(e).__name__}: {e}"})

    return Handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", required=True, choices=sorted(ENGINES))
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--variant", default=None)
    args = parser.parse_args()

    device = pick_device(args.device)
    print(f"Loading {args.engine} on {device} (first start downloads the model weights)...", flush=True)
    engine = ENGINES[args.engine](device, args.variant)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(engine, args.engine, threading.Lock()))
    print(f"SIDECAR READY on port {args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
