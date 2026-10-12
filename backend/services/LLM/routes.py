"""HTTP API for the Brain (LLM) page: catalog, downloads, selection, runtime state."""
import json
import os
import re
import shutil
from pathlib import Path
from typing import Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from services.lib.LAV_logger import logger
from services.lib.downloads import (DownloadFile, download_manager, hf_file_url, hf_list_files, pick_gguf,
                                    pick_mmproj)
from services.lib.secrets import get_secret, set_secret, storage_name
from . import remote as remote_api
from .LLM import LLM


class ModelRef(BaseModel):
    model_id: str


class RemoteTestRequest(BaseModel):
    preset: str = "custom"
    base_url: str
    api_key: Optional[str] = None  # None = use the saved key


class RemoteSaveRequest(BaseModel):
    preset: str = "custom"
    base_url: str
    model: str
    api_key: Optional[str] = None  # None = keep saved key, "" = remove it
    use: bool = True


class HFRepoRequest(BaseModel):
    repo: str


class AddHFModelRequest(BaseModel):
    repo: str
    file: str
    mmproj: Optional[str] = None
    displayName: Optional[str] = None


def _clean_repo(repo: str) -> str:
    repo = repo.strip()
    repo = re.sub(r"^https?://huggingface\.co/", "", repo)
    repo = repo.split("?")[0].strip("/")
    parts = repo.split("/")
    if len(parts) < 2 or not all(re.fullmatch(r"[\w.\-]+", p) for p in parts[:2]):
        raise ValueError("Enter a Hugging Face repo like 'owner/model-name-GGUF'")
    return "/".join(parts[:2])


async def resolve_files(model: dict) -> tuple[list[DownloadFile], dict]:
    folder = Path(model["model_folder"])
    if model.get("link"):
        name = model["fileName"]
        return [DownloadFile(url=model["link"], dest=folder / name)], {"fileName": name}
    repo = model["repo"]
    listing = await hf_list_files(repo)
    if model.get("files"):
        wanted = set(model["files"])
        chosen = [f for f in listing if f["path"] in wanted]
    else:
        chosen = []
        for quant in [model["quant"], *model.get("fallback_quants", [])]:
            chosen = pick_gguf(listing, quant, model.get("exclude"))
            if chosen:
                break
    if not chosen:
        raise FileNotFoundError(f"No GGUF file for quant '{model.get('quant')}' found in {repo}")
    files = [DownloadFile(url=hf_file_url(repo, f["path"]), dest=folder / os.path.basename(f["path"]),
                          size=f["size"], sha256=f.get("sha256")) for f in chosen]
    local = {"fileName": os.path.basename(chosen[0]["path"]),
             "parts": [os.path.basename(f["path"]) for f in chosen]}
    proj_path = model.get("mmproj_file")
    proj = next((f for f in listing if f["path"] == proj_path), None) if proj_path else (
        pick_mmproj(listing) if model.get("vision") else None)
    if proj:
        files.append(DownloadFile(url=hf_file_url(repo, proj["path"]), dest=folder / "mmproj.gguf",
                                  size=proj["size"], sha256=proj.get("sha256")))
        local["mmproj_path"] = "mmproj.gguf"
    return files, local

def start_download(llm: LLM, model: dict, files, local: dict):
    folder = Path(model["model_folder"])

    def finished():
        with open(folder / "local.json", "w", encoding="utf-8") as f:
            json.dump(local, f, indent=2)
        llm._load_available_models()

    return download_manager.start(f"llm:{model['id']}", files, on_complete=finished)



def create_router(llm: LLM, persist=None) -> APIRouter:
    router = APIRouter(prefix="/api/llm")

    # ------------------------------------------------------------------ remote API (LM Studio, OpenAI, ...)

    @router.get("/remote")
    async def remote_info():
        return {"presets": remote_api.PRESETS, "provider": llm.provider, "remote": llm.remote,
                "has_key": bool(get_secret("llm.remote")), "key_storage": storage_name()}

    @router.post("/remote/test")
    async def remote_test(req: RemoteTestRequest):
        base = remote_api.normalize_url(req.base_url, req.preset)
        if not base:
            return JSONResponse(status_code=400, content={"error": "Enter the server address first."})
        key = req.api_key if req.api_key is not None else get_secret("llm.remote")
        try:
            models = await remote_api.list_models(base, key)
        except Exception as e:
            return JSONResponse(status_code=502, content={"error": remote_api.explain(e, base), "base_url": base})
        return {"base_url": base, "models": models}

    @router.post("/remote")
    async def remote_save(req: RemoteSaveRequest):
        if req.api_key is not None:
            set_secret("llm.remote", req.api_key.strip() or None)
        values = {"llm.remote.preset": req.preset,
                  "llm.remote.base_url": remote_api.normalize_url(req.base_url, req.preset),
                  "llm.remote.model": req.model.strip(),
                  "llm.provider": "remote" if req.use else "local"}
        if persist:
            persist(values)
        else:
            llm.set_remote(preset=req.preset, base_url=req.base_url, model=req.model)
            llm.set_provider(values["llm.provider"])
        return llm.status()

    @router.post("/provider/local")
    async def use_local():
        if persist:
            persist({"llm.provider": "local"})
        else:
            llm.set_provider("local")
        return llm.status()

    def snapshot():
        llm._load_available_models()
        for m in llm.all_model_data:
            job = download_manager.active_for(f"llm:{m['id']}")
            m["download"] = job.to_dict() if job else None
        return {"models": llm.all_model_data, "currentModel": llm.current_model_data, "status": llm.status()}

    @router.get("/models")
    async def get_models():
        return snapshot()

    @router.get("/status")
    async def get_status():
        return llm.status()

    @router.post("/select")
    async def select(req: ModelRef):
        if not llm.select_model(req.model_id):
            return JSONResponse(status_code=404, content={"error": "Model not found"})
        return snapshot()

    @router.post("/load")
    async def load():
        model = llm.current_model_data
        if not model or not model.get("file_exists"):
            return JSONResponse(status_code=400, content={"error": "Download the selected model first."})
        llm.load_in_background()
        return llm.status()

    @router.post("/unload")
    async def unload():
        llm.unload_model()
        return llm.status()

    # ------------------------------------------------------------------ downloads

    @router.post("/models/download")
    async def download(req: ModelRef):
        llm._load_available_models()
        model = llm.get_model(req.model_id)
        if not model:
            return JSONResponse(status_code=404, content={"error": "Model not found"})
        if not model.get("downloadable"):
            return JSONResponse(status_code=400, content={"error": "This model has no download source"})
        try:
            files, local = await resolve_files(model)
        except PermissionError as e:
            return JSONResponse(status_code=403, content={"error": str(e)})
        except Exception as e:
            logger.error(f"Could not resolve download for {model['id']}: {e}")
            return JSONResponse(status_code=502, content={"error": f"Could not reach Hugging Face: {e}"})
        job = start_download(llm, model, files, local)
        return {"message": "Download started", "download_id": job.id, "download": job.to_dict()}

    @router.get("/models/download/{download_id}/progress")
    async def progress(download_id: str):
        job = download_manager.jobs.get(download_id)
        if not job:
            return JSONResponse(status_code=404, content={"error": "Download ID not found"})
        return job.to_dict()

    @router.delete("/models/download/{download_id}")
    async def cancel(download_id: str):
        if not download_manager.cancel(download_id):
            return JSONResponse(status_code=400, content={"error": "Download is not running"})
        return {"message": "Cancelling"}

    @router.get("/models/downloads")
    async def downloads():
        return {"downloads": {k: j.to_dict() for k, j in download_manager.jobs.items()}}

    @router.delete("/models/delete")
    async def delete(req: ModelRef):
        llm._load_available_models()
        model = llm.get_model(req.model_id)
        if not model:
            return JSONResponse(status_code=404, content={"error": "Model not found"})
        if llm.loaded_model_id == model["id"]:
            llm.unload_model()
        folder = Path(model["model_folder"])
        if model.get("custom"):
            shutil.rmtree(folder, ignore_errors=True)  # user-added entry: remove completely
        else:
            for name in set((model.get("parts") or []) + [model.get("fileName") or "", model.get("mmproj_path") or ""]):
                if name:
                    (folder / name).unlink(missing_ok=True)
            (folder / "local.json").unlink(missing_ok=True)
        logger.info(f"Deleted model files for {model['id']}")
        return snapshot()

    # ------------------------------------------------------------------ add any GGUF from Hugging Face

    @router.post("/models/hf/files")
    async def hf_files(req: HFRepoRequest):
        try:
            repo = _clean_repo(req.repo)
            listing = await hf_list_files(repo)
        except ValueError as e:
            return JSONResponse(status_code=400, content={"error": str(e)})
        except PermissionError as e:
            return JSONResponse(status_code=403, content={"error": str(e)})
        except FileNotFoundError as e:
            return JSONResponse(status_code=404, content={"error": str(e)})
        except Exception as e:
            return JSONResponse(status_code=502, content={"error": f"Could not reach Hugging Face: {e}"})
        ggufs = [f for f in listing if f["path"].lower().endswith(".gguf")]
        models = [f for f in ggufs if "mmproj" not in f["path"].lower()
                  and not re.search(r"-0000[2-9]-of-\d{5}\.gguf$", f["path"].lower())]
        projs = [f for f in ggufs if "mmproj" in f["path"].lower()]
        if not models:
            return JSONResponse(status_code=404, content={"error": "That repo has no GGUF files."})
        return {"repo": repo, "files": models, "mmproj": projs}

    @router.post("/models/add-hf")
    async def add_hf(req: AddHFModelRequest):
        try:
            repo = _clean_repo(req.repo)
            listing = await hf_list_files(repo)
        except Exception as e:
            return JSONResponse(status_code=400, content={"error": str(e)})
        first = next((f for f in listing if f["path"] == req.file), None)
        if not first:
            return JSONResponse(status_code=404, content={"error": "File not found in repo"})
        split = re.search(r"-(\d{5})-of-(\d{5})\.gguf$", req.file)
        paths = [req.file]
        if split:
            prefix = req.file[:split.start()]
            paths = sorted(f["path"] for f in listing if f["path"].startswith(prefix) and "-of-" in f["path"])
        base = re.sub(r"[^\w.\-]+", "_", os.path.splitext(os.path.basename(req.file))[0])[:80]
        folder = Path(llm.models_directory) / "custom" / base
        folder.mkdir(parents=True, exist_ok=True)
        metadata = {"displayName": req.displayName or base, "description": f"Added from {repo}",
                    "repo": repo, "files": paths, "type": "text", "custom": True,
                    "vision": bool(req.mmproj), "mmproj_file": req.mmproj, "order": 50}
        with open(folder / "metadata.json", "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=4)
        llm._load_available_models()
        model = llm.get_model(f"custom/{base}")
        files, local = await resolve_files(model)
        job = start_download(llm, model, files, local)
        return {"model_id": model["id"], "download_id": job.id, **snapshot()}

    return router
