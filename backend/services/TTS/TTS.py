import asyncio
import re
import threading
from typing import Optional

from services.lib.LAV_logger import logger
from .engines import ENGINES, EngineManager, detect_gpu
from .voice_library import VoiceLibrary

DEFAULT_ENGINE = "chatterbox"

# Things an LLM writes that should not be read aloud: *actions*, markdown, emoji.
_BOLD_RE = re.compile(r"(\*\*|__)(.+?)\1")
_ACTION_RE = re.compile(r"(?<!\*)\*[^*\n]{1,80}\*(?!\*)")
_MARKDOWN_RE = re.compile(r"[*_`#>~]+")
_EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F000-\U0001F2FF️‍]+")


def speakable(text: str) -> str:
    text = _BOLD_RE.sub(r"\2", text)  # keep emphasised words
    text = _ACTION_RE.sub(" ", text)  # drop *stage directions*
    text = _MARKDOWN_RE.sub("", text)
    text = _EMOJI_RE.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


class TTS:
    """The active voice engine + the selected voice from the shared library."""

    def __init__(self):
        self.engines = EngineManager()
        self.voices = VoiceLibrary()
        self.active_engine = DEFAULT_ENGINE
        self.current_voice: Optional[str] = None
        self.variants: dict = {}
        self.options: dict = {"speed": 1.0}
        self.gpu = detect_gpu()
        self._start_lock = threading.Lock()
        voices = self.voices.list()
        if voices:
            self.current_voice = "leaf" if any(v["name"] == "leaf" for v in voices) else voices[0]["name"]

    # ------------------------------------------------------------------ selection

    def status(self) -> dict:
        return {
            "active_engine": self.active_engine,
            "current_voice": self.current_voice,
            "engines": self.engines.list(),
            "gpu": {k: v for k, v in self.gpu.items() if k != "index"},
            "options": self.options,
        }

    def set_engine(self, engine_id: str, variant: Optional[str] = None, start: bool = True):
        if engine_id not in ENGINES:
            raise ValueError(f"Unknown voice engine '{engine_id}'")
        if variant:
            self.variants[engine_id] = variant
        self.active_engine = engine_id
        if start and self.engines.is_installed(engine_id):
            self.start_in_background()

    def start_in_background(self):
        threading.Thread(target=self._start_active, daemon=True).start()

    def _start_active(self):
        engine_id = self.active_engine
        with self._start_lock:
            try:
                # Only one engine holds the GPU at a time.
                self.engines.stop_all_except(engine_id)
                self.engines.start(engine_id, self.variants.get(engine_id))
            except Exception as e:
                logger.error(f"Voice engine {engine_id} failed to start: {e}")

    def change_voice(self, voice_name: str):
        if not self.voices.get(voice_name):
            raise ValueError(f"Voice '{voice_name}' not found")
        self.current_voice = voice_name
        return {"message": f"Voice changed to {voice_name}"}

    # ------------------------------------------------------------------ synthesis

    async def synthesize(self, text: str, voice_name: Optional[str] = None, engine_id: Optional[str] = None) -> bytes:
        engine_id = engine_id or self.active_engine
        text = speakable(text)
        if not text:
            raise ValueError("Nothing to say (the text only contained actions, emoji or symbols).")
        voice = self.voices.get(voice_name or self.current_voice or "")
        if not voice:
            raise LookupError("No voice selected. Add or choose a voice on the Voice page.")
        state = self.engines.engine_state(engine_id)
        if state == "not_installed":
            raise LookupError(f"{ENGINES[engine_id]['label']} is not installed. Install it on the Voice page.")
        if state == "installing":
            raise LookupError(f"{ENGINES[engine_id]['label']} is still installing.")
        if state != "ready":
            await asyncio.to_thread(self._start_blocking, engine_id)
        return await self.engines.synthesize(engine_id, text, voice, self.options)

    def _start_blocking(self, engine_id: str):
        with self._start_lock:
            if engine_id == self.active_engine:
                self.engines.stop_all_except(engine_id)
            self.engines.start(engine_id, self.variants.get(engine_id))
