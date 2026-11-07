"""Integration tests against the Flask routes (mock mode unless stated)."""

import requests

import llm
from conftest import FRAME


def check(client, order_id, frames=None):
    return client.post("/order_check", json={"order_id": order_id, "frames": frames or [FRAME] * 12})


def statuses(order):
    return {l["line_id"]: l["status"] for s in order["verdict"]["sections"].values() for l in s}


# ---- happy and sad paths ----

def test_happy_path_goes_ready_with_handoff(mock_env, client):
    assert client.post("/orders/1042/start").json["state"] == "building"
    o = check(client, "1042").json
    assert o["state"] == "ready"
    assert set(statuses(o).values()) == {"correct"}
    assert o["verdict"]["meta"]["source"] == "mock"
    card = o["handoff"]
    assert card["customer_first_name"] == "Maya"
    assert card["check_result"] == "Checked — all correct"
    assert "allergy" not in card["needs"]
    assert client.post("/orders/1042/pickup").json["state"] == "picked_up"


def test_sad_path_needs_fix_until_every_line_and_allergy_resolved(mock_env, client):
    client.post("/orders/1043/start")
    o = check(client, "1043").json
    assert o["state"] == "needs_fix"
    s = statuses(o)
    assert s["A4"] == "missing" and s["A5"] == "extra_or_wrong" and s["P3"] == "cant_verify"
    labels = {l["line_id"]: l["label"] for l in o["verdict"]["sections"]["assembly"]}
    assert labels["A4"] == "Steak bowl: guac" and labels["A5"] == "Steak bowl: no cheese"

    for line in ("A4", "A5"):
        o = client.post("/orders/1043/confirm", json={"action": "mark_fixed", "line_id": line}).json
    assert o["state"] == "needs_fix"
    o = client.post("/orders/1043/confirm", json={"action": "confirm", "line_id": "P3"}).json
    assert o["state"] == "needs_fix", "allergy order must also need Allergy checked"
    o = client.post("/orders/1043/confirm", json={"action": "allergy_checked"}).json
    assert o["state"] == "ready"
    assert o["handoff"]["check_result"] == "Checked — 2 fixed, 1 confirmed by hand"
    assert o["handoff"]["needs"]["allergy"].startswith("Dairy allergy")


def test_wrong_confirm_action_for_line_is_rejected(mock_env, client):
    client.post("/orders/1043/start")
    check(client, "1043")
    assert client.post("/orders/1043/confirm", json={"action": "confirm", "line_id": "A4"}).status_code == 400
    assert client.post("/orders/1043/confirm", json={"action": "mark_fixed", "line_id": "P3"}).status_code == 400
    assert client.post("/orders/1043/confirm", json={"action": "mark_fixed", "line_id": "A1"}).status_code == 400
    assert client.post("/orders/1043/confirm", json={"action": "bogus"}).status_code == 400


def test_restart_clears_previous_verdict(mock_env, client):
    client.post("/orders/1043/start")
    check(client, "1043")
    o = client.post("/orders/1043/start").json
    assert o["state"] == "building" and o["verdict"] is None


def test_reset_restores_all_orders(mock_env, client):
    client.post("/orders/1042/start")
    orders = client.post("/reset").json["orders"]
    assert {o["state"] for o in orders} == {"waiting"}


# ---- request validation ----

def test_check_requires_start(mock_env, client):
    assert check(client, "1042").status_code == 409


def test_unknown_order_is_404(mock_env, client):
    assert client.get("/orders/9999").status_code == 404
    assert client.post("/orders/9999/start").status_code == 404


def test_frame_validation(mock_env, client):
    client.post("/orders/1042/start")
    assert check(client, "1042", frames=[FRAME] * 16).status_code == 400
    assert check(client, "1042", frames=["not base64!!"]).status_code == 400
    assert client.post("/order_check", json={"order_id": "1042"}).status_code == 400
    # data URLs are accepted too
    assert check(client, "1042", frames=[f"data:image/jpeg;base64,{FRAME}"]).status_code == 200


def test_orders_list_has_ticket_lines(mock_env, client):
    orders = client.get("/orders").json["orders"]
    assert [o["id"] for o in orders] == ["1042", "1043", "1044", "1045"]
    veggie = orders[2]["ticket"]
    assert [l["label"] for l in veggie["assembly"]][-2:] == ["Veggie bowl: extra salsa", "Veggie bowl: no sour cream"]


# ---- live mode with a fake OpenRouter ----

class FakeResp:
    def __init__(self, status, payload):
        self.status_code, self._payload, self.text = status, payload, str(payload)

    def json(self):
        return self._payload


def ok_payload(content):
    return {"choices": [{"message": {"content": content}}]}


def test_primary_timeout_falls_back_to_haiku(live_env, client, monkeypatch):
    calls = []

    def fake_post(url, headers, json, timeout):
        calls.append(json["model"])
        assert json["response_format"]["json_schema"]["strict"] is True
        assert json["provider"] == {"require_parameters": True}
        assert headers["Authorization"] == "Bearer test-key"
        if json["model"] == llm.PRIMARY_MODEL:
            raise requests.Timeout("slow")
        body = ('{"observed": [], "assembly": [{"line_id": "A1", "status": "correct", "reason": ""}],'
                ' "pack": [], "not_on_ticket": [{"section": "pack", "item": "napkins", "reason": "extra"}]}')
        return FakeResp(200, ok_payload(body))

    monkeypatch.setattr(llm.requests, "post", fake_post)
    client.post("/orders/1042/start")
    o = check(client, "1042").json
    assert calls == [llm.PRIMARY_MODEL, llm.FALLBACK_MODEL]
    assert o["verdict"]["meta"]["model"] == llm.FALLBACK_MODEL
    s = statuses(o)
    assert s["A1"] == "correct"
    # lines the model skipped are never assumed correct
    assert all(v == "cant_verify" for k, v in s.items() if k != "A1")
    assert o["verdict"]["not_on_ticket"][0]["item"] == "napkins"
    assert o["state"] == "needs_fix"


def test_both_models_fail_means_unavailable_never_correct(live_env, client, monkeypatch):
    monkeypatch.setattr(llm.requests, "post", lambda *a, **k: FakeResp(500, {"error": "down"}))
    client.post("/orders/1042/start")
    o = check(client, "1042").json
    assert o["verdict"]["unavailable"] is True
    assert set(statuses(o).values()) == {"cant_verify"}
    assert o["verdict"]["sections"]["assembly"][0]["reason"] == "Check unavailable — verify by hand"
    assert o["state"] == "needs_fix"


def test_bad_json_from_model_falls_back(live_env, client, monkeypatch):
    replies = iter([FakeResp(200, ok_payload("sorry, I can't")),
                    FakeResp(200, ok_payload('```json\n{"observed":[],"assembly":[],"pack":[],"not_on_ticket":[]}\n```'))])
    monkeypatch.setattr(llm.requests, "post", lambda *a, **k: next(replies))
    client.post("/orders/1042/start")
    o = check(client, "1042").json
    assert o["verdict"]["meta"]["model"] == llm.FALLBACK_MODEL
    assert o["verdict"]["unavailable"] is False


def test_no_api_key_is_unavailable(monkeypatch, client):
    monkeypatch.delenv("MOCK_LLM", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_KEY", raising=False)
    client.post("/orders/1042/start")
    o = check(client, "1042").json
    assert o["verdict"]["unavailable"] is True


def test_prompt_puts_ticket_text_before_images():
    order = {"id": "1", "ticket": {
        "assembly": [{"line_id": "A1", "dish": "Bowl", "item": "rice", "expect": "present", "qty": 1}],
        "pack": [{"line_id": "P1", "item": "fork", "expect": "present", "qty": 1}]}}
    msgs = llm.build_messages(order, ["data:image/jpeg;base64,AAA"] * 3, board="data:image/jpeg;base64,BBB")
    parts = msgs[1]["content"]
    assert parts[0]["type"] == "text" and '"line_id": "A1"' in parts[0]["text"]
    assert sum(p["type"] == "image_url" for p in parts) == 4  # board + 3 frames
