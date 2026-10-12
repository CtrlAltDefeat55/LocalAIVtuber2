"""Voices served by another program or an online service.

- Voicebox (local voice studio, on this or another PC): GET /profiles, POST /generate/stream
- OpenAI-compatible speech (OpenAI, Kokoro-FastAPI, LocalAI, openedai-speech, ...): POST /audio/speech
- ElevenLabs (paid): POST /v1/text-to-speech/{voice_id}
"""
import re
from typing import Optional, Tuple

import httpx

PROVIDERS = {
    "voicebox": {
        "label": "Voicebox", "base_url": "http://localhost:17493", "needs_key": False, "has_model": False,
        "help": "Start Voicebox and create a voice profile there. For another PC, make sure Voicebox accepts "
                "network connections and use that PC's address, e.g. http://192.168.1.20:17493.",
    },
    "openai": {
        "label": "OpenAI-compatible speech", "base_url": "https://api.openai.com/v1", "needs_key": False,
        "has_model": True, "default_model": "gpt-4o-mini-tts",
        "help": "Works with OpenAI (paid, needs a key) and local servers such as Kokoro-FastAPI "
                "(http://localhost:8880/v1, model “kokoro”) or LocalAI.",
    },
    "elevenlabs": {
        "label": "ElevenLabs", "base_url": "https://api.elevenlabs.io", "needs_key": True, "has_model": True,
        "default_model": "eleven_flash_v2_5",
        "help": "Paid, very natural voices. Create a key at elevenlabs.io → Profile → API keys. "
                "Flash v2.5 is the lowest-latency model.",
    },
}

OPENAI_VOICES = ["alloy", "ash", "ballad", "coral", "echo", "fable", "nova", "onyx", "sage", "shimmer", "verse"]
VOICEBOX_LANGS = {"zh", "en", "ja", "ko", "de", "fr", "ru", "pt", "es", "it", "he", "ar", "da", "el", "fi", "hi",
                  "ms", "nl", "no", "pl", "sv", "sw", "tr"}


def normalize_url(url: str, provider: str) -> str:
    url = (url or "").strip().rstrip("/")
    if not url:
        return ""
    if not re.match(r"^https?://", url):
        url = "http://" + url
    if provider == "openai":
        url = re.sub(r"/audio/speech$", "", url)
    return url


def explain(error: Exception, base_url: str) -> str:
    if isinstance(error, httpx.ConnectError):
        return (f"Nothing answered at {base_url}. Check the address, that the program is running, and (for another "
                "PC) that its firewall allows the port.")
    if isinstance(error, httpx.TimeoutException):
        return f"{base_url} did not answer in time."
    if isinstance(error, httpx.HTTPStatusError):
        code = error.response.status_code
        if code in (401, 403):
            return "The service rejected the API key (or the account has no credit)."
        if code == 404:
            return "The service answered 404: check the address and the selected voice."
        return f"The voice service returned an error ({code}): {error.response.text[:300]}"
    return str(error)


def _key_headers(provider: str, key: Optional[str]) -> dict:
    if not key:
        return {}
    return {"xi-api-key": key} if provider == "elevenlabs" else {"Authorization": f"Bearer {key}"}


async def list_voices(provider: str, base_url: str, key: Optional[str]) -> list:
    """[{id, name, language?}] for the voice picker."""
    async with httpx.AsyncClient(timeout=httpx.Timeout(10, read=20)) as client:
        if provider == "voicebox":
            r = await client.get(f"{base_url}/profiles")
            r.raise_for_status()
            return [{"id": p["id"], "name": p.get("name") or p["id"], "language": p.get("language")} for p in r.json()]
        if provider == "elevenlabs":
            r = await client.get(f"{base_url}/v1/voices", headers=_key_headers(provider, key))
            r.raise_for_status()
            return [{"id": v["voice_id"], "name": v.get("name") or v["voice_id"]} for v in r.json().get("voices", [])]
        # OpenAI-compatible: some servers list their voices, OpenAI itself does not
        try:
            r = await client.get(f"{base_url}/audio/voices", headers=_key_headers(provider, key))
            if r.status_code == 200:
                data = r.json()
                voices = data.get("voices", data) if isinstance(data, dict) else data
                out = [{"id": v if isinstance(v, str) else v.get("id") or v.get("name"),
                        "name": v if isinstance(v, str) else v.get("name") or v.get("id")} for v in voices]
                if out:
                    return out
        except (httpx.HTTPError, ValueError):
            pass
        # Confirm the server is reachable before falling back to the standard voice names.
        r = await client.get(f"{base_url}/models", headers=_key_headers(provider, key))
        if r.status_code in (401, 403):
            r.raise_for_status()
        return [{"id": v, "name": v.title()} for v in OPENAI_VOICES]


async def synthesize(provider: str, base_url: str, key: Optional[str], text: str, voice: str,
                     model: Optional[str], language: Optional[str], speed: float = 1.0) -> Tuple[bytes, str]:
    if not voice:
        raise LookupError("Choose a voice for the connected voice service on the Voice page.")
    timeout = httpx.Timeout(connect=10, read=120, write=30, pool=10)
    async with httpx.AsyncClient(timeout=timeout) as client:
        if provider == "voicebox":
            lang = (language or "en").lower()
            body = {"profile_id": voice, "text": text, "language": lang if lang in VOICEBOX_LANGS else "en"}
            r = await client.post(f"{base_url}/generate/stream", json=body)
            r.raise_for_status()
            return r.content, "audio/wav"
        if provider == "elevenlabs":
            r = await client.post(f"{base_url}/v1/text-to-speech/{voice}", params={"output_format": "mp3_44100_128"},
                                  headers=_key_headers(provider, key),
                                  json={"text": text, "model_id": model or PROVIDERS["elevenlabs"]["default_model"]})
            r.raise_for_status()
            return r.content, "audio/mpeg"
        body = {"model": model or PROVIDERS["openai"]["default_model"], "input": text, "voice": voice,
                "response_format": "wav"}
        if speed and abs(speed - 1.0) > 0.01:
            body["speed"] = speed
        r = await client.post(f"{base_url}/audio/speech", headers=_key_headers(provider, key), json=body)
        r.raise_for_status()
        return r.content, r.headers.get("content-type", "audio/wav").split(";")[0]
