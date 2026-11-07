"""The ticket -> verdict contract (DRAFT until wayfinder ticket 03 closes).

Everything the frontend, backend and tests agree on lives here:

* An order in ``data/orders.json`` is expanded into **ticket lines**, each with a
  stable ``line_id``. Assembly lines are ``A1, A2, ...`` (one per expected
  ingredient, plus one per "no X" modifier); pack lines are ``P1, P2, ...``.
* The model returns ``MODEL_VERDICT_SCHEMA`` (strict JSON schema): every line
  gets exactly one status, plus a list of anything seen that isn't on the ticket.
* The backend merges that with the ticket into the verdict the frontend renders
  (see ``merge_verdict``). Lines the model skipped become ``cant_verify``;
  the backend never invents a ``correct``.
"""

STATUSES = ("correct", "missing", "extra_or_wrong", "cant_verify")


def ticket_lines(order: dict) -> dict:
    """Expand an order into numbered Assembly and Pack ticket lines."""
    assembly, pack = [], []
    for d_i, dish in enumerate(order["dishes"], start=1):
        dish_label = f"{dish['name']} #{d_i}" if len(order["dishes"]) > 1 else dish["name"]
        for ing in dish.get("ingredients", []):
            qty = ing.get("qty", 1) if isinstance(ing, dict) else 1
            name = ing["name"] if isinstance(ing, dict) else ing
            assembly.append({
                "line_id": f"A{len(assembly) + 1}",
                "dish": dish_label,
                "expect": "present",
                "item": name,
                "qty": qty,
                "label": f"{dish_label}: {'extra ' if qty > 1 else ''}{name}",
            })
        for name in dish.get("exclude", []):
            assembly.append({
                "line_id": f"A{len(assembly) + 1}",
                "dish": dish_label,
                "expect": "absent",
                "item": name,
                "qty": 0,
                "label": f"{dish_label}: no {name}",
            })
    for item in order.get("pack", []):
        qty = item.get("qty", 1)
        pack.append({
            "line_id": f"P{len(pack) + 1}",
            "expect": "present",
            "item": item["name"],
            "qty": qty,
            "label": f"{qty}× {item['name']}" if qty > 1 else item["name"],
        })
    return {"assembly": assembly, "pack": pack}


def _line_result():
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["line_id", "status", "reason"],
        "properties": {
            "line_id": {"type": "string"},
            "status": {"type": "string", "enum": list(STATUSES)},
            "reason": {"type": "string", "description": "Under 12 words. Required for any status other than correct."},
        },
    }


# What the model must return. "observed" comes first on purpose: the model
# labels and counts what it sees before judging lines ("point, label, count").
MODEL_VERDICT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["observed", "assembly", "pack", "not_on_ticket"],
    "properties": {
        "observed": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["item", "count", "frame"],
                "properties": {
                    "item": {"type": "string"},
                    "count": {"type": "integer"},
                    "frame": {"type": "integer", "description": "Index of the clearest frame showing it."},
                },
            },
        },
        "assembly": {"type": "array", "items": _line_result()},
        "pack": {"type": "array", "items": _line_result()},
        "not_on_ticket": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["section", "item", "reason"],
                "properties": {
                    "section": {"type": "string", "enum": ["assembly", "pack"]},
                    "item": {"type": "string"},
                    "reason": {"type": "string"},
                },
            },
        },
    },
}


def merge_verdict(lines: dict, model_out: dict | None) -> dict:
    """Combine ticket lines with the model's answer into the frontend verdict.

    ``model_out=None`` means the check was unavailable: every line becomes
    ``cant_verify`` so the worker verifies by hand. Never a fake correct.
    """
    sections = {}
    for section in ("assembly", "pack"):
        by_id = {}
        if model_out:
            for r in model_out.get(section, []) or []:
                if isinstance(r, dict) and r.get("status") in STATUSES and r.get("line_id") not in by_id:
                    by_id[r.get("line_id")] = r
        out = []
        for line in lines[section]:
            r = by_id.get(line["line_id"])
            if r is None:
                status = "cant_verify"
                reason = "Check unavailable — verify by hand" if model_out is None else "Not reported by the check"
            else:
                status, reason = r["status"], (r.get("reason") or "").strip()
            out.append({
                "line_id": line["line_id"],
                "label": line["label"],
                "status": status,
                "reason": reason,
                "resolved": False,  # set by Mark fixed / tap-to-confirm
            })
        sections[section] = out
    extras = []
    if model_out:
        for e in model_out.get("not_on_ticket", []) or []:
            if isinstance(e, dict) and e.get("item"):
                extras.append({"section": e.get("section", "pack"), "item": e["item"],
                               "reason": e.get("reason", ""), "resolved": False})
    return {"sections": sections, "not_on_ticket": extras}
