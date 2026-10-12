"""HTTP API for the Voice page: engines, the voice library and synthesis."""
from typing import Callable, Optional

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel

from services.lib.LAV_logger import logger
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
        persist({"tts.engine": engine_id, **({f"tts.{engine_id}.variant": req.variant} if req.variant else {})})
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
            audio = await tts.synthesize(req.text, req.voice, req.engine)
        except LookupError as e:
            return error(409, str(e))
        except ValueError as e:
            return error(422, str(e))
        except Exception as e:
            logger.error(f"TTS failed: {e}")
            return error(500, str(e))
        return Response(audio, media_type="audio/wav")

    return router
