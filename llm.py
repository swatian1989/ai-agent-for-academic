"""
llm.py — the ONE file that talks to the Claude API, shared by both agents in this app.

Two functions are all the agents need:
    ask(system, user)                   -> free text (streamed)
    ask_structured(system, user, Model) -> a validated Pydantic object (JSON structured output)

Why a wrapper?  Both agents talk to the model the same way.  Keeping the API details in one
file means you can swap the model or provider in one place.

Settings come from the `.env` file next to this file (see `.env.example`):
    ANTHROPIC_API_KEY   your key from https://console.anthropic.com/
    CLAUDE_MODEL        model for writing and critique   (default claude-opus-5-5)
    CLAUDE_BULK_MODEL   optional cheaper model for bulk screening/extraction (default = CLAUDE_MODEL)

Adapted from the Codanics "Top five AI agents for research" kit (agents 02 and 04).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Type, TypeVar

import anthropic
from dotenv import load_dotenv
from pydantic import BaseModel

APP_DIR = Path(__file__).resolve().parent
ENV_FILE = APP_DIR / ".env"
load_dotenv(ENV_FILE)  # reads ANTHROPIC_API_KEY / CLAUDE_MODEL from the app's .env if present

DEFAULT_MODEL = "claude-opus-5-5"
MODEL_CHOICES = {
    "claude-opus-5-5": "Claude Opus 5.5 — best quality (default)",
    "claude-sonnet-5-5": "Claude Sonnet 5.5 — faster, about half the price",
}
# Models that accept the server-side refusal fallback (`fallbacks: "default"`).
_FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5", "claude-fable-5-1"}
_FALLBACK_BETA = "server-side-fallback-2026-07-01"

T = TypeVar("T", bound=BaseModel)

_client: anthropic.Anthropic | None = None


def model_for(task: str = "writing") -> str:
    """Model for a task. Read from the environment on every call so Settings changes apply at once."""
    main = os.getenv("CLAUDE_MODEL") or DEFAULT_MODEL
    if task == "bulk":
        return os.getenv("CLAUDE_BULK_MODEL") or main
    return main


def client() -> anthropic.Anthropic:
    """Lazily create one shared client (credentials come from the environment)."""
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def reset_client() -> None:
    """Forget the cached client, e.g. after a new API key was saved in Settings."""
    global _client
    _client = None


def has_api_key() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"))


def _request(model: str, system: str, user: str, max_tokens: int, effort: str) -> dict:
    kwargs = dict(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
        thinking={"type": "adaptive"},
        output_config={"effort": effort},
    )
    if model in _FALLBACK_MODELS:
        # If the model declines for policy reasons, the API re-runs the request on Anthropic's
        # recommended fallback model instead of returning an empty refusal.
        kwargs.update(betas=[_FALLBACK_BETA], fallbacks="default")
    return kwargs


def _check(msg) -> None:
    if msg.stop_reason == "refusal":
        detail = getattr(msg, "stop_details", None)
        raise RuntimeError(f"The model declined this request: {detail}")
    if msg.stop_reason == "max_tokens":
        raise RuntimeError("Output was cut off (max_tokens). Increase max_tokens and retry.")


def _text(msg) -> str:
    return "".join(b.text for b in msg.content if b.type == "text")


def ask(system: str, user: str, *, max_tokens: int = 64000, effort: str = "medium",
        echo: bool = False, on_text: Callable[[str], None] | None = None,
        task: str = "writing") -> str:
    """Free-text generation. Streams so long outputs never hit HTTP timeouts.
    `echo` prints to the console (CLI); `on_text` receives each chunk (web app)."""
    with client().beta.messages.stream(**_request(model_for(task), system, user, max_tokens, effort)) as stream:
        if echo or on_text:
            for chunk in stream.text_stream:
                if echo:
                    print(chunk, end="", flush=True)
                if on_text:
                    on_text(chunk)
            if echo:
                print()
        msg = stream.get_final_message()
    _check(msg)
    return _text(msg)


def ask_structured(system: str, user: str, model_cls: Type[T], *, max_tokens: int = 32000,
                   effort: str = "medium", task: str = "writing") -> T:
    """Structured generation: the SDK converts the Pydantic model to a JSON schema, the API
    constrains the output to it, and `parsed_output` is a validated instance of `model_cls`."""
    with client().beta.messages.stream(**_request(model_for(task), system, user, max_tokens, effort),
                                       output_format=model_cls) as stream:
        msg = stream.get_final_message()
    _check(msg)
    if msg.parsed_output is None:  # should not happen with a constrained schema; be defensive
        return model_cls.model_validate_json(_text(msg))
    return msg.parsed_output


def friendly_error(exc: Exception) -> str:
    """Plain-language explanation of an API error, for the web app."""
    if isinstance(exc, anthropic.AuthenticationError):
        return "Your Anthropic API key is missing or not valid. Open ⚙️ Settings in the sidebar and paste a valid key."
    if isinstance(exc, anthropic.PermissionDeniedError):
        return "This API key is not allowed to use the selected model. Try the other model in ⚙️ Settings."
    if isinstance(exc, anthropic.RateLimitError):
        return "The Anthropic API is rate-limiting this key. Wait a minute and try again."
    if isinstance(exc, anthropic.BadRequestError):
        return f"The API rejected the request: {exc.message}"
    if isinstance(exc, anthropic.APIConnectionError):
        return "Could not reach the Anthropic API. Check your internet connection."
    if isinstance(exc, anthropic.APIStatusError):
        return f"Anthropic API error ({exc.status_code}): {exc.message}. Please try again shortly."
    if isinstance(exc, TypeError) and "api_key" in str(exc).lower():
        return "No Anthropic API key found. Open ⚙️ Settings in the sidebar and paste your key."
    return f"{type(exc).__name__}: {exc}"
