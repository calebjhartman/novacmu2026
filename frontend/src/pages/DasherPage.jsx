import { useEffect, useRef, useState } from "react";
import { api, orderTitle } from "../api.js";

// While the worker builds the order, grab a small JPEG from the camera every
// FRAME_INTERVAL_MS and keep the most recent MAX_FRAMES. "Done" sends them to
// the backend, which asks Gemini (via OpenRouter) to check them against the ticket.
const FRAME_INTERVAL_MS = 1500;
const MAX_FRAMES = 8; // backend allows 15; fewer = faster + cheaper
const FRAME_WIDTH = 640;

const STATUS_TEXT = {
  correct: "✓ Correct",
  missing: "✗ Missing",
  extra_or_wrong: "✗ Extra / wrong",
  cant_verify: "? Can't verify",
};

function captureFrame(video, canvas) {
  if (!video || video.readyState < 2 || !video.videoWidth) return null;
  const scale = FRAME_WIDTH / video.videoWidth;
  canvas.width = FRAME_WIDTH;
  canvas.height = Math.round(video.videoHeight * scale);
  canvas.getContext("2d").drawImage(video, 0, 0, canvas.width, canvas.height);
  return canvas.toDataURL("image/jpeg", 0.7);
}

export default function DasherPage({ order: initialOrder, onDone, onLogout }) {
  const videoRef = useRef(null);
  const canvasRef = useRef(null);
  const framesRef = useRef([]);
  const [order, setOrder] = useState(initialOrder);
  const [cameraError, setCameraError] = useState("");
  const [ready, setReady] = useState(false);
  const [frameCount, setFrameCount] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const building = order?.state === "building";

  // Camera
  useEffect(() => {
    let stream;
    let cancelled = false;
    const video = videoRef.current;

    async function startCamera() {
      try {
        if (!navigator.mediaDevices?.getUserMedia) {
          throw new Error("Camera access requires HTTPS or localhost.");
        }
        stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
        if (cancelled) {
          stream.getTracks().forEach((t) => t.stop());
          return;
        }
        video.srcObject = stream;
        await video.play();
        if (!cancelled) setReady(true);
      } catch (err) {
        stream?.getTracks().forEach((t) => t.stop());
        if (cancelled) return;
        if (err.name === "NotAllowedError") {
          setCameraError("Camera permission was denied. Allow access and try again.");
        } else if (err.name === "NotFoundError") {
          setCameraError("No camera was found on this device.");
        } else if (err.name === "NotReadableError") {
          setCameraError("The camera could not start. It may be in use.");
        } else {
          setCameraError(err.message || "Unable to access the camera.");
        }
      }
    }

    startCamera();
    return () => {
      cancelled = true;
      stream?.getTracks().forEach((t) => t.stop());
      if (video) video.srcObject = null;
    };
  }, []);

  // Frame sampling while building
  useEffect(() => {
    if (!ready || !building) return;
    framesRef.current = [];
    setFrameCount(0);
    const id = setInterval(() => {
      const f = captureFrame(videoRef.current, canvasRef.current);
      if (!f) return;
      framesRef.current = [...framesRef.current, f].slice(-MAX_FRAMES);
      setFrameCount(framesRef.current.length);
    }, FRAME_INTERVAL_MS);
    return () => clearInterval(id);
  }, [ready, building]);

  async function run(fn) {
    setBusy(true);
    setError("");
    try {
      setOrder(await fn());
    } catch (err) {
      setError(err.message || "Request failed.");
    } finally {
      setBusy(false);
    }
  }

  function handleCheck() {
    let frames = framesRef.current;
    if (frames.length === 0) {
      const f = captureFrame(videoRef.current, canvasRef.current);
      frames = f ? [f] : [];
    }
    if (frames.length === 0) {
      setError("No camera frames yet — wait for the camera to connect.");
      return;
    }
    run(() => api.check(order.id, frames));
  }

  const verdict = order?.verdict;
  const lines = order?.ticket
    ? [...order.ticket.assembly, ...order.ticket.pack]
    : [];

  return (
    <main className="page">
      <section className="camera-card">
        <h1>{order ? orderTitle(order) : "Dasher"}</h1>
        {order && (
          <p className="subtitle">
            Order #{order.id} · {order.state.replace("_", " ")}
          </p>
        )}

        {order?.has_allergy && (
          <p className="allergy-banner">⚠ {order.needs.allergy}</p>
        )}

        {order && !verdict && (
          <section className="ingredients-section" aria-labelledby="ticket-title">
            <h2 id="ticket-title">Ticket</h2>
            <ul className="ingredients-list">
              {lines.map((l) => (
                <li key={l.line_id}>{l.label}</li>
              ))}
            </ul>
          </section>
        )}

        {verdict && (
          <section className="ingredients-section" aria-labelledby="verdict-title">
            <h2 id="verdict-title">
              Check result
              <span className="verdict-meta">
                {verdict.unavailable
                  ? " — check unavailable, verify by hand"
                  : ` — ${verdict.meta?.model} in ${verdict.meta?.seconds}s`}
              </span>
            </h2>
            <ul className="verdict-list">
              {["assembly", "pack"].flatMap((sec) =>
                verdict.sections[sec].map((l) => (
                  <li key={l.line_id} className={`verdict-line status-${l.status}${l.resolved ? " resolved" : ""}`}>
                    <div>
                      <strong>{l.label}</strong>
                      <span className="verdict-status">
                        {l.resolved ? "✓ Resolved" : STATUS_TEXT[l.status]}
                        {l.reason && l.status !== "correct" ? ` — ${l.reason}` : ""}
                      </span>
                    </div>
                    {l.status !== "correct" && !l.resolved && (
                      <button
                        className="order-start"
                        type="button"
                        disabled={busy}
                        onClick={() =>
                          run(() =>
                            api.confirm(order.id, l.status === "cant_verify" ? "confirm" : "mark_fixed", {
                              line_id: l.line_id,
                            })
                          )
                        }
                      >
                        {l.status === "cant_verify" ? "Confirm" : "Mark fixed"}
                      </button>
                    )}
                  </li>
                ))
              )}
              {verdict.not_on_ticket.map((e) => (
                <li key={`x-${e.item}`} className={`verdict-line status-extra_or_wrong${e.resolved ? " resolved" : ""}`}>
                  <div>
                    <strong>Not on ticket: {e.item}</strong>
                    <span className="verdict-status">{e.resolved ? "✓ Resolved" : e.reason}</span>
                  </div>
                  {!e.resolved && (
                    <button
                      className="order-start"
                      type="button"
                      disabled={busy}
                      onClick={() => run(() => api.confirm(order.id, "mark_fixed", { item: e.item }))}
                    >
                      Mark fixed
                    </button>
                  )}
                </li>
              ))}
            </ul>

            {order.has_allergy && !order.allergy_checked && order.state !== "picked_up" && (
              <button
                className="glass-button verdict-action"
                type="button"
                disabled={busy}
                onClick={() => run(() => api.confirm(order.id, "allergy_checked"))}
              >
                Allergy checked
              </button>
            )}
          </section>
        )}

        {order?.handoff && (
          <section className="ingredients-section">
            <h2>Hand-off</h2>
            <p className="handoff-line">{order.handoff.check_result}</p>
            {Object.entries(order.handoff.needs).map(([k, v]) => (
              <p className="handoff-line" key={k}>
                <strong>{k}:</strong> {v}
              </p>
            ))}
          </section>
        )}

        <div className="camera-preview">
          <video ref={videoRef} autoPlay playsInline muted aria-label="Live camera preview" />
        </div>
        <canvas ref={canvasRef} hidden />

        <p className="form-message" role="status">
          {error ||
            cameraError ||
            (busy && order?.state === "building"
              ? "Checking with Gemini…"
              : building && ready
                ? `Camera connected · ${frameCount} frame${frameCount === 1 ? "" : "s"} captured`
                : ready
                  ? "Camera connected."
                  : "Waiting for camera access…")}
        </p>

        {building && (
          <button className="login-button" type="button" disabled={busy || !ready} onClick={handleCheck}>
            {busy ? "Checking…" : "Done — check order"}
            <span aria-hidden="true">✓</span>
          </button>
        )}

        {order?.state === "needs_fix" && (
          <button className="login-button" type="button" disabled={busy} onClick={() => run(() => api.start(order.id))}>
            Re-check from camera
          </button>
        )}

        {order?.state === "ready" && (
          <button className="login-button" type="button" disabled={busy} onClick={() => run(() => api.pickup(order.id))}>
            Picked up by Dasher
          </button>
        )}

        {onDone ? (
          <button className="orders-back verdict-back" type="button" onClick={onDone}>
            ← Back to orders
          </button>
        ) : onLogout ? (
          <button className="login-button" type="button" onClick={onLogout}>
            Log out
          </button>
        ) : null}
      </section>
    </main>
  );
}
