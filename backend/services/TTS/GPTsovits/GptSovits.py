"""GPT-SoVITS v2 inference, hosted by engines/tts_sidecar.py in its own environment.

Voices are managed by services/TTS/voice_library.py; this class only synthesizes.
"""
import os
import sys

import torch

from services.lib.LAV_logger import logger

current_module_directory = os.path.dirname(__file__)
sys.path.insert(0, current_module_directory)
sys.path.insert(0, os.path.join(current_module_directory, "GPT_SoVITS"))

from services.TTS.GPTsovits.GPT_SoVITS.TTS_infer_pack.TTS import TTS as TTS_gptsovits, TTS_Config  # noqa: E402

PRETRAINED_DIR = os.path.join(current_module_directory, "GPT_SoVITS", "pretrained_models")
PRETRAINED_REPO = "lj1995/GPT-SoVITS"
PRETRAINED_PATTERNS = [
    "chinese-roberta-wwm-ext-large/*",
    "chinese-hubert-base/*",
    "gsv-v2final-pretrained/s1bert25hz-5kh-longer-epoch=12-step=369668.ckpt",
    "gsv-v2final-pretrained/s2G2333k.pth",
]
LANGS = {"en", "zh", "ja", "ko", "yue", "auto"}


def ensure_pretrained():
    """Fetch the base models the first time (they are not part of the repository)."""
    marker = os.path.join(PRETRAINED_DIR, "gsv-v2final-pretrained", "s2G2333k.pth")
    if os.path.exists(marker):
        return
    from huggingface_hub import snapshot_download
    logger.info("Downloading GPT-SoVITS base models (~1.5 GB, first run only)...")
    snapshot_download(PRETRAINED_REPO, local_dir=PRETRAINED_DIR, allow_patterns=PRETRAINED_PATTERNS)


class GptSovits:
    def __init__(self, device: str = "cuda"):
        ensure_pretrained()
        config_path = os.path.join(current_module_directory, "GPT_SoVITS", "configs", "tts_infer.yaml")
        self.tts_config = TTS_Config(config_path)
        self.tts_config.device = torch.device(device if device in ("cuda", "cpu") else "cpu")
        self.tts_config.is_half = self.tts_config.device.type == "cuda"
        self.tts_pipeline = TTS_gptsovits(self.tts_config)

    def synthesize_raw(self, text, ref_audio_path, prompt_text, prompt_lang, options=None):
        options = options or {}
        lang = (prompt_lang or "en").lower()
        req = {
            "text": text,
            "text_lang": "auto",
            "ref_audio_path": ref_audio_path,
            "aux_ref_audio_paths": [],
            "prompt_text": prompt_text,
            "prompt_lang": lang if lang in LANGS else "en",
            "top_k": 5,
            "top_p": 1,
            "temperature": float(options.get("temperature", 1)),
            "text_split_method": "cut0",
            "batch_size": 1,
            "batch_threshold": 0.75,
            "speed_factor": float(options.get("speed", 1.0)),
            "split_bucket": True,
            "fragment_interval": 0.3,
            "seed": -1,
            "media_type": "wav",
            "streaming_mode": False,
            "parallel_infer": True,
            "repetition_penalty": 1.35,
            "sample_steps": 32,
            "super_sampling": False,
        }
        sr, audio = next(self.tts_pipeline.run(req))
        return sr, audio
