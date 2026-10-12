"""API keys for remote services.

Keys go to the operating system's credential store (Windows Credential Manager,
macOS Keychain, Linux Secret Service) via `keyring`, never into settings.json.
If no credential store is available, they fall back to a file inside the app's
cache folder that only the current user can read, and the UI says so.
"""
import json
import os
from pathlib import Path
from typing import Optional

from .LAV_logger import logger
from .paths import CACHE_DIR

SERVICE = "LocalAIVtuber"
FALLBACK_FILE = CACHE_DIR / "secrets.json"


def _keyring():
    try:
        import keyring
        from keyring.backends import fail
        if isinstance(keyring.get_keyring(), fail.Keyring):
            return None
        return keyring
    except Exception:
        return None


def storage_name() -> str:
    kr = _keyring()
    if kr:
        return {"nt": "Windows Credential Manager"}.get(os.name, "the system keychain")
    return "a private file in the app folder (no system credential store available)"


def _read_file() -> dict:
    try:
        return json.loads(Path(FALLBACK_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def get_secret(name: str) -> Optional[str]:
    kr = _keyring()
    if kr:
        try:
            value = kr.get_password(SERVICE, name)
            if value:
                return value
        except Exception as e:
            logger.debug(f"keyring read failed: {e}")
    return _read_file().get(name)


def set_secret(name: str, value: Optional[str]):
    kr = _keyring()
    if kr:
        try:
            if value:
                kr.set_password(SERVICE, name, value)
            else:
                try:
                    kr.delete_password(SERVICE, name)
                except Exception:
                    pass
            _remove_from_file(name)
            return
        except Exception as e:
            logger.warning(f"System credential store unavailable ({e}); storing the key in the app folder instead.")
    data = _read_file()
    if value:
        data[name] = value
    else:
        data.pop(name, None)
    FALLBACK_FILE.parent.mkdir(parents=True, exist_ok=True)
    FALLBACK_FILE.write_text(json.dumps(data), encoding="utf-8")
    try:
        os.chmod(FALLBACK_FILE, 0o600)
    except OSError:
        pass


def _remove_from_file(name: str):
    data = _read_file()
    if name in data:
        data.pop(name)
        FALLBACK_FILE.write_text(json.dumps(data), encoding="utf-8")
