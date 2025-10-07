"""FastAPI application exposing the Copilot proxy endpoints."""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

from .config import get_api_key as get_config_api_key, get_base_url as get_config_base_url

DEFAULT_BASE_URL = "https://api.z.ai/api/coding/paas/v4"
DEFAULT_MODEL = "GLM-4.6"
API_KEY_ENV_VARS = ("ZAI_API_KEY", "ZAI_CODING_API_KEY", "GLM_API_KEY")
BASE_URL_ENV_VAR = "ZAI_API_BASE_URL"
CHAT_COMPLETION_PATH = "/chat/completions"

MODEL_CATALOG = [
    {
        "name": "GLM-4.6",
        "model": "GLM-4.6",
        "modified_at": "2024-01-01T00:00:00Z",
        "size": 0,
        "digest": "GLM-4.6",
        "details": {
            "format": "glm",
            "family": "glm",
            "families": ["glm"],
            "parameter_size": "cloud",
            "quantization_level": "cloud",
        },
    },
    {
        "name": "GLM-4.5",
        "model": "GLM-4.5",
        "modified_at": "2024-01-01T00:00:00Z",
        "size": 0,
        "digest": "GLM-4.5",
        "details": {
            "format": "glm",
            "family": "glm",
            "families": ["glm"],
            "parameter_size": "cloud",
            "quantization_level": "cloud",
        },
    },
    {
        "name": "GLM-4.5-Air",
        "model": "GLM-4.5-Air",
        "modified_at": "2024-01-01T00:00:00Z",
        "size": 0,
        "digest": "GLM-4.5-Air",
        "details": {
            "format": "glm",
            "family": "glm",
            "families": ["glm"],
            "parameter_size": "cloud",
            "quantization_level": "cloud",
        },
    },
]


def _get_api_key() -> str:
    # First try to get API key from config file
    config_api_key = get_config_api_key()
    if config_api_key:
        return config_api_key

    # Fall back to environment variables
    for env_var in API_KEY_ENV_VARS:
        api_key = os.getenv(env_var)
        if api_key:
            return api_key.strip()

    raise RuntimeError(
        "Missing Z.AI API key. Please set it using 'copilot-proxy config set-api-key <key>' "
        f"or set one of the following environment variables: {', '.join(API_KEY_ENV_VARS)}"
    )


def _get_base_url() -> str:
    # First try to get base URL from config file
    config_base_url = get_config_base_url()
    if config_base_url:
        base_url = config_base_url
    else:
        # Fall back to environment variable or default
        base_url = os.getenv(BASE_URL_ENV_VAR, DEFAULT_BASE_URL).strip()
        if not base_url:
            base_url = DEFAULT_BASE_URL

    if not base_url.startswith("http://") and not base_url.startswith("https://"):
        base_url = f"https://{base_url}"
    return base_url.rstrip("/")


def _get_chat_completion_url() -> str:
    base_url = _get_base_url()
    if base_url.endswith(CHAT_COMPLETION_PATH):
        return base_url
    return f"{base_url}{CHAT_COMPLETION_PATH}"


@asynccontextmanager
async def _lifespan(app: FastAPI):  # noqa: D401 - FastAPI lifespan signature
    """Ensure configuration is ready before serving requests."""

    try:
        _ = _get_api_key()
        print("GLM Coding Plan proxy is ready.")
    except Exception as exc:  # pragma: no cover - startup logging
        print(f"Failed to initialise GLM Coding Plan proxy: {exc}")
    yield


def create_app() -> FastAPI:
    """Create and return a configured FastAPI application."""

    app = FastAPI(lifespan=_lifespan)

    @app.get("/")
    async def root():  # noqa: D401 - FastAPI route
        """Return a simple health message."""

        return {"message": "GLM Coding Plan proxy is running"}

    @app.get("/api/ps")
    async def list_running_models():  # noqa: D401 - FastAPI route
        """Return an empty list as we do not host local models."""

        return {"models": []}

    @app.get("/api/version")
    async def get_version():  # noqa: D401 - FastAPI route
        """Expose a version compatible with the Ollama API expectations."""

        return {"version": "0.6.4"}

    @app.get("/api/tags")
    @app.get("/api/list")
    async def list_models():  # noqa: D401 - FastAPI route
        """Return the static catalog of GLM models."""

        return {"models": MODEL_CATALOG}

    @app.post("/api/show")
    async def show_model(request: Request):  # noqa: D401 - FastAPI route
        """Handle Ollama-compatible model detail queries."""

        try:
            body = await request.json()
            model_name = body.get("model")
        except Exception:
            model_name = DEFAULT_MODEL

        if not model_name:
            model_name = DEFAULT_MODEL

        return {
            "template": "{{ .System }}\n{{ .Prompt }}",
            "capabilities": ["tools"],
            "details": {
                "family": "glm",
                "families": ["glm"],
                "format": "glm",
                "parameter_size": "cloud",
                "quantization_level": "cloud",
            },
            "model_info": {
                "general.basename": model_name,
                "general.architecture": "glm",
                "glm.context_length": 32768,
            },
        }

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request):  # noqa: D401 - FastAPI route
        """Forward chat completion calls to the Z.AI backend."""

        body = await request.json()

        if not body.get("model"):
            body["model"] = DEFAULT_MODEL

        stream = body.get("stream", False)

        api_key = _get_api_key()
        chat_completion_url = _get_chat_completion_url()

        async def generate_chunks() -> AsyncGenerator[bytes, None]:
            async with httpx.AsyncClient(timeout=300.0) as client:
                try:
                    headers = {
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {api_key}",
                    }
                    response = await client.post(
                        chat_completion_url,
                        headers=headers,
                        json=body,
                        timeout=None,
                    )
                    response.raise_for_status()

                    async for chunk in response.aiter_bytes():
                        yield chunk

                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code == 401:
                        raise RuntimeError("Unauthorized. Check your Z.AI API key.") from exc
                    raise

        if stream:
            return StreamingResponse(generate_chunks(), media_type="text/event-stream")

        async with httpx.AsyncClient(timeout=300.0) as client:
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            }
            response = await client.post(chat_completion_url, headers=headers, json=body)
            response.raise_for_status()
            return response.json()

    return app


app = create_app()

__all__ = [
    "API_KEY_ENV_VARS",
    "BASE_URL_ENV_VAR",
    "CHAT_COMPLETION_PATH",
    "DEFAULT_BASE_URL",
    "DEFAULT_MODEL",
    "MODEL_CATALOG",
    "app",
    "create_app",
]
