"""Find missing or damaged files so setup can repair them instead of starting over.

Standard library only: the launcher loads this file directly (before the app's
Python environment exists), and the backend imports it normally.

* Python environments: every installed package lists its files with size and
  SHA-256 in `*.dist-info/RECORD`. A quick check compares sizes (and that each
  file exists); a deep check also re-hashes them. Broken packages are returned
  as requirements that `uv pip install --reinstall-package` can put back.
* App files: the release zip ships `launcher/manifest.json` with the size and
  SHA-256 of every file in it.
"""
import base64
import csv
import hashlib
import json
import os
import sys
from pathlib import Path


def sha256_file(path, chunk=1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            block = f.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


# ---------------------------------------------------------------------------- python environments

def site_packages(env: Path) -> list:
    env = Path(env)
    if (env / "Lib" / "site-packages").is_dir():
        return [env / "Lib" / "site-packages"]
    return sorted(p for p in (env / "lib").glob("python3*/site-packages") if p.is_dir())


def _requirement(dist_info: Path, name: str, version: str) -> str:
    """How to ask uv for exactly this package again (keeps git/URL installs on their URL)."""
    try:
        direct = json.loads((dist_info / "direct_url.json").read_text(encoding="utf-8"))
        url = direct.get("url", "")
        if url and not url.startswith("file:") and not direct.get("dir_info"):
            vcs = direct.get("vcs_info")
            if vcs:
                url = f"{vcs.get('vcs', 'git')}+{url}@{vcs.get('commit_id', '')}".rstrip("@")
            return f"{name} @ {url}"
    except (OSError, ValueError):
        pass
    return f"{name}=={version}"


def _metadata(dist_info: Path):
    name = version = None
    try:
        with open(dist_info / "METADATA", encoding="utf-8", errors="replace") as f:
            for line in f:
                if not line.strip():
                    break
                if line.startswith("Name:"):
                    name = line.split(":", 1)[1].strip()
                elif line.startswith("Version:"):
                    version = line.split(":", 1)[1].strip()
    except OSError:
        pass
    if not name or not version:  # fall back to the folder name: name-version.dist-info
        stem = dist_info.name[:-len(".dist-info")]
        n, _, v = stem.rpartition("-")
        name, version = name or n, version or v
    return name, version


def check_env(env: Path, deep: bool = False, progress=None) -> list:
    """Return [{'name', 'version', 'requirement', 'problems': [...]}] for damaged packages.

    Only files inside site-packages are checked: launcher scripts in bin/Scripts are
    rewritten for relocatable environments, so their recorded hashes never match.
    """
    broken = []
    for sp in site_packages(env):
        dists = sorted(sp.glob("*.dist-info"))
        for i, dist_info in enumerate(dists):
            if progress:
                progress(i + 1, len(dists))
            name, version = _metadata(dist_info)
            problems = []
            record = dist_info / "RECORD"
            if not (dist_info / "METADATA").exists():
                problems.append("METADATA missing")
            try:
                with open(record, encoding="utf-8", newline="") as f:
                    rows = list(csv.reader(f))
            except OSError:
                rows = []
                problems.append("RECORD missing")
            for row in rows:
                if len(row) < 3 or not row[1] or row[0].startswith(".."):
                    continue
                path = sp / row[0]
                algo, _, digest = row[1].partition("=")
                try:
                    size = path.stat().st_size
                except OSError:
                    problems.append(f"missing {row[0]}")
                    continue
                if row[2] and row[2].isdigit() and int(row[2]) != size:
                    problems.append(f"wrong size {row[0]}")
                elif deep and algo == "sha256":
                    want = base64.urlsafe_b64decode(digest + "=" * (-len(digest) % 4)).hex()
                    if sha256_file(path) != want:
                        problems.append(f"corrupted {row[0]}")
                if len(problems) > 20:
                    break
            if problems:
                broken.append({"name": name, "version": version,
                               "requirement": _requirement(dist_info, name, version), "problems": problems})
    return broken


# ---------------------------------------------------------------------------- app files

MANIFEST_NAME = "manifest.json"

# Files the app or the user is expected to change, move or delete; never "repaired".
USER_DATA_PREFIXES = (
    "backend/settings.json",
    "backend/services/Character/live2D/models/",
    "backend/services/Character/VRM3D/models/",
    "backend/services/TTS/GPTsovits/models/",
)
START_SCRIPTS = ("Start Windows.bat", "Start Mac.command", "Start Linux.sh")


def is_user_data(rel: str) -> bool:
    return rel in START_SCRIPTS or rel.startswith(USER_DATA_PREFIXES)


def build_manifest(root: Path, files, version: str, repo: str = "") -> dict:
    entries = {}
    for rel in sorted(set(files)):
        p = Path(root) / rel
        if p.is_file() and rel != f"launcher/{MANIFEST_NAME}":
            entries[rel] = {"size": p.stat().st_size, "sha256": sha256_file(p)}
    return {"version": version, "repo": repo, "files": entries}


def check_app_files(root: Path, manifest: dict, deep: bool = False) -> list:
    """Relative paths of shipped app files that are missing or damaged."""
    bad = []
    for rel, meta in manifest.get("files", {}).items():
        if is_user_data(rel):
            continue
        p = Path(root) / rel
        try:
            if p.stat().st_size != meta["size"]:
                bad.append(rel)
            elif deep and sha256_file(p) != meta["sha256"]:
                bad.append(rel)
        except OSError:
            bad.append(rel)
    return bad


if __name__ == "__main__":  # python integrity.py <env> [--deep]
    for item in check_env(Path(sys.argv[1]), deep="--deep" in sys.argv):
        print(item["requirement"], "-", "; ".join(item["problems"][:3]))
