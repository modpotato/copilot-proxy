"""Copilot proxy package surfaces the FastAPI application and CLI utilities."""
from __future__ import annotations

from importlib import metadata

from .app import app, create_app

__all__ = ["app", "create_app", "__version__"]

try:  # pragma: no cover - fallback when package metadata missing
    __version__ = metadata.version("copilot-proxy")
except metadata.PackageNotFoundError:  # type: ignore[attr-defined]
    __version__ = "0.0.0"
