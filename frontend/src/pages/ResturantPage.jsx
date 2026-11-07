import { useState } from "react";
import OrdersPage from "./OrdersPage.jsx";

export default function ResturantPage() {
  const [view, setView] = useState("home");

  if (view === "orders") {
    return <OrdersPage onBack={() => setView("home")} />;
  }

  return (
    <main className="page">
      <div className="restaurant-actions">
        <button
          className="glass-button"
          type="button"
          onClick={() => setView("orders")}
        >
          View orders
        </button>

        <button className="glass-button" type="button">
          View items
        </button>

        <button className="glass-button" type="button">
          View packages
        </button>

        <button className="glass-button" type="button">
          View pickups
        </button>
      </div>
    </main>
  );
}