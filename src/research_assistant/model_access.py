"""Explicit model credentials and request policy; configuration never probes a provider."""

import ipaddress
import json
import os
from dataclasses import dataclass, field, replace
from typing import Callable, Literal
from urllib.parse import urlsplit

from openai import (
    APIConnectionError,
    APIResponseValidationError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    NotFoundError,
    OpenAI,
    OpenAIError,
    PermissionDeniedError,
    RateLimitError,
)

from . import config
from .contracts import DomainError

BUILTIN_PROVIDERS = ("openrouter", "openai", "compatible")


@dataclass(frozen=True)
class ModelSource:
    id: str
    label: str
    provider: Literal["openai", "openrouter", "compatible"]
    model: str
    configured: bool
    error: str | None = None


@dataclass(frozen=True)
class ModelSettings:
    provider: Literal["openai", "openrouter", "compatible"]
    label: str
    model: str | None
    api_key: str | None = field(repr=False)
    base_url: str | None = field(repr=False)
    error: str | None = None
    source_id: str = "default"
    sources: tuple["ModelSource", ...] = ()
    role_routes: dict[str, str] = field(default_factory=dict, repr=False)
    client_factory: Callable | None = field(default=None, repr=False, compare=False)

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.model and not self.error)

    @property
    def client_kwargs(self) -> dict:
        # No max_retries override: the SDK default retries 429/5xx and connection errors.
        kwargs = {
            "api_key": self.api_key,
            "base_url": self.base_url,
        }
        if self.provider == "openrouter":
            # Empty values suppress the SDK's OPENAI_ORG_ID/OPENAI_PROJECT_ID defaults.
            kwargs.update(organization="", project="")
        return kwargs

    def request_kwargs(self, fallbacks: bool = False) -> dict:
        # fallbacks: let OpenRouter move to another host of the same model when one is rate-limited.
        # Agents use it (the serving host is traced per call); baseline A keeps a single host.
        kwargs = {"store": False}
        if self.provider == "openrouter":
            kwargs["extra_body"] = {
                "provider": {"require_parameters": True, "allow_fallbacks": fallbacks}
            }
        return kwargs

    def agent_kwargs(self) -> dict:
        """What every agent model call sends: host fallback minus the hosts config.py skips, plus the decoding
        settings config.py pins (none by default)."""
        pinned = {name: value for name, value in decoding().items() if value is not None}
        kwargs = self.request_kwargs(fallbacks=True)
        if self.provider == "openrouter" and config.AGENT_IGNORED_HOSTS:
            kwargs["extra_body"]["provider"]["ignore"] = list(config.AGENT_IGNORED_HOSTS)
        return kwargs | pinned

    def metadata(self) -> dict:
        return {
            "provider": self.provider,
            "model": self.model,
            "schema_version": "financial-review-v3",
        }

    def with_routes(self, routes: dict[str, str] | None) -> "ModelSettings":
        return replace(self, role_routes=dict(routes or {}))

    def for_role(self, role: str) -> "ModelSettings":
        source_id = self.role_routes.get(role)
        if not source_id:
            return self
        return resolve_model_source(source_id, fallback=self)


def decoding() -> dict:
    """The agents' decoding settings from config.py. None means none is sent, so the provider's default applies."""
    return {"temperature": config.AGENT_TEMPERATURE, "top_p": config.AGENT_TOP_P, "seed": config.AGENT_SEED}


def decoding_record() -> dict:
    """The decoding settings as a trace records them, so a run says what it ran with even when nothing is pinned."""
    return {name: "provider default" if value is None else value for name, value in decoding().items()}


def _setting(name: str) -> str | None:
    return os.getenv(name, "").strip() or None


def _valid_endpoint(value: str) -> bool:
    try:
        endpoint = urlsplit(value)
        if (
            not endpoint.hostname
            or endpoint.username is not None
            or endpoint.password is not None
            or endpoint.query
            or endpoint.fragment
            or "?" in value
            or "#" in value
            or any(character.isspace() or ord(character) < 32 for character in value)
        ):
            return False
        _ = endpoint.port  # Reject malformed ports during configuration loading.
        if endpoint.scheme == "https":
            return True
        if endpoint.scheme != "http":
            return False
        if endpoint.hostname.lower() == "localhost":
            return True
        return ipaddress.ip_address(endpoint.hostname).is_loopback
    except ValueError:
        return False


def _validate_openrouter_model(model: str | None) -> str | None:
    if model and (
        model.lower().split(":", 1)[0] in {"openrouter/auto", "openrouter/free"}
        or "online" in model.lower().split(":")[1:]
    ):
        return "Choose an explicit OpenRouter model without automatic routing or online search."
    return None


def load_provider_settings(provider: Literal["openai", "openrouter", "compatible"]) -> ModelSettings:
    """Settings for one built-in provider, so multiple providers can be configured in .env together."""
    explicit = (_setting("RESEARCH_MODEL_PROVIDER") or "").lower() or None
    research_model = _setting("RESEARCH_MODEL")
    openai_base_url = _setting("OPENAI_BASE_URL")
    if provider == "openrouter":
        model = (research_model if explicit == "openrouter" else None) or _setting("OPENROUTER_MODEL")
        error = None
        if explicit == "openrouter" and openai_base_url:
            error = "Remove OPENAI_BASE_URL when selecting OpenRouter; its endpoint is fixed."
        else:
            error = _validate_openrouter_model(model)
        return ModelSettings("openrouter", "OpenRouter", model, _setting("OPENROUTER_API_KEY"),
                             "https://openrouter.ai/api/v1", error, "openrouter")
    if provider == "compatible":
        compat_url = _setting("COMPATIBLE_BASE_URL")
        legacy_url = openai_base_url if explicit != "openrouter" else None
        custom_url = compat_url or legacy_url
        model = (research_model if (explicit == "compatible" or legacy_url) else None) or _setting("COMPATIBLE_MODEL")
        api_key = _setting("COMPATIBLE_API_KEY") or _setting("OPENAI_API_KEY")
        error = None
        if not custom_url:
            error = "Set COMPATIBLE_BASE_URL or OPENAI_BASE_URL for the compatible provider."
        elif not _valid_endpoint(custom_url):
            name = "COMPATIBLE_BASE_URL" if compat_url else "OPENAI_BASE_URL"
            error = f"{name} must use HTTPS (or loopback HTTP) without credentials, query or fragment."
        return ModelSettings("compatible", "OpenAI-compatible", model, api_key, custom_url, error, "compatible")
    model = (research_model if (explicit in (None, "openai") and not openai_base_url) else None) or _setting("OPENAI_MODEL")
    return ModelSettings("openai", "OpenAI", model, _setting("OPENAI_API_KEY"),
                         "https://api.openai.com/v1", None, "openai")


def load_model_settings() -> ModelSettings:
    explicit = _setting("RESEARCH_MODEL_PROVIDER")
    model = _setting("RESEARCH_MODEL")
    custom_url = _setting("OPENAI_BASE_URL")
    if explicit:
        provider = explicit.lower()
        if provider not in BUILTIN_PROVIDERS:
            return ModelSettings("openai", "Model access", model, None, None,
                                 "RESEARCH_MODEL_PROVIDER must be openai, openrouter or compatible.")
        if provider == "openai" and custom_url:
            error = None if _valid_endpoint(custom_url) else (
                "OPENAI_BASE_URL must use HTTPS (or loopback HTTP) without credentials, query or fragment.")
            return ModelSettings("compatible", "OpenAI-compatible", model or _setting("COMPATIBLE_MODEL"),
                                 _setting("OPENAI_API_KEY"), custom_url, error)
        return replace(load_provider_settings(provider), source_id="default")  # type: ignore[arg-type]
    if custom_url:
        error = None if _valid_endpoint(custom_url) else (
            "OPENAI_BASE_URL must use HTTPS (or loopback HTTP) without credentials, query or fragment.")
        return ModelSettings("compatible", "OpenAI-compatible", model or _setting("COMPATIBLE_MODEL"),
                             _setting("OPENAI_API_KEY"), custom_url, error)
    for name in ("openai", "openrouter", "compatible"):
        candidate = load_provider_settings(name)  # type: ignore[arg-type]
        if candidate.configured:
            return replace(candidate, source_id="default")
    for source in _custom_model_sources():
        if source[0].configured:
            return replace(source[1], source_id="default")
    return replace(load_provider_settings("openai"), source_id="default")


def _source_settings(entry: dict) -> tuple[ModelSource, ModelSettings]:
    source_id = str(entry.get("id", "")).strip()
    label = str(entry.get("label", "")).strip()
    provider = str(entry.get("provider", "")).strip().lower()
    model = str(entry.get("model", "")).strip()
    if not source_id or not label or provider not in BUILTIN_PROVIDERS or not model:
        return (ModelSource(source_id or "invalid", label or "Invalid model source",
                            provider if provider in BUILTIN_PROVIDERS else "compatible",
                            model, False, "Each source needs id, label, provider and model."),
                ModelSettings("compatible", "Invalid model source", model, None, None,
                              "Invalid model source.", source_id))
    key_env = str(entry.get("api_key_env", "")).strip()
    if not key_env:
        key_env = "OPENROUTER_API_KEY" if provider == "openrouter" else (
            "COMPATIBLE_API_KEY" if provider == "compatible" and _setting("COMPATIBLE_API_KEY") else "OPENAI_API_KEY")
    api_key = _setting(key_env)
    custom_url = str(entry.get("base_url", "")).strip() or (
        (_setting("COMPATIBLE_BASE_URL") or _setting("OPENAI_BASE_URL")) if provider == "compatible" else None)
    error = None
    if provider == "openrouter":
        base_url = "https://openrouter.ai/api/v1"
        error = "OpenRouter sources must not set base_url." if custom_url else _validate_openrouter_model(model)
    elif provider == "compatible":
        base_url = custom_url
        if not base_url:
            error = f"Set base_url or COMPATIBLE_BASE_URL for source {source_id}."
        elif not _valid_endpoint(base_url):
            error = f"Source {source_id} has an invalid base_url."
    else:
        base_url = "https://api.openai.com/v1"
    settings = ModelSettings(provider, label, model, api_key, base_url, error, source_id)  # type: ignore[arg-type]
    return ModelSource(source_id, label, provider, model, settings.configured, error), settings  # type: ignore[arg-type]


def _custom_model_sources() -> list[tuple[ModelSource, ModelSettings]]:
    raw = _setting("RESEARCH_MODEL_SOURCES")
    if not raw:
        return []
    try:
        entries = json.loads(raw)
    except json.JSONDecodeError:
        err = ModelSource("invalid", "Invalid model sources", "compatible", "", False,
                          "RESEARCH_MODEL_SOURCES must be a JSON array.")
        return [(err, ModelSettings("compatible", err.label, "", None, None, err.error, "invalid"))]
    if not isinstance(entries, list):
        err = ModelSource("invalid", "Invalid model sources", "compatible", "", False,
                          "RESEARCH_MODEL_SOURCES must be a JSON array.")
        return [(err, ModelSettings("compatible", err.label, "", None, None, err.error, "invalid"))]
    return [_source_settings(entry) for entry in entries if isinstance(entry, dict)]


def load_model_sources() -> tuple[ModelSource, ...]:
    """The primary setting, other configured built-in providers and RESEARCH_MODEL_SOURCES are all usable choices."""
    primary = load_model_settings()
    sources = [ModelSource("default", primary.label, primary.provider, primary.model or "",
                           primary.configured, primary.error)]
    seen = {"default"}
    for name in BUILTIN_PROVIDERS:
        candidate = load_provider_settings(name)  # type: ignore[arg-type]
        same_as_primary = (
            candidate.provider == primary.provider
            and candidate.model == primary.model
            and candidate.base_url == primary.base_url
            and candidate.api_key == primary.api_key
        )
        if candidate.configured and not same_as_primary:
            seen.add(name)
            sources.append(ModelSource(name, candidate.label, candidate.provider, candidate.model or "",
                                       candidate.configured, candidate.error))
    for source, _ in _custom_model_sources():
        if source.id in seen:
            continue
        seen.add(source.id)
        sources.append(source)
    return tuple(sources)


def resolve_model_source(source_id: str, fallback: ModelSettings | None = None) -> ModelSettings:
    primary = fallback or load_model_settings()
    if source_id == "default":
        return primary
    if source_id in BUILTIN_PROVIDERS:
        settings = load_provider_settings(source_id)  # type: ignore[arg-type]
        return replace(settings, role_routes=primary.role_routes, client_factory=primary.client_factory)
    for source, settings in _custom_model_sources():
        if source.id == source_id:
            return replace(settings, role_routes=primary.role_routes, client_factory=primary.client_factory)
    if fallback is not None:
        return fallback
    return load_model_settings()


def make_model_client(settings: ModelSettings):
    """Create a provider-specific client for a routed role; cli.model_client remains the testable factory."""
    if settings.client_factory is not None:
        return settings.client_factory(settings)
    return OpenAI(**settings.client_kwargs, max_retries=config.AGENT_MODEL_RETRIES)


def client_for_role(base_client, base_settings: ModelSettings, role: str):
    routed = base_settings.for_role(role)
    if (routed.provider == base_settings.provider
            and routed.base_url == base_settings.base_url
            and routed.api_key == base_settings.api_key
            and routed.model == base_settings.model):
        return base_client, routed
    return make_model_client(routed), routed


def safe_model_error(exc: Exception) -> DomainError:
    """Translate failures without reflecting provider messages, headers or credentials."""
    body = getattr(exc, "body", None)
    error = body.get("error", body) if isinstance(body, dict) else {}
    if isinstance(error, dict) and error.get("code") in ("context_length_exceeded", "context_window_exceeded", "input_too_long"):
        return DomainError("The complete evidence exceeds the selected model's input context. Evidence was not silently truncated. Choose a model with a larger context or explicitly narrow the source selection.", "model_context_limit", 502)
    if isinstance(exc, (AuthenticationError, PermissionDeniedError)):
        return DomainError("Model authentication or access was rejected. Check the selected provider credentials and permissions.", "model_authentication", 502)
    if isinstance(exc, RateLimitError):
        return DomainError("The model provider rate limit was still reached after automatic retries. Saved results remain available; retry later.", "model_rate_limit", 502)
    if isinstance(exc, (APITimeoutError, TimeoutError)):
        return DomainError("The model request still timed out after automatic retries. Saved results remain available.", "model_timeout", 502)
    if isinstance(exc, (BadRequestError, APIResponseValidationError, ValueError)):
        return DomainError("The model request or structured response was incompatible with the required schema. Saved results remain available.", "model_schema", 502)
    if isinstance(exc, (NotFoundError, APIConnectionError)):
        return DomainError("The selected model or provider endpoint is unavailable. Saved results remain available; retry explicitly later.", "model_unavailable", 502)
    if isinstance(exc, APIStatusError):
        if exc.status_code == 402:
            return DomainError("The model provider requires payment or additional credits. Check the selected provider account.", "model_unavailable", 502)
        return DomainError("The model provider could not complete the request. Saved results remain available; retry explicitly later.", "model_unavailable", 502)
    return DomainError("Model request failed. Saved results remain available.", "model_failed", 502)


CHECK_TOOL = {"type": "function", "function": {
    "name": "confirm", "description": "Confirm that you can call tools.", "parameters": {"type": "object", "properties": {}}}}


def check_model(source_id: str | None = None) -> str:
    """One short request with one tool, sent the way agent runs send theirs: it proves the key, the model and
    tool calling. It costs a fraction of a cent, so the Setup page asks for no consent."""
    settings = resolve_model_source(source_id) if source_id else load_model_settings()
    try:
        with OpenAI(**settings.client_kwargs) as client:
            reply = client.chat.completions.create(
                model=settings.model, messages=[{"role": "user", "content": "Call the confirm tool."}],
                tools=[CHECK_TOOL], **settings.request_kwargs(fallbacks=True))
    except OpenAIError as exc:
        error, status = safe_model_error(exc), getattr(exc, "status_code", None)
        raise DomainError(f"{error} (HTTP {status})" if status else str(error), error.code, error.status) from None
    served = reply.model or settings.model
    if not (reply.choices and reply.choices[0].message.tool_calls):
        raise DomainError(f"{settings.label} answered with {served} but did not call the test tool. "
                          "Agent runs need a model that calls tools.", "model_schema", 502)
    return f"{settings.label} answered with {served} and called the test tool."
