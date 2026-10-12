"""HTTP API for the Voice page: engines, the voice library and synthesis."""
from typing import Callable, Optional

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel

from services.lib.LAV_logger import logger
from services.lib.secrets import get_secret, set_secret, storage_name
from . import remote as remote_api
from .TTS import TTS
from .engines import ENGINES


class TTSRequest(BaseModel):
    text: str
    voice: Optional[str] = None
    engine: Optional[str] = None


class ChangeVoiceRequest(BaseModel):
    voice_name: str


class DeleteVoiceRequest(BaseModel):
    name: str


class ActivateRequest(BaseModel):
    variant: Optional[str] = None


class RemoteTestRequest(BaseModel):
    provider: str
    base_url: str
    api_key: Optional[str] = None


class RemoteSaveRequest(BaseModel):
    provider: str
    base_url: str
    voice: str
    voice_name: Optional[str] = ""
    model: Optional[str] = ""
    language: Optional[str] = "en"
    api_key: Optional[str] = None  # None keeps the saved key, "" removes it
    use: bool = True


class OptionsRequest(BaseModel):
    speed: Optional[float] = None


def create_router(tts: TTS, persist: Callable[[dict], None]) -> APIRouter:
    router = APIRouter(prefix="/api/tts")

    def error(status: int, message: str):
        return JSONResponse(status_code=status, content={"error": message})

    # ------------------------------------------------------------------ engines

    @router.get("/engines")
    async def engines():
        return tts.status()

    # ------------------------------------------------------------------ remote voices

    @router.get("/remote")
    async def remote_info():
        return {"providers": remote_api.PROVIDERS, "source": tts.source, "remote": tts.remote,
                "has_key": {p: bool(get_secret(f"tts.{p}")) for p in remote_api.PROVIDERS}, "key_storage": storage_name()}

    @router.post("/remote/test")
    async def remote_test(req: RemoteTestRequest):
        if req.provider not in remote_api.PROVIDERS:
            return error(404, "Unknown voice service")
        base = remote_api.normalize_url(req.base_url, req.provider)
        if not base:
            return error(400, "Enter the address first.")
        key = req.api_key if req.api_key is not None else get_secret(f"tts.{req.provider}")
        try:
            voices = await remote_api.list_voices(req.provider, base, key)
        except Exception as e:
            return error(502, remote_api.explain(e, base))
        return {"base_url": base, "voices": voices}

    @router.post("/remote")
    async def remote_save(req: RemoteSaveRequest):
        if req.provider not in remote_api.PROVIDERS:
            return error(404, "Unknown voice service")
        if req.api_key is not None:
            set_secret(f"tts.{req.provider}", req.api_key.strip() or None)
        persist({"tts.remote.base_url": remote_api.normalize_url(req.base_url, req.provider),
                 "tts.remote.voice": req.voice, "tts.remote.voice_name": req.voice_name or req.voice,
                 "tts.remote.model": req.model or "", "tts.remote.language": req.language or "en",
                 "tts.source": req.provider if req.use else "local"})
        return tts.status()

    @router.post("/source/local")
    async def use_local():
        persist({"tts.source": "local"})
        return tts.status()

    @router.post("/engines/{engine_id}/install")
    async def install(engine_id: str):
        if engine_id not in ENGINES:
            return error(404, "Unknown engine")
        tts.engines.install(engine_id)
        return tts.status()

    @router.post("/engines/{engine_id}/cancel")
    async def cancel(engine_id: str):
        tts.engines.cancel_install(engine_id)
        return tts.status()

    @router.post("/engines/{engine_id}/uninstall")
    async def uninstall(engine_id: str):
        if engine_id not in ENGINES:
            return error(404, "Unknown engine")
        tts.engines.uninstall(engine_id)
        return tts.status()

    @router.post("/engines/{engine_id}/activate")
    async def activate(engine_id: str, req: ActivateRequest):
        try:
            tts.set_engine(engine_id, req.variant)
        except ValueError as e:
            return error(404, str(e))
        persist({"tts.engine": engine_id, "tts.source": "local", **({f"tts.{engine_id}.variant": req.variant} if req.variant else {})})
        return tts.status()

    @router.post("/engines/{engine_id}/stop")
    async def stop(engine_id: str):
        tts.engines.stop(engine_id)
        return tts.status()

    @router.post("/options")
    async def options(req: OptionsRequest):
        if req.speed is not None:
            tts.options["speed"] = max(0.5, min(2.0, float(req.speed)))
            persist({"tts.speed": tts.options["speed"]})
        return tts.status()

    # ------------------------------------------------------------------ voice library

    @router.get("/voices")
    async def voices():
        library = tts.voices.list()
        for v in library:
            v.pop("audio_path", None)
        return {"voices": [v["name"] for v in library], "library": library, "current_voice": tts.current_voice}

    @router.post("/change-voice")
    async def change_voice(req: ChangeVoiceRequest):
        try:
            result = tts.change_voice(req.voice_name)
        except ValueError as e:
            return error(400, str(e))
        persist({"tts.voice": req.voice_name})
        return result

    @router.get("/voices/{name}/audio")
    async def voice_audio(name: str):
        voice = tts.voices.get(name)
        if not voice:
            return error(404, "Voice not found")
        return FileResponse(voice["audio_path"], media_type="audio/wav")

    @router.post("/upload")
    async def upload_voice(
        name: str = Form(...),
        reference_text: str = Form(""),
        reference_language: str = Form("en"),
        replace: bool = Form(False),
        reference_audio: Optional[UploadFile] = File(None),
    ):
        try:
            data = await reference_audio.read() if reference_audio else None
            voice = tts.voices.save(name, data, reference_text, reference_language, replace=replace)
        except FileExistsError as e:
            return error(409, str(e))
        except ValueError as e:
            return error(400, str(e))
        except Exception as e:
            logger.error(f"Error saving voice: {e}", exc_info=True)
            return error(500, f"Failed to save voice: {e}")
        if not tts.current_voice:
            tts.current_voice = voice["name"]
            persist({"tts.voice": voice["name"]})
        voice.pop("audio_path", None)
        return {"message": f"Voice '{voice['name']}' saved", "voice": voice}

    @router.delete("/delete")
    async def delete_voice(req: DeleteVoiceRequest):
        try:
            if not tts.voices.delete(req.name):
                return error(404, "Voice not found")
        except ValueError as e:
            return error(400, str(e))
        if tts.current_voice == req.name:
            remaining = tts.voices.list()
            tts.current_voice = remaining[0]["name"] if remaining else None
            persist({"tts.voice": tts.current_voice})
        return {"message": f"Voice '{req.name}' deleted", "current_voice": tts.current_voice}

    # ------------------------------------------------------------------ synthesis

    @router.post("")
    async def synthesize(req: TTSRequest):
        try:
            audio, media_type = await tts.synthesize(req.text, req.voice, req.engine)
        except LookupError as e:
            return error(409, str(e))
        except ValueError as e:
            return error(422, str(e))
        except Exception as e:
            logger.error(f"TTS failed: {e}")
            return error(500, str(e))
        return Response(audio, media_type=media_type)

    return router
