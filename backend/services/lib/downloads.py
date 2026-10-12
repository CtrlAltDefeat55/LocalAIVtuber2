"""Resumable, cancellable downloads with real progress, plus Hugging Face file resolution.

Partial files are kept as `<name>.part` so an interrupted multi-GB download
continues where it stopped instead of starting over. Cancelling removes the
partial file. Job records are kept in memory only and pruned.
"""
import asyncio
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable, List, Optional
from urllib.parse import quote

import aiohttp

from .LAV_logger import logger
from .paths import hf_token

HF_BASE = "https://huggingface.co"
MAX_FINISHED_JOBS = 20


def hf_headers():
    token = hf_token()
    return {"Authorization": f"Bearer {token}"} if token else {}


def hf_file_url(repo: str, path: str, revision: str = "main") -> str:
    return f"{HF_BASE}/{repo}/resolve/{revision}/{quote(path)}?download=true"


async def hf_list_files(repo: str) -> List[dict]:
    """Return [{'path', 'size'}] for every file in a model repo (recursive)."""
    url = f"{HF_BASE}/api/models/{repo}/tree/main?recursive=true"
    files = []
    async with aiohttp.ClientSession(headers=hf_headers()) as session:
        while url:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                if resp.status == 401 or resp.status == 403:
                    raise PermissionError(
                        f"{repo} is gated or private. Accept its license on huggingface.co and add your token in Settings.")
                if resp.status == 404:
                    raise FileNotFoundError(f"Hugging Face repo '{repo}' not found")
                resp.raise_for_status()
                for item in await resp.json():
                    if item.get("type") == "file":
                        size = (item.get("lfs") or {}).get("size") or item.get("size") or 0
                        files.append({"path": item["path"], "size": size})
                url = resp.links.get("next", {}).get("url") if resp.links else None
    return files


_SPLIT_RE = re.compile(r"-(\d{5})-of-(\d{5})\.gguf$", re.IGNORECASE)


def pick_gguf(files: List[dict], quant: str, exclude: Optional[List[str]] = None) -> List[dict]:
    """Choose the GGUF file(s) for a quant, e.g. 'IQ3_S' or 'UD-Q4_K_XL'.

    Prefers the plainest matching name (variants such as '-mtp' or other
    experimental builds are skipped via `exclude`). Returns every part of a
    split model, first part first.
    """
    q = quant.lower()
    ggufs = [f for f in files if f["path"].lower().endswith(".gguf") and "mmproj" not in f["path"].lower()]

    def matches(name: str) -> bool:
        base = os.path.basename(name).lower()
        # quant must appear as its own token, so 'Q4_K' does not match 'Q4_K_M'
        return re.search(rf"(^|[-_.]){re.escape(q)}([-.]|$)", base) is not None

    candidates = [f for f in ggufs if matches(f["path"])]
    if exclude:
        filtered = [f for f in candidates if not any(x.lower() in f["path"].lower() for x in exclude)]
        candidates = filtered or candidates
    if not candidates:
        return []

    # group split parts by their shared prefix and pick the shortest (plainest) group
    groups = {}
    for f in candidates:
        key = _SPLIT_RE.sub("", f["path"])
        groups.setdefault(key, []).append(f)
    best = min(groups, key=lambda k: (len(os.path.basename(k)), k))
    return sorted(groups[best], key=lambda f: f["path"])


def pick_mmproj(files: List[dict]) -> Optional[dict]:
    projs = [f for f in files if "mmproj" in f["path"].lower() and f["path"].lower().endswith(".gguf")]
    for pref in ("f16", "bf16", "q8_0"):
        for f in projs:
            # whole token only: "f16" must not match "bf16"
            if re.search(rf"(^|[-_.]){pref}([-_.]|$)", os.path.basename(f["path"]).lower()):
                return f
    return projs[0] if projs else None


@dataclass
class DownloadFile:
    url: str
    dest: Path
    size: int = 0


@dataclass
class DownloadJob:
    id: str
    label: str
    files: List[DownloadFile]
    status: str = "starting"  # starting | downloading | completed | error | cancelled
    downloaded: int = 0
    total: int = 0
    error: Optional[str] = None
    started: float = field(default_factory=time.time)
    finished: Optional[float] = None
    current_file: str = ""
    downloaded_this_run: int = 0
    _cancel: asyncio.Event = field(default_factory=asyncio.Event)
    _task: Optional[asyncio.Task] = None

    def to_dict(self):
        elapsed = (self.finished or time.time()) - self.started
        speed = self.downloaded_this_run / elapsed if elapsed > 0 else 0
        return {
            "id": self.id,
            "label": self.label,
            "status": self.status,
            "downloaded_size": self.downloaded,
            "total_size": self.total,
            "progress": (self.downloaded / self.total * 100) if self.total else 0,
            "speed_bps": speed,
            "eta_seconds": ((self.total - self.downloaded) / speed) if speed > 0 and self.total else None,
            "error": self.error,
            "current_file": self.current_file,
            "elapsed_time": elapsed,
        }


class DownloadManager:
    def __init__(self):
        self.jobs: dict[str, DownloadJob] = {}

    def start(self, label: str, files: List[DownloadFile],
              on_complete: Optional[Callable[[], Awaitable[None] | None]] = None) -> DownloadJob:
        for job in self.jobs.values():
            if job.label == label and job.status in ("starting", "downloading"):
                return job  # already running - never start a duplicate
        job = DownloadJob(id=uuid.uuid4().hex[:12], label=label, files=files)
        job.total = sum(f.size for f in files)
        self.jobs[job.id] = job
        job._task = asyncio.create_task(self._run(job, on_complete))
        self._prune()
        return job

    def cancel(self, job_id: str) -> bool:
        job = self.jobs.get(job_id)
        if not job or job.status not in ("starting", "downloading"):
            return False
        job._cancel.set()
        return True

    def active_for(self, label: str) -> Optional[DownloadJob]:
        for job in self.jobs.values():
            if job.label == label and job.status in ("starting", "downloading"):
                return job
        return None

    def _prune(self):
        finished = [j for j in self.jobs.values() if j.finished]
        finished.sort(key=lambda j: j.finished)
        for job in finished[:-MAX_FINISHED_JOBS]:
            self.jobs.pop(job.id, None)

    async def _run(self, job: DownloadJob, on_complete):
        job.status = "downloading"
        try:
            async with aiohttp.ClientSession(headers=hf_headers()) as session:
                done_bytes = 0
                for f in job.files:
                    job.current_file = f.dest.name
                    await self._download_one(session, job, f, done_bytes)
                    done_bytes += f.size or (f.dest.stat().st_size if f.dest.exists() else 0)
            job.status = "completed"
            job.downloaded = job.total = max(job.total, job.downloaded)
            logger.info(f"Download complete: {job.label}")
            if on_complete:
                result = on_complete()
                if asyncio.iscoroutine(result):
                    await result
        except asyncio.CancelledError:
            job.status = "cancelled"
        except _Cancelled:
            job.status = "cancelled"
            for f in job.files:
                Path(str(f.dest) + ".part").unlink(missing_ok=True)
            logger.info(f"Download cancelled: {job.label}")
        except Exception as e:
            job.status = "error"
            job.error = str(e) or e.__class__.__name__
            logger.error(f"Download failed ({job.label}): {job.error}")
        finally:
            job.finished = time.time()

    async def _download_one(self, session, job: DownloadJob, f: DownloadFile, done_before: int):
        if f.dest.exists() and (not f.size or f.dest.stat().st_size == f.size):
            job.downloaded = done_before + f.dest.stat().st_size
            return
        f.dest.parent.mkdir(parents=True, exist_ok=True)
        part = Path(str(f.dest) + ".part")
        have = part.stat().st_size if part.exists() else 0
        headers = {"Range": f"bytes={have}-"} if have else {}
        timeout = aiohttp.ClientTimeout(total=None, sock_connect=30, sock_read=120)
        async with session.get(f.url, headers=headers, timeout=timeout) as resp:
            if resp.status in (401, 403):
                raise PermissionError("Access denied. This model is gated: accept its license on huggingface.co "
                                      "and add your Hugging Face token in Settings.")
            if resp.status == 416:  # already complete
                have = part.stat().st_size
            elif resp.status == 200 and have:
                have = 0  # server ignored the range; start over
            elif resp.status not in (200, 206):
                raise RuntimeError(f"HTTP {resp.status} while downloading {f.dest.name}")
            if not f.size:
                length = int(resp.headers.get("Content-Length", 0))
                f.size = have + length
                job.total = sum(x.size for x in job.files)
            mode = "ab" if have else "wb"
            with open(part, mode) as out:
                if resp.status != 416:
                    async for chunk in resp.content.iter_chunked(1 << 20):
                        if job._cancel.is_set():
                            raise _Cancelled()
                        out.write(chunk)
                        have += len(chunk)
                        job.downloaded_this_run += len(chunk)
                        job.downloaded = done_before + have
        if f.size and have != f.size:
            raise RuntimeError(f"Incomplete download of {f.dest.name} ({have} of {f.size} bytes); retry to resume")
        os.replace(part, f.dest)


class _Cancelled(Exception):
    pass


download_manager = DownloadManager()
