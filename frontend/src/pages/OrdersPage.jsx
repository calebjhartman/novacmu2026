import { useEffect, useState } from "react";
import DasherPage from "./DasherPage.jsx";


export default function OrdersPage({ onBack, onStart }) {
  const [orders, setOrders] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selectedOrder, setSelectedOrder] = useState(null);

  useEffect(() => {
    let active = true;
    const controller = new AbortController();

    async function loadOrders() {
      try {
        const response = await fetch(
          `${import.meta.env.BASE_URL}mock-data.json`,
          { signal: controller.signal }
        );

        if (!response.ok) {
          throw new Error("Unable to load orders.json.");
        }

        const data = await response.json();

        if (
          !Array.isArray(data) ||
          !data.every(
            (order) =>
              order !== null &&
              typeof order === "object" &&
              (typeof order.id === "string" ||
                typeof order.id === "number") &&
              typeof order.name === "string"
          )
        ) {
          throw new Error("orders.json has an invalid format.");
        }

        if (active) {
          setOrders(data);
        }
      } catch (err) {
        if (active && err.name !== "AbortError") {
          setError(err.message || "Unable to load orders.");
        }
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    }

    loadOrders();

    return () => {
      active = false;
      controller.abort();
    };
  }, []);


  if (selectedOrder) {
        return (
        <DasherPage
        order={selectedOrder}
        onDone={() => setSelectedOrder(null)}
        />
        );
    }

  return (
    <main className="page">
      <section className="orders-panel" aria-labelledby="orders-title">
        <header className="orders-header">
          <h1 id="orders-title">Orders</h1>

          {onBack && (
            <button
              className="orders-back"
              type="button"
              onClick={onBack}
            >
              ← Back
            </button>
          )}
        </header>

        <div role="status">
          {loading && (
            <p className="orders-message">Loading orders…</p>
          )}

          {error && (
            <p className="orders-message">{error}</p>
          )}

          {!loading && !error && orders.length === 0 && (
            <p className="orders-message">No orders yet.</p>
          )}
        </div>

        {!loading && !error && (
          <ul className="orders-list">
            {orders.map((order) => (
              <li className="order-row" key={order.id}>
                <div className="order-details">
                  <span className="order-id">{order.id}</span>
                  <h2 className="order-name">{order.name}</h2>
                </div>

                <button
                    className="order-start"
                    type="button"
                    onClick={() => setSelectedOrder(order)}
                    aria-label={`Start ${order.name}, order ${order.id}`}
                    >
                    Start
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </main>
  );
}