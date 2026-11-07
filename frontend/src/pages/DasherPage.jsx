import { useEffect, useRef, useState } from "react";

export default function DasherPage({ order, onDone, onLogout }) {
  const videoRef = useRef(null);
  const [error, setError] = useState("");
  const [ready, setReady] = useState(false);

  const components = Array.isArray(order?.components)
  ? order.components
  : [];

  useEffect(() => {
    let stream;
    let cancelled = false;
    const video = videoRef.current;

    async function startCamera() {
      try {
        if (!navigator.mediaDevices?.getUserMedia) {
          throw new Error("Camera access requires HTTPS or localhost.");
        }

        stream = await navigator.mediaDevices.getUserMedia({
          video: true,
          audio: false,
        });

        if (cancelled) {
          stream.getTracks().forEach((track) => track.stop());
          return;
        }

        video.srcObject = stream;
        await video.play();

        if (!cancelled) {
          setReady(true);
        }
      } catch (err) {
        stream?.getTracks().forEach((track) => track.stop());

        if (cancelled) return;

        if (err.name === "NotAllowedError") {
          setError("Camera permission was denied. Allow access and try again.");
        } else if (err.name === "NotFoundError") {
          setError("No camera was found on this device.");
        } else if (err.name === "NotReadableError") {
          setError("The camera could not start. It may be in use.");
        } else {
          setError(err.message || "Unable to access the camera.");
        }
      }
    }

    startCamera();

    return () => {
      cancelled = true;
      stream?.getTracks().forEach((track) => track.stop());

      if (video) {
        video.srcObject = null;
      }
    };
  }, []);

  return (
    <main className="page">
      <section className="camera-card">
        <h1>{order ? order.name : "Dasher"}</h1>

        {order ? (
          <>
            <p className="subtitle">Order {order.id}</p>

            <section
  className="ingredients-section"
  aria-labelledby="components-title"
>
  <h2 id="components-title">Components</h2>

  {components.length > 0 ? (
    <ul className="ingredients-list">
      {components.map((component, index) => (
        <li key={`${component.name}-${index}`}>
          {component.name} × {component.count}
        </li>
      ))}
    </ul>
  ) : (
    <p className="ingredients-empty">
      No components listed for this item.
    </p>
  )}
</section>
          </>
        ) : (
          <p className="subtitle">Live camera preview</p>
        )}

        <div className="camera-preview">
          <video
            ref={videoRef}
            autoPlay
            playsInline
            muted
            aria-label="Live laptop camera preview"
          />
        </div>

        <p className="form-message" role="status">
          {error || (ready ? "Camera connected." : "Waiting for camera access…")}
        </p>

        {onDone ? (
          <button
            className="login-button"
            type="button"
            onClick={onDone}
          >
            Done
            <span aria-hidden="true">✓</span>
          </button>
        ) : onLogout ? (
          <button
            className="login-button"
            type="button"
            onClick={onLogout}
          >
            Log out
          </button>
        ) : null}
      </section>
    </main>
  );
}