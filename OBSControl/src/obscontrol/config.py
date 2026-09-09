from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile

from .models import AppConfig


def default_config_path() -> Path:
    base = Path(os.environ.get("APPDATA", Path.home()))
    return base / "OBSControl" / "config.json"


def load_config(path: Path | None = None) -> AppConfig:
    path = path or default_config_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return AppConfig()
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ValueError(f"Invalid OBSControl configuration at {path}: {exc}") from exc
    return AppConfig.from_dict(raw)


def save_config(config: AppConfig, path: Path | None = None) -> None:
    path = path or default_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(config.to_dict(), indent=2, sort_keys=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=path.parent, text=True,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.write("\n")
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def local_obs_connection() -> tuple[str, int, str] | None:
    """Read OBS's own local WebSocket settings without exposing the password."""
    base = Path(os.environ.get("APPDATA", Path.home()))
    path = base / "obs-studio" / "plugin_config" / "obs-websocket" / "config.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    if not raw.get("server_enabled", False):
        return None
    return "127.0.0.1", int(raw.get("server_port", 4455)), raw.get("server_password", "")
