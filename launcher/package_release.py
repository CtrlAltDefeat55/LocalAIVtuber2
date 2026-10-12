"""Build the single downloadable zip: python launcher/package_release.py [--skip-build]

Contains the tracked source, the prebuilt web UI (so users never need Node.js),
the start scripts and icons. Runtimes and models are fetched on first start.
"""
import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOP = "LocalAIVtuber"
EXECUTABLE = {"Start Linux.sh", "Start Mac.command"}


def version():
    m = re.search(r'APP_VERSION = "([^"]+)"', (ROOT / "backend" / "server.py").read_text(encoding="utf-8"))
    return m.group(1) if m else "dev"


def github_repo():
    """owner/name used to fetch replacement files; from Actions, or the git remote."""
    if os.environ.get("GITHUB_REPOSITORY"):
        return os.environ["GITHUB_REPOSITORY"]
    url = subprocess.run(["git", "remote", "get-url", "origin"], cwd=ROOT, capture_output=True, text=True).stdout
    m = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?\s*$", url)
    return m.group(1) if m else ""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-build", action="store_true", help="use the existing frontend/dist")
    args = parser.parse_args()

    frontend = ROOT / "frontend"
    if not args.skip_build:
        npm = shutil.which("npm")
        if not npm:
            sys.exit("npm is required to build the web UI")
        subprocess.run([npm, "ci"], cwd=frontend, check=True, shell=sys.platform == "win32")
        subprocess.run([npm, "run", "build"], cwd=frontend, check=True, shell=sys.platform == "win32")
    dist = frontend / "dist"
    if not (dist / "index.html").exists():
        sys.exit("frontend/dist is missing; run without --skip-build")

    tracked = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True).stdout
    files = [f for f in tracked.decode("utf-8").split("\0") if f and not f.startswith(".github/")]
    files += [str(p.relative_to(ROOT)).replace("\\", "/") for p in dist.rglob("*") if p.is_file()]

    out_dir = ROOT / "dist"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / f"{TOP}-v{version()}.zip"
    # Size + SHA-256 of every shipped file, so the launcher can find and restore damaged ones.
    spec = importlib.util.spec_from_file_location("integrity", ROOT / "backend/services/lib/integrity.py")
    integrity = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(integrity)
    manifest = integrity.build_manifest(ROOT, files, version(), github_repo())
    files = [f for f in files if f != "launcher/manifest.json"]
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for rel in sorted(set(files)):
            src = ROOT / rel
            if not src.is_file():
                continue
            info = zipfile.ZipInfo.from_file(src, f"{TOP}/{rel}")
            mode = 0o755 if Path(rel).name in EXECUTABLE else 0o644
            info.external_attr = (0o100000 | mode) << 16  # keep the Mac/Linux start scripts executable
            info.compress_type = zipfile.ZIP_DEFLATED
            with open(src, "rb") as fh:
                z.writestr(info, fh.read())
        z.writestr(f"{TOP}/launcher/manifest.json", json.dumps(manifest, indent=1))
    print(f"Wrote {out} ({out.stat().st_size / 1e6:.1f} MB, {len(files)} files)")


if __name__ == "__main__":
    main()
