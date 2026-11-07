"""Synthetic orders and their in-memory state machine.

States: waiting -> building (Start) -> checking (Done) -> needs_fix | ready
-> picked_up. An order is ready only when every verdict line is correct or
resolved by the worker, every not-on-ticket item is resolved, and (if the
order has an allergy note) the worker tapped Allergy checked.
"""

import copy
import json
import threading
from pathlib import Path

from contract import ticket_lines

DATA_DIR = Path(__file__).parent / "data"


class OrderError(Exception):
    """A request that doesn't fit the order's current state (HTTP 409/404)."""

    def __init__(self, message: str, status: int = 409):
        super().__init__(message)
        self.status = status


class OrderStore:
    def __init__(self, path: Path = DATA_DIR / "orders.json"):
        self._path = path
        self._lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        raw = json.loads(self._path.read_text(encoding="utf-8"))["orders"]
        with self._lock:
            self._orders = {}
            for o in raw:
                self._orders[o["id"]] = {
                    **o,
                    "ticket": ticket_lines(o),
                    "state": "waiting",
                    "verdict": None,
                    "allergy_checked": False,
                }

    # ---- reads ----

    def get(self, order_id: str) -> dict:
        with self._lock:
            o = self._orders.get(str(order_id))
            if o is None:
                raise OrderError(f"No order {order_id}", 404)
            return copy.deepcopy(o)

    def list(self) -> list[dict]:
        with self._lock:
            return [self._public(o) for o in self._orders.values()]

    def public(self, order_id: str) -> dict:
        with self._lock:
            o = self._orders.get(str(order_id))
            if o is None:
                raise OrderError(f"No order {order_id}", 404)
            return self._public(o)

    # ---- transitions ----

    def start(self, order_id: str) -> dict:
        return self._transition(order_id, {"waiting", "building", "needs_fix", "ready"}, "building",
                                reset_verdict=True)

    def begin_check(self, order_id: str) -> dict:
        """Building -> checking. Returns a copy of the order for the model call."""
        self._transition(order_id, {"building"}, "checking")
        return self.get(order_id)

    def finish_check(self, order_id: str, verdict: dict) -> dict:
        with self._lock:
            o = self._orders[str(order_id)]
            o["verdict"] = verdict
            o["allergy_checked"] = False
            o["state"] = "ready" if self._all_clear(o) else "needs_fix"
            return self._public(o)

    def abort_check(self, order_id: str) -> None:
        """Model call crashed unexpectedly: put the order back so Done can be retried."""
        with self._lock:
            o = self._orders[str(order_id)]
            if o["state"] == "checking":
                o["state"] = "building"

    def confirm(self, order_id: str, action: str, line_id: str | None = None,
                item: str | None = None) -> dict:
        with self._lock:
            o = self._orders.get(str(order_id))
            if o is None:
                raise OrderError(f"No order {order_id}", 404)
            if o["state"] not in ("needs_fix", "ready") or o["verdict"] is None:
                raise OrderError(f"Order {order_id} has no verdict to confirm (state: {o['state']})")

            if action == "allergy_checked":
                if not o["needs"].get("allergy"):
                    raise OrderError(f"Order {order_id} has no allergy note", 400)
                o["allergy_checked"] = True
            elif action in ("mark_fixed", "confirm"):
                target = self._find_target(o, line_id, item)
                if target.get("status") == "correct":
                    raise OrderError(f"{line_id} is already correct", 400)
                if action == "confirm" and target.get("status") not in ("cant_verify", None):
                    raise OrderError("Use mark_fixed for missing / extra lines", 400)
                if action == "mark_fixed" and target.get("status") == "cant_verify":
                    raise OrderError("Use confirm for can't-verify lines", 400)
                target["resolved"] = True
            else:
                raise OrderError("action must be mark_fixed, confirm or allergy_checked", 400)

            o["state"] = "ready" if self._all_clear(o) else "needs_fix"
            return self._public(o)

    def pickup(self, order_id: str) -> dict:
        return self._transition(order_id, {"ready"}, "picked_up")

    # ---- internals ----

    def _transition(self, order_id, allowed, new_state, reset_verdict=False):
        with self._lock:
            o = self._orders.get(str(order_id))
            if o is None:
                raise OrderError(f"No order {order_id}", 404)
            if o["state"] not in allowed:
                raise OrderError(f"Order {order_id} is {o['state']}; can't move to {new_state}")
            o["state"] = new_state
            if reset_verdict:
                o["verdict"] = None
                o["allergy_checked"] = False
            return self._public(o)

    @staticmethod
    def _find_target(o, line_id, item):
        v = o["verdict"]
        if line_id:
            for sec in v["sections"].values():
                for line in sec:
                    if line["line_id"] == line_id:
                        return line
            raise OrderError(f"No line {line_id} on order {o['id']}", 400)
        if item:
            for e in v["not_on_ticket"]:
                if e["item"] == item:
                    return e
            raise OrderError(f"No not-on-ticket item {item!r} on order {o['id']}", 400)
        raise OrderError("line_id or item is required", 400)

    @staticmethod
    def _all_clear(o) -> bool:
        v = o["verdict"]
        if v is None:
            return False
        lines = [l for sec in v["sections"].values() for l in sec]
        if any(l["status"] != "correct" and not l["resolved"] for l in lines):
            return False
        if any(not e["resolved"] for e in v["not_on_ticket"]):
            return False
        if o["needs"].get("allergy") and not o["allergy_checked"]:
            return False
        return True

    @staticmethod
    def _handoff(o) -> dict:
        v = o["verdict"]
        lines = [l for sec in v["sections"].values() for l in sec]
        fixed = sum(1 for l in lines if l["status"] in ("missing", "extra_or_wrong"))
        confirmed = sum(1 for l in lines if l["status"] == "cant_verify")
        if fixed or confirmed:
            parts = []
            if fixed:
                parts.append(f"{fixed} fixed")
            if confirmed:
                parts.append(f"{confirmed} confirmed by hand")
            result = "Checked — " + ", ".join(parts)
        else:
            result = "Checked — all correct"
        needs = {k: val for k, val in o["needs"].items() if val}
        return {
            "order_id": o["id"],
            "customer_first_name": o["customer_first_name"],
            "bags": o["bags"],
            "check_result": result,
            "needs": needs,
        }

    def _public(self, o) -> dict:
        out = {
            "id": o["id"],
            "customer_first_name": o["customer_first_name"],
            "source": o["source"],
            "state": o["state"],
            "ticket": o["ticket"],
            "needs": o["needs"],
            "has_allergy": bool(o["needs"].get("allergy")),
            "allergy_checked": o["allergy_checked"],
            "verdict": copy.deepcopy(o["verdict"]),
            "handoff": self._handoff(o) if o["state"] in ("ready", "picked_up") else None,
        }
        return out
