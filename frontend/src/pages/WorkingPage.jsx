import { useEffect, useRef, useState } from "react";

export default function WorkingPage ({ onLogout }) {
  const videoRef = useRef(null);
  const [error, setError] = useState("");
  const [ready, setReady] = useState(false);

  useEffect(() => { 
    let stream;
    let cancelled = false;

    async function startCamera() {
      try {
        if (!navigator.mediaDevices?.getUserMedia) {
          throw new Error("Camera access requires HTTPS or localhost.");
        }

        stream = await navigator.mediaDevices.getUserMedia({
          video: true,
          audio: false,
        });

        // Permission may resolve after the user has left the page.
        if (cancelled) {
          stream.getTracks().forEach((track) => track.stop());
          return;
        }

        videoRef.current.srcObject = stream;
        await videoRef.current.play();

        if (!cancelled) {
          setReady(true);
        }
      } catch (err) {
        stream?.getTracks().forEach((track) => track.stop());

        if (cancelled) return;

        if (err.name === "NotAllowedError") {
          setError("Camera permission was denied. Allow access and refresh.");
        } else if (err.name === "NotFoundError") {
          setError("No camera was found on this device.");
        } else if (err.name === "NotReadableError") {
          setError("The camera could not start. It may be in use by another app.");
        } else {
          setError(err.message || "Unable to access the camera.");
        }
      }
    }

    startCamera();

    return () => {
      cancelled = true;
      stream?.getTracks().forEach((track) => track.stop());
    };
  }, []);

  return (
    <main className="page">
      <section className="camera-card">
        <h1>Dasher</h1>
        <p className="subtitle">Live camera preview</p>

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

        <button
          className="login-button"
          type="button"
          onClick={onLogout}
        >
          Log out
        </button>
      </section>
    </main>
  );
}