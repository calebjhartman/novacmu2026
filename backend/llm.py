"""One OpenRouter vision call per order check, with fallback and mock mode.

Primary: google/gemini-3.5-flash. One retry on anthropic/claude-haiku-5.5.
If both fail (timeout, HTTP error, bad JSON) the caller gets ``None`` and
shows "Check unavailable — verify by hand". MOCK_LLM=1 returns canned
verdicts from data/mock_verdicts.json without any network call.
"""

import json
import logging
import os
import time
from pathlib import Path

import requests

from contract import MODEL_VERDICT_SCHEMA

log = logging.getLogger("order_check.llm")

DATA_DIR = Path(__file__).parent / "data"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
PRIMARY_MODEL = os.getenv("ORDER_CHECK_MODEL", "google/gemini-3.5-flash")
FALLBACK_MODEL = os.getenv("ORDER_CHECK_FALLBACK_MODEL", "anthropic/claude-haiku-5.5")
TIMEOUT_S = float(os.getenv("ORDER_CHECK_TIMEOUT_S", "10"))
MAX_FRAMES = 15


def api_key() -> str | None:
    # The starter guide uses both names; accept either. Never log the value.
    return os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENROUTER_KEY")


def mock_enabled() -> bool:
    return os.getenv("MOCK_LLM", "").strip().lower() in ("1", "true", "yes")


SYSTEM_PROMPT = """You check food orders at a fast-casual bowl restaurant from an overhead camera.

You get: (1) the order ticket as JSON lines, (2) one labeled reference photo of this
restaurant's ingredients and pack items (the "ingredient board"), (3) numbered frames
from the camera, in time order, while one worker assembled the bowl(s) and packed the bag.

Do this in order:
1. In "observed", list every ingredient and pack item you can actually see, using the
   names from the ingredient board, with a count and the index of the clearest frame.
2. For every ticket line, give exactly one status:
   - correct: clearly seen and matches the ticket (an "absent" line is correct when the
     item is clearly NOT added to that dish).
   - missing: an expected item is clearly not there, or there are fewer than the ticket qty.
   - extra_or_wrong: an item the ticket says to leave out was added, the wrong item was
     used, or there are more than the ticket qty.
   - cant_verify: the view is blocked, blurry or ambiguous. Prefer this over guessing.
3. In "not_on_ticket", list items you saw go into a dish or the bag that no ticket line covers.

Use each line_id exactly once. Keep every reason under 12 words. Judge only what the
frames show; never assume a step happened off camera."""


def build_messages(order: dict, frames: list[str], board: str | None) -> list[dict]:
    lines = order["ticket"]
    ticket_text = json.dumps({
        "order_id": order["id"],
        "assembly": [{k: l[k] for k in ("line_id", "dish", "item", "expect", "qty")} for l in lines["assembly"]],
        "pack": [{k: l[k] for k in ("line_id", "item", "expect", "qty")} for l in lines["pack"]],
    }, ensure_ascii=False)

    # OpenRouter recommends text before images.
    content: list[dict[str, object]] = [{"type": "text", "text": f"Order ticket:\n{ticket_text}"}]
    if board:
        content.append({"type": "text", "text": "Ingredient board (reference photo, labeled):"})
        content.append({"type": "image_url", "image_url": {"url": board}})
    content.append({"type": "text", "text": f"Camera frames 0 to {len(frames) - 1}, in time order:"})
    for i, f in enumerate(frames):
        content.append({"type": "text", "text": f"Frame {i}"})
        content.append({"type": "image_url", "image_url": {"url": f}})

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": content},
    ]


def _request_body(model: str, messages: list[dict]) -> dict:
    body = {
        "model": model,
        "messages": messages,
        "temperature": 0,
        "max_tokens": 1500,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "order_verdict", "strict": True, "schema": MODEL_VERDICT_SCHEMA},
        },
        # Only route to endpoints that honor the schema.
        "provider": {"require_parameters": True},
    }
    effort = os.getenv("ORDER_CHECK_REASONING", "low").strip()
    if effort:
        body["reasoning"] = {"effort": effort}
    return body


def _call_model(model: str, messages: list[dict], key: str) -> dict:
    resp = requests.post(
        OPENROUTER_URL,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "X-Title": "Order Check (NOVA hackathon)",
        },
        json=_request_body(model, messages),
        timeout=TIMEOUT_S,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"OpenRouter error: {str(data['error'])[:300]}")
    content = data["choices"][0]["message"]["content"]
    if isinstance(content, list):  # some providers return content parts
        content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
    content = content.strip()
    if content.startswith("```"):
        content = content.strip("`").removeprefix("json").strip()
    out = json.loads(content)
    if not isinstance(out, dict) or "assembly" not in out or "pack" not in out:
        raise ValueError("response is missing assembly/pack")
    return out


def _mock_verdict(order: dict) -> dict:
    """Canned verdict: data/mock_verdicts.json by order id, else all correct."""
    path = DATA_DIR / "mock_verdicts.json"
    canned = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if order["id"] in canned:
        return canned[order["id"]]
    lines = order["ticket"]
    return {
        "observed": [],
        "assembly": [{"line_id": l["line_id"], "status": "correct", "reason": ""} for l in lines["assembly"]],
        "pack": [{"line_id": l["line_id"], "status": "correct", "reason": ""} for l in lines["pack"]],
        "not_on_ticket": [],
    }


def check_order(order: dict, frames: list[str], board: str | None) -> tuple[dict | None, dict]:
    """Run the order check. Returns (model_output or None, meta)."""
    if mock_enabled():
        return _mock_verdict(order), {"source": "mock", "model": "mock", "attempts": [], "seconds": 0.0}

    key = api_key()
    if not key:
        log.error("No OPENROUTER_API_KEY set; check unavailable")
        return None, {"source": "unavailable", "model": None, "attempts": ["no API key"], "seconds": 0.0}

    messages = build_messages(order, frames, board)
    attempts = []
    t0 = time.monotonic()
    for model in (PRIMARY_MODEL, FALLBACK_MODEL):
        start = time.monotonic()
        try:
            out = _call_model(model, messages, key)
            dt = time.monotonic() - start
            log.info("order %s checked by %s in %.1fs", order["id"], model, dt)
            attempts.append(f"{model}: ok in {dt:.1f}s")
            return out, {"source": "llm", "model": model, "attempts": attempts,
                         "seconds": round(time.monotonic() - t0, 2)}
        except Exception as e:  # timeout, HTTP error, bad JSON: try the next model
            dt = time.monotonic() - start
            log.warning("order %s: %s failed after %.1fs: %s", order["id"], model, dt, e)
            attempts.append(f"{model}: {type(e).__name__} after {dt:.1f}s")
    return None, {"source": "unavailable", "model": None, "attempts": attempts,
                  "seconds": round(time.monotonic() - t0, 2)}
