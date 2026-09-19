"""The language model behind Tier 3, the Copilot's prose and the assistant.

One client, two ways to reach a model. On an installation the model is
Ollama on the same machine (`OLLAMA_URL`), which is the offline promise: no
question leaves the building. On a demo link with 512 MB of memory there is
no room for a three-billion-parameter model, so the same client can speak to
an OpenAI-compatible endpoint instead (`SAMAN_LLM_URL`, `SAMAN_LLM_MODEL`,
`SAMAN_LLM_KEY`): Groq's free tier, a Gemini key, or any server that speaks
the `/v1/chat/completions` shape. That is a remote model, and the health page
says so in those words; nothing about the guards changes. The model still
only words a sentence and answers from retrieved passages, every figure it
produces is checked against what was computed, and sovereign mode switches
both paths off.

Every call site asks this module, never an HTTP library: `available()`,
`generate(prompt)`, `chat(messages)`, and `provider()` for the label.
"""

from __future__ import annotations

from functools import lru_cache

import httpx

from .config import get_settings

#: How the model is reached, for the health page and the provenance labels.
LOCAL = "ollama"
REMOTE = "remote"
NONE = "deterministic"


def provider() -> str:
    """Which path is configured: local Ollama, a remote endpoint, or none."""
    settings = get_settings()
    if not settings.llm_enabled:
        return NONE
    if settings.saman_llm_url:
        return REMOTE
    return LOCAL


def model_name() -> str:
    settings = get_settings()
    return settings.saman_llm_model if settings.saman_llm_url else settings.ollama_model


def engine_label() -> str:
    """What `/api/health` prints beside the mode."""
    settings = get_settings()
    kind = provider()
    if kind == LOCAL:
        return f"ollama · {settings.ollama_model} on this machine"
    if kind == REMOTE:
        return f"remote · {settings.saman_llm_model} at {_host(settings.saman_llm_url)}"
    return "rule-based adjudicator"


def _host(url: str) -> str:
    return url.split("//", 1)[-1].split("/", 1)[0]


def available() -> bool:
    """A model is configured and answers. One probe, cached per process."""
    settings = get_settings()
    if not settings.llm_enabled:
        return False
    if settings.saman_llm_url:
        return _remote_reachable(settings.saman_llm_url, settings.saman_llm_key or "")
    return _ollama_reachable(settings.ollama_url or "", settings.ollama_model)


@lru_cache(maxsize=4)
def _ollama_reachable(url: str, model: str) -> bool:
    try:
        response = httpx.get(f"{url.rstrip('/')}/api/tags", timeout=2.0)
        response.raise_for_status()
        names = {m.get("name", "") for m in response.json().get("models", [])}
    except Exception:
        return False
    return model in names or f"{model}:latest" in names or any(n.startswith(model) for n in names)


@lru_cache(maxsize=4)
def _remote_reachable(url: str, key: str) -> bool:
    try:
        response = httpx.get(f"{url.rstrip('/')}/models", headers=_auth(key), timeout=4.0)
        return response.status_code == 200
    except Exception:
        return False


def _auth(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"} if key else {}


def forget() -> None:
    """Drop the cached probes (tests, and the admin health refresh)."""
    _ollama_reachable.cache_clear()
    _remote_reachable.cache_clear()


# --------------------------------------------------------------------------
# What the model's wording is worth: counted, never assumed
# --------------------------------------------------------------------------

#: outcome counts per caller ("assistant", "copilot", "adjudicate"): how
#: often the model's sentence passed the caller's guard, and why it did not.
_outcomes: dict[str, dict[str, int]] = {}


def record(caller: str, outcome: str) -> None:
    bucket = _outcomes.setdefault(caller, {})
    bucket[outcome] = bucket.get(outcome, 0) + 1


def stats() -> dict:
    """Acceptance per caller since the process started. `accepted` over the
    total is the one number that says whether a smaller or larger model is
    earning its place; the rest says why answers were thrown away."""
    out = {}
    for caller, counts in _outcomes.items():
        total = sum(counts.values())
        out[caller] = {
            "total": total,
            "accepted": counts.get("accepted", 0),
            "acceptance": round(counts.get("accepted", 0) / total, 3) if total else None,
            "by_outcome": dict(sorted(counts.items())),
        }
    kind = provider()
    return {"provider": kind, "model": model_name() if kind != NONE else None, "callers": out}


def reset_stats() -> None:
    _outcomes.clear()


def generate(
    prompt: str, *, temperature: float = 0.1, timeout: float = 20.0, max_tokens: int = 300
) -> str:
    """One completion for one prompt. Raises on any transport failure; the
    caller decides what its fallback is, and every caller has one."""
    settings = get_settings()
    if settings.saman_llm_url:
        return chat(
            [{"role": "user", "content": prompt}],
            temperature=temperature,
            timeout=timeout,
            max_tokens=max_tokens,
        )
    response = httpx.post(
        f"{(settings.ollama_url or '').rstrip('/')}/api/generate",
        json={
            "model": settings.ollama_model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        },
        timeout=timeout,
    )
    response.raise_for_status()
    return (response.json().get("response") or "").strip()


def chat(
    messages: list[dict], *, temperature: float = 0.1, timeout: float = 60.0, max_tokens: int = 260
) -> str:
    settings = get_settings()
    if settings.saman_llm_url:
        response = _post_remote(settings, messages, temperature, max_tokens, timeout)
        response.raise_for_status()
        choices = response.json().get("choices") or []
        return ((choices[0].get("message") or {}).get("content") or "").strip() if choices else ""
    response = httpx.post(
        f"{(settings.ollama_url or '').rstrip('/')}/api/chat",
        json={
            "model": settings.ollama_model,
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
            "messages": messages,
        },
        timeout=timeout,
    )
    response.raise_for_status()
    return (response.json().get("message", {}).get("content") or "").strip()


def stream_chat(
    messages: list[dict], *, temperature: float = 0.1, timeout: float = 60.0, max_tokens: int = 260
):
    """The same call as `chat`, yielding the text as it arrives.

    Yields plain text deltas; raises on transport failure like `chat`. The
    caller is responsible for the guards: a streamed answer is still checked
    sentence by sentence before any of it is shown (`knowledge.stream`).
    """
    import json as _json

    settings = get_settings()
    if settings.saman_llm_url:
        body = {
            "model": settings.saman_llm_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        url = f"{settings.saman_llm_url.rstrip('/')}/chat/completions"
        headers = _auth(settings.saman_llm_key or "")
        for attempt in (1, 2):
            with httpx.stream("POST", url, headers=headers, json=body, timeout=timeout) as resp:
                if resp.status_code == 429 and attempt == 1:
                    import time

                    try:
                        wait = float(resp.headers.get("retry-after", "2"))
                    except ValueError:
                        wait = 2.0
                    time.sleep(min(max(wait, 0.5), RETRY_AFTER_CAP))
                    continue
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        return
                    try:
                        chunk = _json.loads(data)
                    except ValueError:
                        continue
                    choices = chunk.get("choices") or []
                    first = (choices[0].get("delta") or {}) if choices else {}
                    delta = first.get("content") or ""
                    if delta:
                        yield delta
                return
        return
    with httpx.stream(
        "POST",
        f"{(settings.ollama_url or '').rstrip('/')}/api/chat",
        json={
            "model": settings.ollama_model,
            "stream": True,
            "options": {"temperature": temperature, "num_predict": max_tokens},
            "messages": messages,
        },
        timeout=timeout,
    ) as resp:
        resp.raise_for_status()
        for line in resp.iter_lines():
            if not line.strip():
                continue
            try:
                chunk = _json.loads(line)
            except ValueError:
                continue
            delta = (chunk.get("message") or {}).get("content") or ""
            if delta:
                yield delta
            if chunk.get("done"):
                return


#: A free tier meters requests and tokens per minute. One wait, bounded, on a
#: 429 is the difference between a demo that stutters and one that stops.
RETRY_AFTER_CAP = 20.0


def _post_remote(
    settings, messages: list[dict], temperature: float, max_tokens: int, timeout: float
):
    import time

    body = {
        "model": settings.saman_llm_model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    url = f"{settings.saman_llm_url.rstrip('/')}/chat/completions"
    headers = _auth(settings.saman_llm_key or "")
    response = httpx.post(url, headers=headers, json=body, timeout=timeout)
    if response.status_code == 429:
        try:
            wait = float(response.headers.get("retry-after", "2"))
        except ValueError:
            wait = 2.0
        time.sleep(min(max(wait, 0.5), RETRY_AFTER_CAP))
        response = httpx.post(url, headers=headers, json=body, timeout=timeout)
    return response
