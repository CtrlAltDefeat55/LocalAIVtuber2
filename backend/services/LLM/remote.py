"""Use a language model served somewhere else through the OpenAI-compatible API.

Covers LM Studio / Ollama / llama.cpp / KoboldCpp running on this or another PC,
and paid online services (OpenAI, OpenRouter, Groq, Google Gemini, ...).
"""
import re
from typing import Optional

import httpx

PRESETS = {
    "lmstudio": {"label": "LM Studio", "base_url": "http://localhost:1234/v1", "needs_key": False, "local_server": True,
                 "help": "In LM Studio open the Developer tab and start the server. To use it from another PC, turn on "
                         "“Serve on Local Network” and enter that PC's IP, e.g. http://192.168.1.20:1234/v1."},
    "ollama": {"label": "Ollama", "base_url": "http://localhost:11434/v1", "needs_key": False, "local_server": True,
               "help": "Ollama listens on port 11434. For another PC, start it with OLLAMA_HOST=0.0.0.0."},
    "llamacpp": {"label": "llama.cpp / KoboldCpp / other local server", "base_url": "http://localhost:8080/v1",
                 "needs_key": False, "local_server": True,
                 "help": "Any server with an OpenAI-compatible /v1/chat/completions endpoint."},
    "openai": {"label": "OpenAI", "base_url": "https://api.openai.com/v1", "needs_key": True, "local_server": False,
               "help": "Paid. Create a key at platform.openai.com/api-keys."},
    "openrouter": {"label": "OpenRouter", "base_url": "https://openrouter.ai/api/v1", "needs_key": True,
                   "local_server": False, "help": "One key for hundreds of models (paid and free). openrouter.ai/keys"},
    "groq": {"label": "Groq", "base_url": "https://api.groq.com/openai/v1", "needs_key": True, "local_server": False,
             "help": "Very fast hosted open models. console.groq.com/keys"},
    "gemini": {"label": "Google Gemini", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
               "needs_key": True, "local_server": False, "help": "Key from aistudio.google.com/apikey"},
    "custom": {"label": "Other (OpenAI-compatible)", "base_url": "", "needs_key": False, "local_server": True,
               "help": "Enter the server's base URL ending in /v1."},
}


def normalize_url(url: str, preset: Optional[str] = None) -> str:
    url = (url or "").strip().rstrip("/")
    if not url:
        return ""
    if not re.match(r"^https?://", url):
        url = "http://" + url
    for suffix in ("/chat/completions", "/models"):
        if url.endswith(suffix):
            url = url[: -len(suffix)]
    # LM Studio / Ollama users often type just host:port
    if preset in ("lmstudio", "ollama", "llamacpp") and not re.search(r"/v\d", url):
        url += "/v1"
    return url


def headers(api_key: Optional[str]) -> dict:
    h = {"Content-Type": "application/json"}
    if api_key:
        h["Authorization"] = f"Bearer {api_key}"
    h["HTTP-Referer"] = "https://github.com/CtrlAltDefeat55/LocalAIVtuber2"  # OpenRouter attribution, ignored elsewhere
    h["X-Title"] = "Local AI VTuber"
    return h


def explain(error: Exception, base_url: str) -> str:
    if isinstance(error, httpx.ConnectError):
        return (f"Nothing answered at {base_url}. Check the address, that the server is running, and (for another "
                "PC) that it accepts network connections and the firewall allows the port.")
    if isinstance(error, httpx.TimeoutException):
        return f"{base_url} did not answer in time. The server may be busy loading a model."
    if isinstance(error, httpx.HTTPStatusError):
        code = error.response.status_code
        if code in (401, 403):
            return "The server rejected the API key. Check that it is correct and has credit/permission."
        if code == 404:
            return f"{base_url} doesn't look like an OpenAI-compatible API (got 404). The URL usually ends in /v1."
        body = error.response.text[:300]
        return f"The server answered with an error ({code}): {body}"
    return str(error)


async def list_models(base_url: str, api_key: Optional[str]) -> list:
    async with httpx.AsyncClient(timeout=httpx.Timeout(10, read=20)) as client:
        r = await client.get(f"{base_url}/models", headers=headers(api_key))
        r.raise_for_status()
        data = r.json()
    items = data.get("data") if isinstance(data, dict) else data
    ids = []
    for m in items or []:
        mid = m.get("id") if isinstance(m, dict) else m
        if mid:
            ids.append(str(mid))
    return sorted(set(ids))
