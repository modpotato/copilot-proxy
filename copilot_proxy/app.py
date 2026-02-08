"""FastAPI application exposing the Copilot proxy endpoints."""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import AsyncGenerator, List, Dict, Any

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

from .config import (
    get_api_key as get_config_api_key,
    get_base_url as get_config_base_url,
    get_context_length,
    get_model_name as get_config_model_name,
    get_temperature,
)

DEFAULT_BASE_URL = "https://api.z.ai/api/coding/paas/v4"
DEFAULT_MODEL = "GLM-4.7"
API_KEY_ENV_VARS = ("ZAI_API_KEY", "ZAI_CODING_API_KEY", "GLM_API_KEY")
BASE_URL_ENV_VAR = "ZAI_API_BASE_URL"
CHAT_COMPLETION_PATH = "/chat/completions"
MODELS_PATH = "/models"

# Dynamic model catalog - populated on startup
_dynamic_model_catalog: List[Dict[str, Any]] = []


def _convert_api_model_to_ollama_format(api_model: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a model from the Z.AI /models response to Ollama format."""
    model_id = api_model.get("id", "unknown")
    created = api_model.get("created", 0)
    
    # Convert Unix timestamp to ISO format
    try:
        modified_at = datetime.utcfromtimestamp(created).isoformat() + "Z"
    except (ValueError, OSError):
        modified_at = "2024-01-01T00:00:00Z"
    
    return {
        "name": model_id,
        "model": model_id,
        "modified_at": modified_at,
        "size": 0,
        "digest": model_id,
        "details": {
            "format": "glm",
            "family": "glm",
            "families": ["glm"],
            "parameter_size": "cloud",
            "quantization_level": "cloud",
        },
    }


async def fetch_available_models() -> List[Dict[str, Any]]:
    """Fetch the list of available models from the Z.AI API."""
    global _dynamic_model_catalog
    
    try:
        api_key = _get_api_key()
        base_url = _get_base_url()
        models_url = f"{base_url}{MODELS_PATH}"
        
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(models_url, headers=headers)
            response.raise_for_status()
            
            data = response.json()
            api_models = data.get("data", [])
            
            # Convert to Ollama format
            _dynamic_model_catalog = [
                _convert_api_model_to_ollama_format(m) for m in api_models
            ]
            
            return _dynamic_model_catalog
            
    except Exception as exc:
        print(f"Warning: Failed to fetch models from API: {exc}")
        print("Falling back to default model only.")
        # Fallback to just the default model
        _dynamic_model_catalog = [
            {
                "name": DEFAULT_MODEL,
                "model": DEFAULT_MODEL,
                "modified_at": "2024-01-01T00:00:00Z",
                "size": 0,
                "digest": DEFAULT_MODEL,
                "details": {
                    "format": "glm",
                    "family": "glm",
                    "families": ["glm"],
                    "parameter_size": "cloud",
                    "quantization_level": "cloud",
                },
            }
        ]
        return _dynamic_model_catalog


def get_model_catalog() -> List[Dict[str, Any]]:
    """Get the current model catalog (dynamically loaded or fallback)."""
    if _dynamic_model_catalog:
        return _dynamic_model_catalog
    # Return a minimal fallback if not yet loaded
    return [
        {
            "name": DEFAULT_MODEL,
            "model": DEFAULT_MODEL,
            "modified_at": "2024-01-01T00:00:00Z",
            "size": 0,
            "digest": DEFAULT_MODEL,
            "details": {
                "format": "glm",
                "family": "glm",
                "families": ["glm"],
                "parameter_size": "cloud",
                "quantization_level": "cloud",
            },
        }
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
        # Fetch available models dynamically from the API
        models = await fetch_available_models()
        model_names = [m["name"] for m in models]
        print(f"Loaded {len(models)} models from API: {', '.join(model_names)}")
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

        return {"models": get_model_catalog()}

    @app.post("/api/show")
    async def show_model(request: Request):  # noqa: D401 - FastAPI route
        """Handle Ollama-compatible model detail queries."""

        try:
            body = await request.json()
            model_name = body.get("model")
        except Exception:
            model_name = DEFAULT_MODEL

        if not model_name:
            model_name = get_config_model_name() or DEFAULT_MODEL

        context_length = get_context_length()

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
                "glm.context_length": context_length,
            },
        }

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request):  # noqa: D401 - FastAPI route
        """Forward chat completion calls to the Z.AI backend."""

        body = await request.json()

        if not body.get("model"):
            body["model"] = get_config_model_name() or DEFAULT_MODEL

        # Apply temperature override if configured
        config_temp = get_temperature()
        if config_temp is not None:
            body["temperature"] = config_temp

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
    "app",
    "create_app",
    "fetch_available_models",
    "get_model_catalog",
]
