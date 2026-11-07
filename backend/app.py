"""Order check backend (Flask).

Routes (all JSON):
  GET  /health                      -> {ok, mock, model, fallback, has_key, board}
  GET  /orders                      -> {orders: [...]}
  GET  /orders/<id>                 -> order (ticket, state, verdict, handoff)
  POST /orders/<id>/start           -> order in "building"
  POST /order_check                 {order_id, frames: [base64 JPEG...]} -> order with verdict
  POST /orders/<id>/confirm         {action: mark_fixed|confirm|allergy_checked, line_id?|item?}
  POST /orders/<id>/pickup          -> order in "picked_up"
  POST /reset                       -> reload orders.json (demo reruns)

Run:  python app.py      (MOCK_LLM=1 for canned verdicts, no API key needed)
"""

import base64
import logging
import os
from pathlib import Path

from flask import Flask, jsonify, request

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).parent / ".env")
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:  # python-dotenv is optional
    pass

import llm
from contract import merge_verdict
from orders import OrderError, OrderStore

DATA_DIR = Path(__file__).parent / "data"
BOARD_CANDIDATES = ("ingredient_board.jpg", "ingredient_board.jpeg", "ingredient_board.png")
MAX_FRAME_BYTES = 2 * 1024 * 1024  # per decoded frame


def load_board() -> str | None:
    """The labeled ingredient board photo as a data URL, or None if not shot yet."""
    for name in BOARD_CANDIDATES:
        p = DATA_DIR / name
        if p.exists():
            mime = "image/png" if p.suffix == ".png" else "image/jpeg"
            return f"data:{mime};base64,{base64.b64encode(p.read_bytes()).decode()}"
    return None


def normalize_frame(f) -> str:
    """Accept a data URL or bare base64 JPEG/PNG; return a data URL."""
    if not isinstance(f, str) or not f:
        raise ValueError("each frame must be a non-empty base64 string")
    if f.startswith("data:image/"):
        header, _, b64 = f.partition(",")
        if ";base64" not in header:
            raise ValueError("frame data URLs must be base64")
    else:
        header, b64 = "data:image/jpeg;base64", f
    try:
        raw = base64.b64decode(b64, validate=True)
    except Exception:
        raise ValueError("frame is not valid base64")
    if len(raw) > MAX_FRAME_BYTES:
        raise ValueError("frame larger than 2 MB; send ~640 px JPEGs")
    return f"{header},{b64}"


def create_app(store: OrderStore | None = None) -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 40 * 1024 * 1024
    store = store or OrderStore()
    board = load_board()
    if board is None:
        app.logger.warning("No ingredient board photo in backend/data/ yet; checks run without it")

    allowed_origin = os.getenv("FRONTEND_ORIGIN", "*")

    @app.after_request
    def cors(resp):
        resp.headers["Access-Control-Allow-Origin"] = allowed_origin
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        return resp

    @app.errorhandler(OrderError)
    def order_error(e: OrderError):
        return jsonify(error=str(e)), e.status

    @app.errorhandler(413)
    def too_large(_):
        return jsonify(error="request too large; send fewer or smaller frames"), 413

    @app.get("/health")
    def health():
        return jsonify(ok=True, mock=llm.mock_enabled(), model=llm.PRIMARY_MODEL,
                       fallback=llm.FALLBACK_MODEL, has_key=bool(llm.api_key()),
                       board=board is not None)

    @app.get("/orders")
    def list_orders():
        return jsonify(orders=store.list())

    @app.get("/orders/<order_id>")
    def get_order(order_id):
        return jsonify(store.public(order_id))

    @app.post("/orders/<order_id>/start")
    def start(order_id):
        return jsonify(store.start(order_id))

    @app.post("/order_check")
    def order_check():
        body = request.get_json(silent=True) or {}
        order_id = str(body.get("order_id", "")).strip()
        frames = body.get("frames")
        if not order_id:
            return jsonify(error="order_id is required"), 400
        if not isinstance(frames, list) or not frames:
            return jsonify(error="frames must be a non-empty list"), 400
        if len(frames) > llm.MAX_FRAMES:
            return jsonify(error=f"send at most {llm.MAX_FRAMES} frames"), 400
        try:
            frames = [normalize_frame(f) for f in frames]
        except ValueError as e:
            return jsonify(error=str(e)), 400

        order = store.begin_check(order_id)  # 404/409 if not building
        try:
            model_out, meta = llm.check_order(order, frames, board)
            verdict = merge_verdict(order["ticket"], model_out)
        except Exception:
            store.abort_check(order_id)
            raise
        verdict["meta"] = meta
        verdict["unavailable"] = model_out is None
        return jsonify(store.finish_check(order_id, verdict))

    @app.post("/orders/<order_id>/confirm")
    def confirm(order_id):
        body = request.get_json(silent=True) or {}
        return jsonify(store.confirm(order_id, body.get("action", ""),
                                     line_id=body.get("line_id"), item=body.get("item")))

    @app.post("/orders/<order_id>/pickup")
    def pickup(order_id):
        return jsonify(store.pickup(order_id))

    @app.post("/reset")
    def reset():
        store.reset()
        return jsonify(orders=store.list())

    return app


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    port = int(os.getenv("PORT", "5000"))
    create_app().run(host="127.0.0.1", port=port, debug=os.getenv("FLASK_DEBUG") == "1")
