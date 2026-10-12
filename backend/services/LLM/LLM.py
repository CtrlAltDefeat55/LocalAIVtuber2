import asyncio
import base64
import io
import json
import math
import os
import re
import threading
from typing import AsyncGenerator, Optional

import httpx

from services.lib.LAV_logger import logger
from services.lib.paths import LLM_MODELS_DIR
from services.lib.secrets import get_secret
from . import remote as remote_api
from .llama_server import LlamaServer, find_llama_server

# Rough characters-per-token used to keep requests inside the context window
# without a tokenizer round-trip per message.
CHARS_PER_TOKEN = 3.5


class LLM:
    """Model catalog + a llama-server process serving the selected model.

    State machine (exposed to the UI via `status()`):
      stopped -> loading -> ready
                        \\-> error   (message in `error`)
    """

    def __init__(self):
        self.models_directory = str(LLM_MODELS_DIR)
        os.makedirs(self.models_directory, exist_ok=True)
        self.server = LlamaServer()
        self.all_model_data: list = []
        self.current_model_data: Optional[dict] = None
        self.keep_model_loaded = True
        self.state = "stopped"
        self.error: Optional[str] = None
        self.loaded_model_id: Optional[str] = None
        self._lock = threading.Lock()
        self._generation = 0  # bumps on every load request so stale loads cancel themselves

        self.sampling_params = {
            'top_k': 40, 'top_p': 0.95, 'min_p': 0.05,
            'repeat_penalty': 1.1, 'temperature': 0.8, 'seed': -1,
        }
        self.runtime_options = {
            "context_size": 8192,
            "gpu_layers": "auto",
            "cpu_only": False,
            "enable_vision": False,
            "thinking": False,
            "max_tokens": 512,
        }
        # "local" = llama-server on this PC; "remote" = an OpenAI-compatible API (LM Studio, OpenAI, ...)
        self.provider = "local"
        self.remote = {"preset": "lmstudio", "base_url": "", "model": ""}
        self.remote_error: Optional[str] = None
        self._load_available_models()

    # ------------------------------------------------------------------ catalog

    def _load_available_models(self):
        """Scan Models/: every folder with metadata.json is a catalog entry.

        `local.json` (not tracked by git) records what was actually downloaded.
        Loose .gguf files dropped into Models/ by hand are picked up too.
        """
        models = []
        for root, dirs, files in os.walk(self.models_directory):
            dirs.sort()
            if "metadata.json" not in files:
                continue
            metadata_path = os.path.join(root, "metadata.json")
            try:
                with open(metadata_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                local_path = os.path.join(root, "local.json")
                if os.path.isfile(local_path):
                    with open(local_path, "r", encoding="utf-8") as f:
                        data.update(json.load(f))
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"Could not load metadata from {metadata_path}: {e}")
                continue
            data["id"] = os.path.relpath(root, self.models_directory).replace(os.sep, "/")
            models.append(self._describe(data, root, metadata_path))

        known = {os.path.normcase(os.path.join(m["model_folder"], m.get("fileName") or "")) for m in models}
        for root, _dirs, files in os.walk(self.models_directory):
            if "metadata.json" in files:
                continue
            for name in sorted(files):
                path = os.path.join(root, name)
                low = name.lower()
                if not low.endswith(".gguf") or "mmproj" in low or os.path.normcase(path) in known:
                    continue
                if re.search(r"-0000[2-9]-of-\d{5}\.gguf$", low):
                    continue  # later parts of a split model
                projs = [f for f in files if "mmproj" in f.lower() and f.lower().endswith(".gguf")]
                data = {"displayName": os.path.splitext(name)[0], "fileName": name, "type": "text",
                        "description": "Added from the Models folder.", "local_only": True,
                        "mmproj_path": projs[0] if projs else None,
                        "id": "file:" + os.path.relpath(path, self.models_directory).replace(os.sep, "/")}
                models.append(self._describe(data, root, None))

        models.sort(key=lambda m: (not m.get("recommended", False), m.get("order", 100), m.get("displayName", "")))
        self.all_model_data = models

        if self.current_model_data:
            self.current_model_data = self.get_model(self.current_model_data.get("id"))
        if not self.current_model_data and models:
            existing = [m for m in models if m["file_exists"]]
            self.current_model_data = (existing or models)[0]

    def _describe(self, data: dict, root: str, metadata_path: Optional[str]) -> dict:
        data["metadata_path"] = metadata_path
        data["model_folder"] = root
        file_name = data.get("fileName") or ""
        data["file_exists"] = bool(file_name) and os.path.isfile(os.path.join(root, file_name))
        if data["file_exists"]:
            parts = data.get("parts") or [file_name]
            size = sum(os.path.getsize(os.path.join(root, p)) for p in parts if os.path.isfile(os.path.join(root, p)))
            data["file_size_bytes"] = size
            data["file_size_readable"] = self._format_file_size(size)
        else:
            data["file_size_bytes"] = 0
            data["file_size_readable"] = data.get("size_hint") or "Not downloaded"
        mmproj = data.get("mmproj_path")
        data["mmproj_exists"] = bool(mmproj) and os.path.isfile(os.path.join(root, mmproj))
        data["downloadable"] = bool(data.get("link") or data.get("repo"))
        return data

    def get_model(self, model_id_or_file: Optional[str]) -> Optional[dict]:
        if not model_id_or_file:
            return None
        for m in self.all_model_data:
            if model_id_or_file in (m.get("id"), m.get("fileName"), m.get("displayName")):
                return m
        return None

    @staticmethod
    def _format_file_size(size_bytes):
        if not size_bytes:
            return "0 B"
        names = ["B", "KB", "MB", "GB", "TB"]
        i = min(int(math.floor(math.log(size_bytes, 1024))), len(names) - 1)
        return f"{round(size_bytes / math.pow(1024, i), 2)} {names[i]}"

    def status(self) -> dict:
        if self.provider == "remote":
            r = self.remote
            configured = bool(r["base_url"] and r["model"])
            label = remote_api.PRESETS.get(r["preset"], {}).get("label", "API")
            return {
                "provider": "remote",
                "state": "error" if self.remote_error else ("ready" if configured else "stopped"),
                "error": self.remote_error if configured else "Set up the API connection on the Brain page.",
                "runtime_installed": True,
                "model_id": None,
                "model_name": f"{r['model'] or 'No model'} · {label}",
                "model_downloaded": configured,
                "loaded_model_id": None,
                "vision_active": bool(self.runtime_options["enable_vision"]),
                "options": self.runtime_options,
                "remote": {**r, "has_key": bool(get_secret("llm.remote"))},
            }
        model = self.current_model_data or {}
        return {
            "provider": "local",
            "state": self.state,
            "error": self.error,
            "runtime_installed": find_llama_server() is not None,
            "model_id": model.get("id"),
            "model_name": model.get("displayName"),
            "model_downloaded": bool(model.get("file_exists")),
            "loaded_model_id": self.loaded_model_id,
            "vision_active": bool(self.server.mmproj_path),
            "options": self.runtime_options,
        }

    # ------------------------------------------------------------------ lifecycle

    def select_model(self, model_id: str, load: Optional[bool] = None) -> bool:
        self._load_available_models()
        model = self.get_model(model_id)
        if not model:
            logger.error(f"Model {model_id} not found.")
            return False
        changed = (self.current_model_data or {}).get("id") != model["id"]
        self.current_model_data = model
        if changed:
            self.error = None
            if self.state == "error":
                self.state = "stopped"
            if self.loaded_model_id and self.loaded_model_id != model["id"]:
                self.unload_model()
        if (load if load is not None else self.keep_model_loaded) and model.get("file_exists"):
            self.load_in_background()
        return True

    # Back-compat with settings written by older versions ("llm.model_filename")
    def load_model_by_filename(self, model_filename: str):
        return self.select_model(model_filename)

    def set_runtime_options(self, **options):
        changed = {k: v for k, v in options.items() if self.runtime_options.get(k) != v}
        if not changed:
            return
        self.runtime_options.update(changed)
        restart_keys = {"context_size", "gpu_layers", "cpu_only", "enable_vision"}
        if restart_keys & changed.keys() and self.loaded_model_id:
            logger.info(f"LLM runtime options changed ({', '.join(changed)}), reloading model")
            self.unload_model()
            if self.keep_model_loaded:
                self.load_in_background()

    def load_in_background(self):
        threading.Thread(target=self._safe_load, daemon=True).start()

    def _safe_load(self):
        try:
            self.load_model(self.current_model_data)
        except Exception as e:
            logger.error(f"Model load failed: {e}")

    def load_model(self, model_data: Optional[dict] = None):
        """Blocking: start llama-server with the model. Safe to call repeatedly."""
        if self.provider == "remote":
            return  # the brain runs elsewhere; nothing to load here
        model_data = model_data or self.current_model_data
        if not model_data:
            self.state, self.error = "error", "No model selected. Pick or download a model on the Brain page."
            raise RuntimeError(self.error)
        self._generation += 1
        generation = self._generation
        with self._lock:
            if generation != self._generation:
                return  # a newer request superseded this one while we waited
            if self.loaded_model_id == model_data["id"] and self.server.is_running():
                self.state = "ready"
                return
            folder = model_data["model_folder"]
            model_path = os.path.join(folder, model_data.get("fileName") or "")
            if not model_data.get("fileName") or not os.path.isfile(model_path):
                self.state = "error"
                self.error = f"{model_data.get('displayName')} is not downloaded yet."
                raise RuntimeError(self.error)
            mmproj = None
            if self.runtime_options["enable_vision"] and model_data.get("mmproj_path"):
                candidate = os.path.join(folder, model_data["mmproj_path"])
                mmproj = candidate if os.path.isfile(candidate) else None
            self.state, self.error = "loading", None
            self.current_model_data = model_data
            gpu_layers = "0" if self.runtime_options["cpu_only"] else self.runtime_options["gpu_layers"]
            try:
                self.server.start(model_path, mmproj, self.runtime_options["context_size"], gpu_layers,
                                  is_cancelled=lambda: generation != self._generation)
            except Exception as e:
                self.loaded_model_id = None
                if generation == self._generation:
                    self.state, self.error = "error", str(e)
                raise
            self.loaded_model_id = model_data["id"]
            self.state = "ready"
            logger.info(f"Model ready: {model_data.get('displayName')}")

    def unload_model(self):
        self._generation += 1  # cancels an in-flight load
        self.server.stop()
        self.loaded_model_id = None
        if self.state != "error":
            self.state = "stopped"
        logger.info("Model unloaded.")

    def set_keep_model_loaded(self, value):
        self.keep_model_loaded = bool(value)
        if self.keep_model_loaded:
            if self.current_model_data and self.current_model_data.get("file_exists") and not self.loaded_model_id:
                self.load_in_background()

    def update_sampling_params(self, params: dict):
        self.sampling_params.update(params)
        logger.info(f"Updated sampling parameters: {self.sampling_params}")

    def set_provider(self, provider: str):
        provider = "remote" if provider == "remote" else "local"
        if provider == self.provider:
            return
        self.provider = provider
        if provider == "remote":
            self.unload_model()  # free the GPU when a remote brain is used
        elif self.keep_model_loaded and (self.current_model_data or {}).get("file_exists"):
            self.load_in_background()

    def set_remote(self, **values):
        self.remote.update({k: v for k, v in values.items() if v is not None})
        self.remote["base_url"] = remote_api.normalize_url(self.remote["base_url"], self.remote["preset"])
        self.remote_error = None

    def _remote_endpoint(self) -> tuple:
        r = self.remote
        if not r["base_url"] or not r["model"]:
            raise RuntimeError("The API connection isn't set up yet. Open the Brain page, choose “Use an API” and "
                               "test the connection.")
        return f"{r['base_url']}/chat/completions", remote_api.headers(get_secret("llm.remote"))

    async def ensure_loaded(self):
        if self.provider == "remote":
            self._remote_endpoint()  # raises a helpful error when not configured
            return
        if self.loaded_model_id == (self.current_model_data or {}).get("id") and self.server.is_running():
            return
        await asyncio.to_thread(self.load_model, self.current_model_data)

    # ------------------------------------------------------------------ inference

    def _sampling(self) -> dict:
        p = self.sampling_params
        if self.provider == "remote" and not remote_api.PRESETS.get(self.remote["preset"], {}).get("local_server"):
            # hosted APIs reject llama.cpp-only parameters such as top_k / min_p
            out = {"temperature": min(p["temperature"], 2.0), "top_p": p["top_p"]}
            if int(p.get("seed", -1)) >= 0:
                out["seed"] = int(p["seed"])
            return out
        out = {
            "temperature": p["temperature"], "top_k": p["top_k"], "top_p": p["top_p"],
            "min_p": p["min_p"], "repeat_penalty": p["repeat_penalty"],
        }
        if int(p.get("seed", -1)) >= 0:
            out["seed"] = int(p["seed"])
        return out

    def _fit_context(self, messages: list) -> list:
        budget = int(self.runtime_options["context_size"]) - int(self.runtime_options["max_tokens"]) - 256

        def tokens(msg):
            content = msg["content"]
            if isinstance(content, list):  # multimodal parts: count text only, images cost ~1k tokens
                return sum(len(c.get("text", "")) / CHARS_PER_TOKEN if c.get("type") == "text" else 1024
                           for c in content)
            return len(content) / CHARS_PER_TOKEN

        while sum(tokens(m) for m in messages) > budget and len(messages) > 2:
            messages.pop(1)  # drop the oldest turn after the system prompt
        return messages

    def _template_kwargs(self) -> dict:
        if self.provider == "remote":
            return {}
        return {"chat_template_kwargs": {"enable_thinking": bool(self.runtime_options["thinking"])}}

    def _screenshot_part(self) -> Optional[dict]:
        vision = self.runtime_options["enable_vision"] if self.provider == "remote" else bool(self.server.mmproj_path)
        if not vision:
            logger.info("Screenshot requested but vision is not active for this model; sending text only.")
            return None
        try:
            import mss
            from PIL import Image
            with mss.mss() as sct:
                shot = sct.grab(sct.monitors[1])
                img = Image.frombytes("RGB", shot.size, shot.rgb)
            img.thumbnail((1280, 1280))
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=85)
            return {"type": "image_url",
                    "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()}}
        except Exception as e:
            logger.warning(f"Screenshot failed: {e}")
            return None

    async def get_completion(self, text, history, system_prompt, screenshot=False) -> AsyncGenerator[str, None]:
        await self.ensure_loaded()
        messages = [{"role": "system", "content": system_prompt or ""}]
        messages += [m for m in (history or []) if m.get("content")]
        user_content = text
        if screenshot:
            part = await asyncio.to_thread(self._screenshot_part)
            if part:
                user_content = [part, {"type": "text", "text": text}]
        messages.append({"role": "user", "content": user_content})
        body = {"messages": self._fit_context(messages), "stream": True,
                "max_tokens": int(self.runtime_options["max_tokens"]), **self._sampling(), **self._template_kwargs()}
        async for chunk in self._chat(body):
            yield chunk
        self._maybe_unload()

    async def _chat(self, body: dict) -> AsyncGenerator[str, None]:
        if self.provider != "remote":
            async for chunk in self._stream(f"{self.server.base_url}/v1/chat/completions", body, chat=True):
                yield chunk
            return
        url, hdrs = self._remote_endpoint()
        body = {**body, "model": self.remote["model"]}
        try:
            async for chunk in self._stream(url, body, chat=True, headers=hdrs):
                yield chunk
            self.remote_error = None
        except Exception as e:
            self.remote_error = remote_api.explain(e, self.remote["base_url"])
            raise RuntimeError(self.remote_error) from e

    async def complete_current_response(self, history, system_prompt) -> AsyncGenerator[str, None]:
        """Continue the last (partial) assistant message in `history`."""
        if not history:
            return
        await self.ensure_loaded()
        if self.provider == "remote":
            # Remote APIs have no raw-prompt endpoint; ask the model to carry on instead.
            messages = [{"role": "system", "content": system_prompt or ""}] + list(history) + [
                {"role": "user", "content": "(Continue your previous reply exactly where it stopped. Do not repeat it.)"}]
            body = {"messages": self._fit_context(messages), "stream": True,
                    "max_tokens": int(self.runtime_options["max_tokens"]), **self._sampling()}
            async for chunk in self._chat(body):
                yield chunk
            return
        messages = [{"role": "system", "content": system_prompt or ""}] + list(history)
        partial = ""
        if messages[-1]["role"] == "assistant":
            partial = messages.pop()["content"]
        messages = self._fit_context(messages)
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(f"{self.server.base_url}/apply-template",
                                  json={"messages": messages, **self._template_kwargs()})
            r.raise_for_status()
            prompt = r.json()["prompt"] + partial
        body = {"prompt": prompt, "stream": True, "n_predict": int(self.runtime_options["max_tokens"]) * 2,
                **self._sampling()}
        async for chunk in self._stream(f"{self.server.base_url}/completion", body, chat=False):
            yield chunk
        self._maybe_unload()

    async def _stream(self, url: str, body: dict, chat: bool, headers: Optional[dict] = None) -> AsyncGenerator[str, None]:
        in_think = False
        async with httpx.AsyncClient(timeout=httpx.Timeout(connect=10, read=300, write=60, pool=10)) as client:
            async with client.stream("POST", url, json=body, headers=headers) as resp:
                if resp.status_code != 200:
                    detail = (await resp.aread()).decode(errors="replace")[:500]
                    raise httpx.HTTPStatusError(f"LLM request failed ({resp.status_code}): {detail}",
                                                request=resp.request, response=resp)
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        data = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    if chat:
                        choices = data.get("choices") or []  # some APIs send usage-only chunks
                        piece = ((choices[0].get("delta") or {}).get("content") if choices else "") or ""
                    else:
                        piece = data.get("content") or ""
                    # Hide any inline reasoning a template emits even with thinking off.
                    out = ""
                    while piece:
                        if in_think:
                            end = piece.find("</think>")
                            if end < 0:
                                break
                            piece, in_think = piece[end + 8:].lstrip(), False
                        else:
                            start = piece.find("<think>")
                            if start < 0:
                                out += piece
                                break
                            out, piece, in_think = out + piece[:start], piece[start + 7:], True
                    if out:
                        yield out
                    if not chat and data.get("stop"):
                        break

    def _maybe_unload(self):
        if self.provider == "local" and not self.keep_model_loaded:
            self.unload_model()
