"""Reference voices shared by every voice-cloning engine.

Each voice is a folder `<VOICES_DIR>/<name>/` holding `reference.wav` and a
`metadata.json` ({reference_text, language, audio_file}). This is the same
layout GPT-SoVITS already used, so existing voices keep working unchanged.
"""
import io
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional

import soundfile as sf

from services.lib.LAV_logger import logger
from services.lib.paths import VOICES_DIR

NAME_RE = re.compile(r"^[\w\- .]{1,60}$", re.UNICODE)


class VoiceLibrary:
    def __init__(self, root: Path = VOICES_DIR):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _dir(self, name: str) -> Path:
        if not NAME_RE.match(name or "") or name.strip(" .") != name.strip():
            raise ValueError("Voice names may use letters, numbers, spaces, '-', '_' and '.' (max 60).")
        path = (self.root / name).resolve()
        if path.parent != self.root.resolve():
            raise ValueError("Invalid voice name")
        return path

    def list(self) -> list:
        voices = []
        for d in sorted(self.root.iterdir(), key=lambda p: p.name.lower()) if self.root.exists() else []:
            voice = self._read(d)
            if voice:
                voices.append(voice)
        return voices

    def _read(self, d: Path) -> Optional[dict]:
        meta_path = d / "metadata.json"
        if not d.is_dir() or not meta_path.exists():
            return None
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            logger.warning(f"Skipping voice {d.name}: {e}")
            return None
        audio = d / meta.get("audio_file", "reference.wav")
        if not audio.exists():
            return None
        try:
            duration = round(sf.info(str(audio)).duration, 2)
        except Exception:
            duration = None
        return {
            "name": d.name,
            "reference_text": meta.get("reference_text", ""),
            "language": meta.get("language", "en"),
            "audio_path": str(audio),
            "duration": duration,
        }

    def get(self, name: str) -> Optional[dict]:
        try:
            return self._read(self._dir(name))
        except ValueError:
            return None

    def save(self, name: str, audio: Optional[bytes], reference_text: str, language: str,
             replace: bool = False) -> dict:
        """Create a voice, or update its transcript/language/audio when `replace` is set."""
        d = self._dir(name.strip())
        exists = (d / "metadata.json").exists()
        if exists and not replace:
            raise FileExistsError(f"A voice named '{name}' already exists")
        if not exists and audio is None:
            raise ValueError("A reference audio file is required")
        d.mkdir(parents=True, exist_ok=True)
        wav_path = d / "reference.wav"
        if audio is not None:
            tmp = d / "reference.new.wav"
            try:
                _to_wav(audio, tmp)
                tmp.replace(wav_path)
            finally:
                tmp.unlink(missing_ok=True)
        meta = {"reference_text": reference_text.strip(), "language": language or "en", "audio_file": "reference.wav"}
        (d / "metadata.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        return self._read(d)

    def delete(self, name: str) -> bool:
        d = self._dir(name)
        if not d.exists():
            return False
        shutil.rmtree(d)
        return True


def _to_wav(data: bytes, dest: Path):
    """Store any common audio format as mono WAV; uses ffmpeg only when soundfile cannot decode it."""
    try:
        audio, sr = sf.read(io.BytesIO(data), always_2d=True)
        sf.write(str(dest), audio.mean(axis=1), sr)
        return
    except Exception:
        pass
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise ValueError("Unsupported audio format. Use WAV or FLAC, or install ffmpeg for MP3/M4A support.")
    proc = subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-i", "pipe:0", "-ac", "1", "-ar", "44100", str(dest)],
                          input=data, capture_output=True)
    if proc.returncode != 0:
        raise ValueError("Could not convert the audio file: " + proc.stderr.decode(errors="replace")[-300:])
