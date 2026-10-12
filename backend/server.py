import sys
import os
import shutil

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

# Must run before any library that reads cache locations is imported.
from services.lib.paths import (APP_ROOT, BACKEND_DIR, FRONTEND_DIST, LLM_MODELS_DIR, SETTINGS_FILE, VOICES_DIR,
                                configure_environment, hf_token, save_hf_token)
configure_environment()

import time
from services.lib.startup_progress import startup_progress
start_time = time.time()
total_start_time = time.time()
startup_progress.show_step("Importing python modules")

import asyncio
import json
import subprocess
import threading
import traceback
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Dict, List, Optional

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile, WebSocket
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from services.Character.characterManager import CharacterManager
from services.ChatFetch.Chatfetch import ChatFetch
from services.Input.Input import VoiceInput
from services.Input.VisionInput import VisionInput
from services.LLM.LLM import LLM
from services.LLM.routes import create_router as create_llm_router
from services.Memory.HistoryStore import HistoryStore
from services.Memory.Memory import Memory
from services.TTS.TTS import TTS
from services.TTS.routes import create_router as create_tts_router
from services.lib.LAV_logger import logger
from services.lib.port_forward import create_proxy_middleware
from services.lib.process_manager import process_manager
from services.lib import hardware
from services.lib.monitor import usage_monitor

APP_VERSION = "3.0.0"
HOST, PORT = "127.0.0.1", int(os.environ.get("LAV_PORT", "8000"))

startup_progress.complete_step(f"Imports completed in {time.time() - start_time:.2f}s")

# *******************************
# RVC plugin (optional, Windows release package only)
# *******************************

rvc_server_port = 8001
rvc_dir = BACKEND_DIR / "plugins" / "rvc"
rvc_runtime_python = rvc_dir / "runtime" / ("python.exe" if sys.platform == "win32" else "bin/python")


def start_rvc():
    if not rvc_runtime_python.exists():
        logger.info("RVC plugin runtime not installed; RVC voice conversion is unavailable.")
        return
    ok, message = process_manager.start_server_process(
        name="RVC", python_path=str(rvc_runtime_python), script_path=str(rvc_dir / "rvc_server.py"),
        port=rvc_server_port, cwd=str(rvc_dir))
    if not ok:
        logger.error(f"Failed to start RVC server: {message}")


app = FastAPI(title="Local AI Vtuber", version=APP_VERSION)
if (FRONTEND_DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")
    app.mount("/resource", StaticFiles(directory=FRONTEND_DIST / "resource"), name="resource")

# Initialize Services (heavy models inside them load lazily on first use)
start_time = time.time()
startup_progress.show_step("Loading AI Services")
voice_input: VoiceInput = VoiceInput()
llm: LLM = LLM()
memory: Memory = Memory()
history_store: HistoryStore = HistoryStore()
tts: TTS = TTS()
vision_input: VisionInput = VisionInput()
character_manager: CharacterManager = CharacterManager()
startup_progress.complete_step(f"AI Services loaded in {time.time() - start_time:.2f}s")

clients = set()
chat_fetch = ChatFetch()
chat_clients = set()

# *******************************
# WebUI
# *******************************

@app.get("/")
async def serve_webui():
    index = FRONTEND_DIST / "index.html"
    if not index.exists():
        return JSONResponse(status_code=503, content={
            "error": "The web interface is not built. Run the start script again, or `npm run build` in frontend/."})
    return FileResponse(index)


@app.get("/{icon_name}")
async def serve_root_file(icon_name: str):
    """Root-level static files from the build (favicon, app icon, manifest)."""
    path = (FRONTEND_DIST / icon_name).resolve()
    if path.parent == FRONTEND_DIST.resolve() and path.is_file():
        return FileResponse(path)
    raise HTTPException(status_code=404)

# *******************************
# Input
# *******************************

@app.post("/api/record/start")
async def start_recording():
    async def run():
        try:
            await voice_input.start_streaming(clients)
        except Exception as e:
            logger.error(f"Microphone input failed: {e}")
            await asyncio.gather(*[c.send_json({"type": "error", "message": f"Microphone failed: {e}"})
                                   for c in list(clients)], return_exceptions=True)
    asyncio.create_task(run())
    return Response(status_code=200)

@app.post("/api/record/stop")
async def stop_recording():
    voice_input.stop_streaming()
    return Response(status_code=200)

@app.websocket("/ws/audio")
async def websocket_audio(websocket: WebSocket):
    await websocket.accept()
    clients.add(websocket)
    try:
        while True:
            await websocket.receive_text()
    except Exception:
        pass
    finally:
        clients.remove(websocket)
        try:
            await websocket.close()
        except RuntimeError:
            pass  # Already closed

@app.get("/api/monitors")
async def get_monitor_info():
    """
    Get information about available monitors.
    """
    try:
        monitors = vision_input.get_monitors()
        logger.info(f"Monitors Server: {monitors}")
            
        monitor_info = []
        for i, monitor in enumerate(monitors):
            # Determine if this is likely the primary monitor
            # Primary monitor usually has left=0 and top=0 or is the first actual monitor
            is_primary = (monitor["left"] == 0 and monitor["top"] == 0)
            
            monitor_info.append({
                "index": i,
                "width": monitor["width"],
                "height": monitor["height"],
                "top": monitor["top"],
                "left": monitor["left"],
                "is_primary": is_primary,
                "description": f"Monitor {i} ({monitor['width']}x{monitor['height']}) at ({monitor['left']}, {monitor['top']})"
            })
        
        return JSONResponse(
            status_code=200,
            content={
                "monitors": monitor_info,
                "count": len(monitors)
            }
        )
    except Exception as e:
        logger.error(f"Error getting monitor info: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to get monitor info: {str(e)}"}
        )

async def process_screenshot_async(monitor_index: int, ocr_scale_factor: float, skip_ocr: bool = False):
    """
    Async wrapper for screenshot processing to avoid blocking the event loop.
    """
    import asyncio
    loop = asyncio.get_event_loop()
    
    # Run the synchronous screenshot processing in a thread pool
    result = await loop.run_in_executor(
        None,
        lambda: vision_input.process_screen(
            monitor_index=monitor_index,
            save_screenshot=False,
            confidence_threshold=0.5,
            ocr_scale_factor=ocr_scale_factor,
            skip_ocr=skip_ocr
        )
    )
    
    return result

@app.get("/api/screenshot")
async def get_screenshot(monitor_index: int = 1, ocr_scale_factor: float = 0.5, skip_ocr: bool = False):
    """
    Capture a screenshot and return the image, caption, and extracted text.
    
    Args:
        monitor_index: Index of the monitor to capture
        ocr_scale_factor: Factor to scale down image for OCR processing (0.1 to 1.0)
        skip_ocr: Whether to skip OCR processing and only generate caption
    """
    try:
        logger.info(f"Screenshot request for monitor index: {monitor_index}, scale factor: {ocr_scale_factor}, skip OCR: {skip_ocr}")
        
        # Validate scale factor
        if ocr_scale_factor < 0.1 or ocr_scale_factor > 1.0:
            return JSONResponse(
                status_code=400,
                content={"error": "OCR scale factor must be between 0.1 and 1.0"}
            )
        
        # Process screen asynchronously using asyncio.create_task
        task = asyncio.create_task(process_screenshot_async(monitor_index, ocr_scale_factor, skip_ocr))
        result = await task
        
        if not result['success']:
            return JSONResponse(
                status_code=500, 
                content={"error": "Failed to capture screenshot"}
            )
        
        # Convert screenshot to base64 for JSON response
        import io
        import base64
        img_byte_arr = io.BytesIO()
        result['screenshot'].save(img_byte_arr, format='PNG')
        img_byte_arr.seek(0)
        image_base64 = base64.b64encode(img_byte_arr.getvalue()).decode('utf-8')
        
        # Extract all detected text
        detected_text = vision_input.get_detected_text(result['ocr_results'])
        
        # Convert numpy types to native Python types for JSON serialization
        def convert_numpy_types(obj):
            if hasattr(obj, 'item'):  # numpy scalar
                return obj.item()
            elif isinstance(obj, (list, tuple)):
                return [convert_numpy_types(item) for item in obj]
            elif isinstance(obj, dict):
                return {key: convert_numpy_types(value) for key, value in obj.items()}
            return obj
        
        # Convert OCR results to ensure JSON serialization
        converted_ocr_results = convert_numpy_types(result['ocr_results'])
        
        # Return JSON response with all data
        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "image": image_base64,
                "caption": result['caption'] or "",
                "extracted_text": detected_text,
                "ocr_count": len(result['ocr_results']),
                "ocr_results": converted_ocr_results,  # Converted OCR data
                "ocr_scale_factor": ocr_scale_factor
            }
        )
        
    except Exception as e:
        logger.error(f"Error capturing screenshot: {e}, {traceback.format_exc()}")
        return JSONResponse(
            status_code=500, 
            content={"error": f"Failed to capture screenshot: {str(e)}"}
        )

# *******************************
# StreamChat
# *******************************

@app.websocket("/ws/streamChat")
async def websocket_chat(websocket: WebSocket):
    await websocket.accept()
    chat_clients.add(websocket)
    try:
        while True:
            await websocket.receive_text()
    except Exception:
        pass
    finally:
        chat_clients.remove(websocket)
        try:
            await websocket.close()
        except RuntimeError:
            pass 

@app.post("/api/streamChat/yt/start")
async def start_fetch_youtube():
    asyncio.create_task(chat_fetch.start_fetching(chat_clients))
    return JSONResponse(status_code=200, content={"message": "Chat fetch started"})

@app.post("/api/streamChat/yt/stop")
async def stop_fetch_youtube():
    chat_fetch.stop_fetching()
    return JSONResponse(status_code=200, content={"message": "Chat fetch stopped"})


# *******************************
# LLM
# *******************************

class LLMRequest(BaseModel):
    text: str
    history: list | None = None
    systemPrompt: str = ""
    screenshot: bool = False

class CompleteResponseRequest(BaseModel):
    history: list
    systemPrompt: str = ""


async def _stream_llm(make_generator, fastapi_request: Request):
    """Load the model if needed, then stream; errors before the first token become a JSON error."""
    try:
        await llm.ensure_loaded()
    except Exception as e:
        return JSONResponse(status_code=503, content={"error": str(e)})
    generator = make_generator()

    async def stream_response():
        try:
            async for chunk in generator:
                if await fastapi_request.is_disconnected():
                    logger.info("Client disconnected, stopping response stream.")
                    break
                yield chunk
        except Exception as e:
            logger.error(f"Error during completion: {e}")
        finally:
            await generator.aclose()

    return StreamingResponse(stream_response(), media_type="text/plain")


@app.post("/api/completion")
async def get_completion(request: LLMRequest, fastapi_request: Request):
    return await _stream_llm(lambda: llm.get_completion(request.text, request.history, request.systemPrompt,
                                                        request.screenshot), fastapi_request)


@app.post("/api/completion/complete")
async def complete_current_response(request: CompleteResponseRequest, fastapi_request: Request):
    return await _stream_llm(lambda: llm.complete_current_response(request.history, request.systemPrompt),
                             fastapi_request)

# *******************************
# Character Models
# *******************************

@app.get("/api/character/live2d/models")
async def get_live2d_models():
    """Get all available Live2D models"""
    try:
        models = character_manager.get_live2d_models()
        return JSONResponse(content={"models": models})
    except Exception as e:
        logger.error(f"Error getting Live2D models: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"error": "Failed to get Live2D models"})

@app.get("/api/character/vrm/models")
async def get_vrm_models():
    """Get all available VRM models"""
    try:
        models = character_manager.get_vrm_models()
        return JSONResponse(content={"models": models})
    except Exception as e:
        logger.error(f"Error getting VRM models: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"error": "Failed to get VRM models"})

@app.get("/api/character/files/{file_path:path}")
async def serve_character_files(file_path: str, request: Request):
    """Serve character model files from backend"""
    try:
        # Get the full request path
        full_path = request.url.path
        
        # Get the absolute file path using CharacterManager
        absolute_path = character_manager.get_file_path(full_path)
        
        if absolute_path is None:
            raise HTTPException(status_code=404, detail="File not found")
        
        return FileResponse(str(absolute_path))
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error serving character file: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/api/character/vrm/upload")
async def upload_vrm_model(file: UploadFile = File(...), replace: bool = Form(False), target_name: str = Form("")):
    """Upload (or with replace=true, update) a VRM model file; target_name keeps the existing file name"""
    try:
        file_data = await file.read()
        success, message = character_manager.upload_vrm_model(file_data, target_name or file.filename, replace=replace)
        
        if success:
            return JSONResponse(status_code=200, content={"message": message})
        else:
            return JSONResponse(status_code=400, content={"error": message})
            
    except Exception as e:
        logger.error(f"Error uploading VRM model: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"error": "Failed to upload model"})

@app.post("/api/character/live2d/upload-zip")
async def upload_live2d_zip(file: UploadFile = File(...), replace: bool = Form(False), target_name: str = Form("")):
    """Install a Live2D model from a .zip archive (target_name replaces that existing model)"""
    try:
        success, message = character_manager.upload_live2d_zip(await file.read(), file.filename, replace=replace,
                                                               target_name=target_name)
        return JSONResponse(status_code=200 if success else 400,
                            content={"message": message} if success else {"error": message})
    except Exception as e:
        logger.error(f"Error uploading Live2D zip: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"error": "Failed to install model"})

@app.post("/api/character/live2d/upload-folder")
async def upload_live2d_folder(files: List[UploadFile] = File(...), replace: bool = Form(False),
                               target_name: str = Form("")):
    """Upload a Live2D model folder"""
    try:
        # Read all files and their relative paths
        file_data = []
        for file in files:
            content = await file.read()
            file_data.append((file.filename, content))
        
        success, message = character_manager.upload_live2d_folder(file_data, replace=replace, target_name=target_name)
        
        if success:
            return JSONResponse(status_code=200, content={"message": message})
        else:
            return JSONResponse(status_code=400, content={"error": message})
            
    except Exception as e:
        logger.error(f"Error uploading Live2D model folder: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"error": "Failed to upload model folder"})

class DeleteCharacterRequest(BaseModel):
    path: str

@app.post("/api/character/vrm/delete")
async def delete_vrm_model(request: DeleteCharacterRequest):
    """Delete a VRM model"""
    try:
        success, message = character_manager.delete_vrm_model(request.path)
        
        if success:
            return JSONResponse(status_code=200, content={"message": message})
        else:
            return JSONResponse(status_code=400, content={"error": message})
            
    except Exception as e:
        logger.error(f"Error deleting VRM model: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"error": "Failed to delete model"})

@app.post("/api/character/live2d/delete")
async def delete_live2d_model(request: DeleteCharacterRequest):
    """Delete a Live2D model folder"""
    try:
        success, message = character_manager.delete_live2d_model(request.path)
        
        if success:
            return JSONResponse(status_code=200, content={"message": message})
        else:
            return JSONResponse(status_code=400, content={"error": message})
            
    except Exception as e:
        logger.error(f"Error deleting Live2D model: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"error": "Failed to delete model"})


# *******************************
# Settings
# *******************************

SAMPLING_KEYS = {"top_k": int, "top_p": float, "min_p": float, "repeat_penalty": float, "temperature": float,
                 "seed": int}
RUNTIME_KEYS = {"llm.context_size": ("context_size", int), "llm.gpu_layers": ("gpu_layers", str),
                "load-llm-cpu": ("cpu_only", bool), "llm.enable_vision": ("enable_vision", bool),
                "llm.thinking": ("thinking", bool), "llm.max_tokens": ("max_tokens", int)}


class SettingsManager:
    def __init__(self, settings_file):
        self.settings_file = str(settings_file)
        self.settings = self.load_settings()
        self._lock = threading.Lock()

    def load_settings(self) -> Dict[str, Any]:
        """settings.json, else the last good copy (settings.json.bak), else built-in defaults."""
        backup = self.settings_file + ".bak"
        for path in (self.settings_file, backup):
            try:
                with open(path, "r", encoding="utf-8") as file:
                    data = json.load(file)
                if not isinstance(data, dict):
                    raise ValueError("not a settings object")
                if path == backup:
                    logger.warning("settings.json was damaged; restored your last saved settings")
                    self.save_settings(data)
                return data
            except FileNotFoundError:
                continue
            except (OSError, ValueError) as e:
                logger.error(f"{os.path.basename(path)} is unreadable ({e})")
                if path == self.settings_file:  # keep the damaged file for inspection
                    try:
                        os.replace(path, self.settings_file + ".damaged")
                    except OSError:
                        pass
        return {}

    def save_settings(self, settings: Dict[str, Any]):
        tmp = self.settings_file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as file:
            json.dump(settings, file, indent=4, ensure_ascii=False)
            file.flush()
            os.fsync(file.fileno())
        if os.path.exists(self.settings_file):
            try:  # last good copy, used if the main file is ever damaged
                shutil.copy2(self.settings_file, self.settings_file + ".bak")
            except OSError:
                pass
        os.replace(tmp, self.settings_file)  # atomic: a crash never leaves a half-written file

    def apply_settings(self, keys=None):
        """Apply settings to the services. Only `keys` are applied when given (all on startup)."""
        s = self.settings
        keys = set(s.keys()) if keys is None else set(keys)

        runtime = {}
        for key, (option, cast) in RUNTIME_KEYS.items():
            if key in keys and key in s:
                try:
                    runtime[option] = cast(s[key]) if cast is not str else str(s[key] or "auto")
                except (TypeError, ValueError):
                    logger.warning(f"Invalid value for {key}: {s[key]!r}")
        if runtime:
            llm.set_runtime_options(**runtime)

        sampling = {}
        for name, cast in SAMPLING_KEYS.items():
            key = f"llm.{name}"
            if key in keys and key in s:
                try:
                    sampling[name] = cast(s[key])
                except (TypeError, ValueError):
                    logger.warning(f"Invalid value for {key}: {s[key]!r}, using default")
        if sampling:
            llm.update_sampling_params(sampling)

        if "llm.keep_model_loaded" in keys and "llm.keep_model_loaded" in s:
            llm.keep_model_loaded = bool(s["llm.keep_model_loaded"])
        model_key = "llm.model_id" if "llm.model_id" in s else "llm.model_filename"
        if model_key in keys and s.get(model_key):
            llm.select_model(s[model_key], load=False)

        remote_llm = {k.split(".")[-1]: s[k] for k in ("llm.remote.preset", "llm.remote.base_url", "llm.remote.model")
                      if k in s and k in keys}
        if remote_llm:
            llm.set_remote(**remote_llm)
        if "llm.provider" in keys and "llm.provider" in s:
            llm.set_provider(s["llm.provider"])

        remote_tts = {k.split(".")[-1]: s[k] for k in ("tts.remote.base_url", "tts.remote.voice", "tts.remote.voice_name",
                                                       "tts.remote.model", "tts.remote.language") if k in s and k in keys}
        if remote_tts:
            tts.remote.update(remote_tts)
            tts.remote_error = None
        if "tts.source" in keys and "tts.source" in s:
            tts.set_source(s["tts.source"])

        if "stream.yt.videoid" in keys and "stream.yt.videoid" in s:
            chat_fetch.video_id = s["stream.yt.videoid"]
        if "tts.speed" in keys and "tts.speed" in s:
            tts.options["speed"] = float(s["tts.speed"])
        for engine_id in ("tada",):
            if f"tts.{engine_id}.variant" in s:
                tts.variants[engine_id] = s[f"tts.{engine_id}.variant"]
        if "tts.engine" in keys and s.get("tts.engine"):
            try:
                tts.set_engine(s["tts.engine"], start=False)
            except ValueError:
                logger.warning(f"Unknown voice engine in settings: {s['tts.engine']}")
        if "tts.voice" in keys and s.get("tts.voice"):
            try:
                tts.change_voice(s["tts.voice"])
            except ValueError:
                logger.warning(f"Saved voice '{s['tts.voice']}' not found, keeping {tts.current_voice}")

    def update_settings(self, updated_settings: Dict[str, Any]):
        with self._lock:
            self.settings.update(updated_settings)
            self.save_settings(self.settings)
        self.apply_settings(updated_settings.keys())
        # selecting a model from the Brain page should also load it when "keep loaded" is on
        if {"llm.model_id", "llm.model_filename"} & updated_settings.keys() and llm.keep_model_loaded:
            if (llm.current_model_data or {}).get("file_exists"):
                llm.load_in_background()


settings_manager = SettingsManager(SETTINGS_FILE)
start_time = time.time()
startup_progress.show_step("Applying Settings")
settings_manager.apply_settings()
startup_progress.complete_step(f"Settings applied in {time.time() - start_time:.2f}s")

app.include_router(create_llm_router(llm, lambda values: settings_manager.update_settings(values)))
app.include_router(create_tts_router(tts, lambda values: settings_manager.update_settings(values)))


class UpdateSettingsRequest(BaseModel):
    settings: Dict[str, Any]

@app.post("/api/settings/update")
async def update_settings(request: UpdateSettingsRequest):
    try:
        settings_manager.update_settings(request.settings)
        return JSONResponse(content={"status": "ok", "message": "Settings updated successfully"})
    except ValueError as ve:
        logger.error(f"Validation error: {ve}, traceback: {traceback.format_exc()}")
        return JSONResponse(status_code=400, content={"error": str(ve)})
    except Exception as e:
        logger.error(f"Error updating settings: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"error": "Failed to update settings"})

@app.get("/api/settings")
async def get_settings():
    return JSONResponse(content={"settings": settings_manager.settings})


class TokenRequest(BaseModel):
    token: Optional[str] = None

@app.get("/api/settings/hf-token")
async def get_hf_token():
    token = hf_token()
    return {"has_token": bool(token), "hint": f"hf_...{token[-4:]}" if token else None}

@app.post("/api/settings/hf-token")
async def set_hf_token(request: TokenRequest):
    token = (request.token or "").strip()
    if token and not token.startswith("hf_"):
        return JSONResponse(status_code=400, content={"error": "Hugging Face tokens start with 'hf_'"})
    save_hf_token(token or None)
    return await get_hf_token()

# *******************************
# System: status, folders, quit
# *******************************

uvicorn_server: Optional[uvicorn.Server] = None

@app.get("/api/system/status")
async def system_status():
    return {
        "version": APP_VERSION,
        "llm": llm.status(),
        "tts": tts.summary(),
        "gpu": {k: v for k, v in tts.gpu.items() if k != "index"},
        "platform": sys.platform,
    }

_hardware_cache: Dict[str, Any] = {}

@app.get("/api/system/hardware")
async def system_hardware(refresh: bool = False):
    """What this computer has and which models/voices will run well on it."""
    if refresh or "info" not in _hardware_cache:
        _hardware_cache["info"] = await asyncio.to_thread(hardware.scan)
    info = dict(_hardware_cache["info"])
    llm._load_available_models()
    info["recommendation"] = hardware.recommend(info, llm.all_model_data)
    return info

@app.get("/api/system/usage")
async def system_usage():
    """Live CPU / RAM / GPU use split by LLM, voice, app window, this app and other programs."""
    gpu_info = _hardware_cache.get("info", {}).get("gpus", [])
    return await asyncio.to_thread(usage_monitor.sample, gpu_info)

class WindowRequest(BaseModel):
    pid: int

@app.post("/api/system/window")
async def register_window(request: WindowRequest):
    """The launcher reports the app-window browser process so its usage shows as 'Character window'."""
    usage_monitor.register_window(request.pid)
    return {"ok": True}

FOLDERS = {
    "models": LLM_MODELS_DIR,
    "voices": VOICES_DIR,
    "live2d": character_manager.live2d_path,
    "vrm": character_manager.vrm_path,
    "app": APP_ROOT,
}

class FolderRequest(BaseModel):
    which: str

@app.post("/api/system/open-folder")
async def open_folder(request: FolderRequest):
    folder = FOLDERS.get(request.which)
    if not folder:
        return JSONResponse(status_code=404, content={"error": "Unknown folder"})
    os.makedirs(folder, exist_ok=True)
    try:
        if sys.platform == "win32":
            os.startfile(folder)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(folder)])
        else:
            subprocess.Popen(["xdg-open", str(folder)])
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Could not open folder: {e}", "path": str(folder)})
    return {"path": str(folder)}

@app.post("/api/system/shutdown")
async def shutdown():
    """Quit the whole app: stops the model, voice engines and this server."""
    logger.info("Shutdown requested from the app")

    async def stop_soon():
        await asyncio.sleep(0.3)  # let this response reach the browser
        voice_input.stop_streaming()
        chat_fetch.stop_fetching()
        await asyncio.to_thread(process_manager.stop_all_servers)
        if uvicorn_server:
            uvicorn_server.should_exit = True
        else:
            os._exit(0)

    asyncio.create_task(stop_soon())
    return {"message": "Shutting down"}


async def warm_up():
    """Load the model and voice in the background so the UI is usable immediately."""
    threading.Thread(target=start_rvc, daemon=True).start()
    if llm.keep_model_loaded and (llm.current_model_data or {}).get("file_exists"):
        llm.load_in_background()
    if tts.source == "local" and tts.engines.is_installed(tts.active_engine):
        tts.start_in_background()
    _hardware_cache["info"] = await asyncio.to_thread(hardware.scan)
    startup_progress.complete_step(
        f"Server ready in {time.time() - total_start_time:.2f}s at {datetime.now().strftime('%H:%M:%S')} "
        f"- open http://{HOST}:{PORT}")


@asynccontextmanager
async def lifespan(_app):
    await warm_up()
    yield
    await asyncio.to_thread(process_manager.stop_all_servers)

app.router.lifespan_context = lifespan

# *******************************
# Chat History API
# *******************************

class CreateSessionRequest(BaseModel):
    title: str

@app.post("/api/chat/session/create")
async def create_chat_session(request: CreateSessionRequest):
    try:
        session = history_store.create_session(request.title)
        return JSONResponse(status_code=200, content=session)
    except Exception as e:
        logger.error(f"Error creating chat session: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"error": "Failed to create chat session"})

class UpdateSessionRequest(BaseModel):
    session_id: str
    history: List[Dict[str, str]]

@app.post("/api/chat/session/update")
async def update_chat_session(request: UpdateSessionRequest):
    try:
        success = history_store.update_session(request.session_id, request.history)
        if success:
            return JSONResponse(status_code=200, content={"message": "Session updated successfully"})
        return JSONResponse(status_code=404, content={"error": "Session not found"})
    except Exception as e:
        logger.error(f"Error updating chat session: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"error": "Failed to update chat session"})

class UpdateSessionTitleRequest(BaseModel):
    session_id: str
    title: str

@app.post("/api/chat/session/update-title")
async def update_chat_session_title(request: UpdateSessionTitleRequest):
    try:
        success = history_store.update_session_title(request.session_id, request.title)
        if success:
            return JSONResponse(status_code=200, content={"message": "Session title updated successfully"})
        return JSONResponse(status_code=404, content={"error": "Session not found"})
    except Exception as e:
        logger.error(f"Error updating chat session title: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"error": "Failed to update chat session title"})

@app.get("/api/chat/sessions")
async def get_chat_sessions():
    try:
        sessions = history_store.get_session_list()
        return JSONResponse(status_code=200, content=sessions)
    except Exception as e:
        logger.error(f"Error getting chat sessions: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"error": "Failed to get chat sessions"})

@app.get("/api/chat/session/{session_id}")
async def get_chat_session(session_id: str):
    try:
        session = history_store.get_session_history(session_id)
        if session:
            return JSONResponse(status_code=200, content=session)
        return JSONResponse(status_code=404, content={"error": "Session not found"})
    except Exception as e:
        logger.error(f"Error getting chat session: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"error": "Failed to get chat session"})

@app.delete("/api/chat/session/{session_id}")
async def delete_chat_session(session_id: str):
    try:
        success = history_store.delete_session(session_id)
        if success:
            return JSONResponse(status_code=200, content={"message": "Session deleted successfully"})
        return JSONResponse(status_code=404, content={"error": "Session not found"})
    except Exception as e:
        logger.error(f"Error deleting chat session: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"error": "Failed to delete chat session"})

# *******************************
# Session Indexing API
# *******************************

class IndexSessionRequest(BaseModel):
    session_id: str
    window_size: int = 3
    stride: int = 1
    format_style: str = "simple"

@app.post("/api/chat/session/{session_id}/index")
async def index_chat_session(session_id: str, request: IndexSessionRequest):
    try:
        # Get the session history
        session = history_store.get_session_history(session_id)
        if not session:
            return JSONResponse(status_code=404, content={"error": "Session not found"})
        
        history = session.get("history", [])
        if not history:
            return JSONResponse(status_code=400, content={"error": "Session has no history to index"})
        
        # Insert the history into memory using the new chunking functionality
        response = memory.insert_history(
            history=history,
            session_id=session_id,
            window_size=request.window_size,
            stride=request.stride,
            format_style=request.format_style
        )
        
        if response is None:
            return JSONResponse(status_code=500, content={"error": "Failed to index session"})
        
        # Mark the session as indexed
        history_store.mark_session_indexed(session_id, True)
        
        return JSONResponse(status_code=200, content={
            "message": "Session indexed successfully",
            "chunks_created": len(history) // request.window_size + 1 if len(history) > 0 else 0
        })
        
    except Exception as e:
        logger.error(f"Error indexing chat session: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"error": "Failed to index chat session"})

@app.delete("/api/chat/session/{session_id}/index")
async def remove_session_index(session_id: str):
    try:
        # Check if session exists
        session = history_store.get_session_history(session_id)
        if not session:
            return JSONResponse(status_code=404, content={"error": "Session not found"})
        
        # Remove all messages for this session from memory
        success = memory.delete_session_messages(session_id)
        
        if not success:
            return JSONResponse(status_code=500, content={"error": "Failed to remove session from memory"})
        
        # Mark the session as not indexed
        history_store.mark_session_indexed(session_id, False)
        
        return JSONResponse(status_code=200, content={"message": "Session index removed successfully"})
        
    except Exception as e:
        logger.error(f"Error removing session index: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"error": "Failed to remove session index"})

@app.get("/api/chat/session/{session_id}/index/status")
async def get_session_index_status(session_id: str):
    try:
        session = history_store.get_session_history(session_id)
        if not session:
            return JSONResponse(status_code=404, content={"error": "Session not found"})
        
        return JSONResponse(status_code=200, content={
            "session_id": session_id,
            "indexed": session.get("indexed", False),
            "indexed_at": session.get("indexed_at"),
            "message_count": len(session.get("history", []))
        })
        
    except Exception as e:
        logger.error(f"Error getting session index status: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"error": "Failed to get session index status"})

@app.get("/api/chat/session/{session_id}/indexed")
async def get_indexed_chunks(session_id: str):
    try:
        # Fetch all indexed chunks for the session
        chunks = memory.query_by_session(session_id, limit=1000)
        return JSONResponse(status_code=200, content={"chunks": chunks})
    except Exception as e:
        logger.error(f"Error getting indexed chunks for session {session_id}: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"error": "Failed to get indexed chunks"})

@app.post("/api/chat/reindex-all")
async def reindex_all_sessions():
    try:
        # Get all sessions
        sessions = history_store.get_session_list()
        if not sessions:
            return JSONResponse(status_code=200, content={"message": "No sessions to reindex"})
        
        # Delete all existing indexes
        success = memory.delete_all_messages()
        if not success:
            return JSONResponse(status_code=500, content={"error": "Failed to delete existing indexes"})
        
        # Mark all sessions as not indexed
        for session in sessions:
            history_store.mark_session_indexed(session["id"], False)
        
        # Reindex all sessions with history
        reindexed_count = 0
        failed_sessions = []
        
        for session in sessions:
            try:
                session_data = history_store.get_session_history(session["id"])
                if session_data and session_data.get("history"):
                    # Insert the history into memory
                    response = memory.insert_history(
                        history=session_data["history"],
                        session_id=session["id"],
                        window_size=3,
                        stride=1,
                        format_style="simple"
                    )
                    
                    if response is not None:
                        # Mark the session as indexed
                        history_store.mark_session_indexed(session["id"], True)
                        reindexed_count += 1
                    else:
                        failed_sessions.append(session["id"])
                else:
                    failed_sessions.append(session["id"])
            except Exception as e:
                logger.error(f"Error reindexing session {session['id']}: {e}")
                failed_sessions.append(session["id"])
        
        return JSONResponse(status_code=200, content={
            "message": "Reindexing completed",
            "reindexed_count": reindexed_count,
            "failed_sessions": failed_sessions,
            "total_sessions": len(sessions)
        })
        
    except Exception as e:
        logger.error(f"Error reindexing all sessions: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"error": "Failed to reindex all sessions"})

# *******************************
# Memory - Context Query API
# *******************************

class QueryContextRequest(BaseModel):
    text: str
    limit: int = 3

@app.post("/api/memory/context")
async def query_memory_context(request: QueryContextRequest):
    try:
        response = memory.query(text=request.text, limit=request.limit)
        return JSONResponse(status_code=200, content={"context": response})
    except Exception as e:
        logger.error(f"Error querying memory context: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"error": "Failed to query memory context"})

# Add RVC proxy middleware
app.middleware("http")(create_proxy_middleware("/api/rvc", rvc_server_port))

if __name__ == "__main__":
    config = uvicorn.Config(app, host=HOST, port=PORT, log_level="warning")
    uvicorn_server = uvicorn.Server(config)
    try:
        uvicorn_server.run()
    finally:
        process_manager.stop_all_servers()
