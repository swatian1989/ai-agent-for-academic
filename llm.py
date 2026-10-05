"""
llm.py — the ONE file that talks to the AI model, shared by both agents in this app.

Two functions are all the agents need:
    ask(system, user)                   -> free text (streamed)
    ask_structured(system, user, Model) -> a validated Pydantic object (JSON structured output)

Why a wrapper?  Both agents talk to the model the same way.  Keeping the API details in one
file means you can swap the model or provider in one place — which is how the free options work:

    anthropic   Claude (paid API key) — best quality; the model the original kit was built for
    gemini      Google Gemini (FREE API key from Google AI Studio; free tier data may be used by Google)
    openrouter  OpenRouter free models (FREE key; about 50 requests a day)

All three are online services: nothing has to be installed, and they work on Streamlit Cloud.

Settings come from the `.env` file next to this file (see `.env.example`), from Streamlit secrets
when hosted on Streamlit Community Cloud, or — for one browser session only — from `use_session()`:
    AI_PROVIDER         anthropic | gemini | openrouter          (default anthropic)
    ANTHROPIC_API_KEY, CLAUDE_MODEL, CLAUDE_BULK_MODEL
    GEMINI_API_KEY, GEMINI_MODEL
    OPENROUTER_API_KEY, OPENROUTER_MODEL

Adapted from the Codanics "Top five AI agents for research" kit (agents 02 and 04).
"""
from __future__ import annotations

import contextvars
import json
import os
import re
from pathlib import Path
from typing import Callable, Type, TypeVar

import anthropic
import requests
from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError

APP_DIR = Path(__file__).resolve().parent
ENV_FILE = APP_DIR / ".env"
load_dotenv(ENV_FILE)  # reads keys and model choices from the app's .env if present

DEFAULT_MODEL = "claude-opus-5-5"
MODEL_CHOICES = {
    "claude-opus-5-5": "Claude Opus 5.5 — best quality (default)",
    "claude-sonnet-5-5": "Claude Sonnet 5.5 — faster, about half the price",
}
# Claude models that accept the server-side refusal fallback (`fallbacks: "default"`).
_FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5", "claude-fable-5-1"}
_FALLBACK_BETA = "server-side-fallback-2026-07-01"

PROVIDERS: dict[str, dict] = {
    "anthropic": {
        "label": "Claude (Anthropic) — paid, best quality", "short": "Anthropic",
        "key_env": "ANTHROPIC_API_KEY", "model_env": "CLAUDE_MODEL", "default_model": DEFAULT_MODEL,
        "models": list(MODEL_CHOICES), "get_key": "https://console.anthropic.com/settings/keys",
        "note": "Paid per use (pay-as-you-go credit). Best quality for long reviews and manuscripts.",
    },
    "gemini": {
        "label": "Google Gemini — FREE API key", "short": "Google Gemini",
        "key_env": "GEMINI_API_KEY", "model_env": "GEMINI_MODEL", "default_model": "gemini-3.8-flash",
        "models": ["gemini-3.8-flash", "gemini-2.5-pro", "gemini-2.5-flash"],
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/", "url_env": "GEMINI_BASE_URL",
        "max_tokens": 32768, "reasoning_effort": True, "get_key": "https://aistudio.google.com/apikey",
        "note": "Free key from Google AI Studio (no card needed). On the free tier Google may use what you send "
                "to improve its products — avoid unpublished results or anything patient-related. Daily limits apply.",
    },
    "openrouter": {
        "label": "OpenRouter — FREE models", "short": "OpenRouter",
        "key_env": "OPENROUTER_API_KEY", "model_env": "OPENROUTER_MODEL", "default_model": "",
        "models": [], "base_url": "https://openrouter.ai/api/v1", "url_env": "OPENROUTER_BASE_URL",
        "get_key": "https://openrouter.ai/keys",
        "note": "Free key. Free models (names ending in “:free”) allow about 50 requests a day — roughly three "
                "full runs. Some free models log prompts. Press “Load available models” to choose one.",
    },
}

T = TypeVar("T", bound=BaseModel)

_client: anthropic.Anthropic | None = None
_session_clients: dict[str, anthropic.Anthropic] = {}
_openai_clients: dict[tuple, object] = {}
_format_start: dict[tuple, int] = {}  # remembers which JSON mode a provider/model accepted
# Per-browser-session overrides (hosted app): set at the start of every script run by app.py.
# A ContextVar keeps one visitor's keys and choices away from every other visitor.
_session: contextvars.ContextVar[dict] = contextvars.ContextVar("llm_session", default={})


# ================================================================== settings
def use_session(provider: str | None = None, keys: dict | None = None, models: dict | None = None,
                bulk_model: str | None = None) -> None:
    """Use these choices for the current browser session only (never written to disk).
    `keys` and `models` map a provider name to that provider's key / model."""
    _session.set({"provider": provider, "keys": dict(keys or {}), "models": dict(models or {}),
                  "bulk_model": bulk_model})


def provider() -> str:
    p = _session.get().get("provider") or os.getenv("AI_PROVIDER") or "anthropic"
    return p if p in PROVIDERS else "anthropic"


def provider_label(p: str | None = None) -> str:
    return PROVIDERS[p or provider()]["label"]


def api_key(p: str | None = None) -> str | None:
    p = p or provider()
    if _session.get().get("keys", {}).get(p):
        return _session.get()["keys"][p]
    if p == "anthropic":
        return os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN")
    env = PROVIDERS[p]["key_env"]
    return os.getenv(env) if env else None


def has_api_key() -> bool:
    return bool(api_key())


def base_url(p: str) -> str:
    cfg = PROVIDERS[p]
    return os.getenv(cfg.get("url_env") or "") or cfg.get("base_url", "")


def model_for(task: str = "writing") -> str:
    """Model for a task. Read on every call so Settings changes apply at once."""
    p, s = provider(), _session.get()
    cfg = PROVIDERS[p]
    main = s.get("models", {}).get(p) or os.getenv(cfg["model_env"]) or cfg["default_model"]
    if task == "bulk" and p == "anthropic":
        return s.get("bulk_model") or os.getenv("CLAUDE_BULK_MODEL") or main
    return main


# ================================================================== Claude
def client() -> anthropic.Anthropic:
    """The session's own Anthropic key if one was given, else one shared client."""
    key = _session.get().get("keys", {}).get("anthropic")
    if key:
        if key not in _session_clients:
            _session_clients[key] = anthropic.Anthropic(api_key=key)
        return _session_clients[key]
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def reset_client() -> None:
    """Forget cached clients, e.g. after a new API key was saved in Settings."""
    global _client
    _client = None
    _openai_clients.clear()


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


# ================================================================== free providers
def _openai_client(p: str):
    from openai import OpenAI  # only needed for the free providers
    key, url = api_key(p), base_url(p)
    k = (p, key, url)
    if k not in _openai_clients:
        headers = {"X-Title": "AI Agent for Academic"} if p == "openrouter" else None
        _openai_clients[k] = OpenAI(api_key=key or "none", base_url=url, max_retries=4, timeout=900,
                                    default_headers=headers)
    return _openai_clients[k]


def _cut_off() -> RuntimeError:
    return RuntimeError("The answer was cut off because it hit the model's length limit. Try a model with a "
                        "longer output limit, or fewer records.")


def _complete(p: str, system: str, user: str, *, task: str, effort: str, fmt=None,
              on_chunk: Callable[[str], None] | None = None, messages: list | None = None) -> str:
    """One chat completion on a free provider (OpenAI-compatible API). `fmt` is a response_format.
    Streams to `on_chunk` when given."""
    model = model_for(task)
    if not model:
        raise RuntimeError(f"Choose a model for {PROVIDERS[p]['short']} in ⚙️ Settings "
                           "(press “Load available models”).")
    msgs = messages or [{"role": "system", "content": system}, {"role": "user", "content": user}]
    cfg = PROVIDERS[p]
    kwargs: dict = {"model": model, "messages": msgs}
    if cfg.get("max_tokens"):
        kwargs["max_tokens"] = cfg["max_tokens"]
    if cfg.get("reasoning_effort"):
        kwargs["reasoning_effort"] = effort
    if fmt is not None:
        kwargs["response_format"] = fmt
    oa = _openai_client(p)
    if on_chunk is None:
        resp = oa.chat.completions.create(**kwargs)
        choice = resp.choices[0]
        if choice.finish_reason == "length":
            raise _cut_off()
        return choice.message.content or ""
    parts, finish = [], None
    for ev in oa.chat.completions.create(stream=True, **kwargs):
        if not ev.choices:
            continue
        piece = ev.choices[0].delta.content if ev.choices[0].delta else None
        if piece:
            parts.append(piece)
            on_chunk(piece)
        finish = ev.choices[0].finish_reason or finish
    if finish == "length":
        raise _cut_off()
    return "".join(parts)


_THINK = re.compile(r"<think>.*?</think>\s*", re.S)


def _strip_think(text: str) -> str:
    return _THINK.sub("", text).strip()


def _parse_json(text: str, model_cls: Type[T]) -> T:
    text = _strip_think(text)
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fenced:
        text = fenced.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("The model did not return a JSON object.")
    return model_cls.model_validate_json(text[start:end + 1])


def _free_structured(p: str, system: str, user: str, model_cls: Type[T], *, task: str, effort: str) -> T:
    """Structured output on providers without Claude's guaranteed schemas: ask for JSON in the best mode
    the provider accepts, validate with Pydantic, and give the model one chance to repair invalid JSON."""
    schema = model_cls.model_json_schema()
    system = (f"{system}\n\nReply with ONLY a JSON object — no explanation and no code fences — that matches "
              f"this JSON schema (named {model_cls.__name__}):\n{json.dumps(schema)}")
    modes = [{"type": "json_schema", "json_schema": {"name": model_cls.__name__, "schema": schema, "strict": False}},
             {"type": "json_object"}, None]
    key = (p, model_for(task))
    text = ""
    for i in range(_format_start.get(key, 0), len(modes)):
        try:
            text = _complete(p, system, user, task=task, effort=effort, fmt=modes[i])
            _format_start[key] = i
            break
        except Exception as exc:  # a provider that rejects this JSON mode answers 400 — try the next mode
            if i == len(modes) - 1 or type(exc).__name__ != "BadRequestError":
                raise
    try:
        return _parse_json(text, model_cls)
    except (ValidationError, ValueError) as err:
        repair = [{"role": "system", "content": system}, {"role": "user", "content": user},
                  {"role": "assistant", "content": text},
                  {"role": "user", "content": f"That reply did not match the schema ({str(err)[:1500]}). "
                                              "Return the corrected JSON object only."}]
        text = _complete(p, system, user, task=task, effort=effort, fmt=modes[_format_start.get(key, 0)],
                         messages=repair)
        try:
            return _parse_json(text, model_cls)
        except (ValidationError, ValueError):
            raise RuntimeError(f"{PROVIDERS[p]['short']} ({model_for(task)}) could not produce valid structured "
                               "output for this step. Try again, or choose a larger model in ⚙️ Settings.") from None


# ================================================================== the two functions
def ask(system: str, user: str, *, max_tokens: int = 64000, effort: str = "medium",
        echo: bool = False, on_text: Callable[[str], None] | None = None,
        task: str = "writing") -> str:
    """Free-text generation. Streams so long outputs never hit HTTP timeouts.
    `echo` prints to the console (CLI); `on_text` receives each chunk (web app)."""
    p = provider()
    if p != "anthropic":
        def emit(chunk: str) -> None:
            if echo:
                print(chunk, end="", flush=True)
            if on_text:
                on_text(chunk)
        text = _complete(p, system, user, task=task, effort=effort, on_chunk=emit)
        if echo:
            print()
        return _strip_think(text)
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
    """Structured generation. With Claude the API constrains the output to the Pydantic model's JSON schema
    and `parsed_output` is a validated instance; other providers go through `_free_structured`."""
    p = provider()
    if p != "anthropic":
        return _free_structured(p, system, user, model_cls, task=task, effort=effort)
    with client().beta.messages.stream(**_request(model_for(task), system, user, max_tokens, effort),
                                       output_format=model_cls) as stream:
        msg = stream.get_final_message()
    _check(msg)
    if msg.parsed_output is None:  # should not happen with a constrained schema; be defensive
        return model_cls.model_validate_json(_text(msg))
    return msg.parsed_output


# ================================================================== model lists
_SKIP_GEMINI = ("embedding", "tts", "image", "live", "veo", "imagen", "robotics", "transcribe", "audio", "aqa")


def list_models(p: str) -> list[str]:
    """Models available to you right now from a provider (falls back to the built-in suggestions)."""
    cfg = PROVIDERS[p]
    if p == "anthropic":
        return list(MODEL_CHOICES)
    if p == "openrouter":
        r = requests.get(base_url(p).rstrip("/") + "/models", timeout=30)
        r.raise_for_status()
        free = [m for m in r.json().get("data", []) if m.get("id", "").endswith(":free")
                and (m.get("context_length") or 0) >= 32000]
        free.sort(key=lambda m: (-(m.get("context_length") or 0), m["id"]))
        return [m["id"] for m in free] or cfg["models"]
    ids = [m.id.split("/")[-1] for m in _openai_client(p).models.list()]
    ids = [i for i in ids if i.startswith("gemini") and not any(s in i for s in _SKIP_GEMINI)]
    return sorted(set(ids), reverse=True) or cfg["models"]


# ================================================================== errors
def friendly_error(exc: Exception) -> str:
    """Plain-language explanation of an API error, for the web app."""
    short = PROVIDERS[provider()]["short"]
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
    try:
        import openai
    except ImportError:
        openai = None
    if openai is not None:
        if isinstance(exc, (openai.AuthenticationError, openai.PermissionDeniedError)) or (
                isinstance(exc, openai.BadRequestError) and "api key" in str(exc).lower()):
            return f"Your {short} API key is missing or not valid. Open ⚙️ Settings and paste a valid key."
        if isinstance(exc, openai.RateLimitError):
            return (f"The free {short} limit has been reached (too many requests per minute or per day). "
                    "Wait a minute — or until tomorrow for daily limits — or switch provider in ⚙️ Settings.")
        if isinstance(exc, openai.NotFoundError):
            return f"{short} does not offer the model “{model_for()}”. Choose another model in ⚙️ Settings."
        if isinstance(exc, openai.BadRequestError):
            return f"{short} rejected the request: {getattr(exc, 'message', exc)}"
        if isinstance(exc, openai.APIConnectionError):
            return f"Could not reach {short}. Check your internet connection."
        if isinstance(exc, openai.APIStatusError):
            return f"{short} error ({exc.status_code}): {getattr(exc, 'message', exc)}. Please try again shortly."
    if isinstance(exc, requests.HTTPError):
        return f"{short} error: {exc}"
    if isinstance(exc, TypeError) and "api_key" in str(exc).lower():
        return "No API key found. Open ⚙️ Settings in the sidebar and paste your key."
    return f"{type(exc).__name__}: {exc}" if not isinstance(exc, RuntimeError) else str(exc)
