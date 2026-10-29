import { useState } from "react";
import { api } from "../api";
import { useAction } from "../hooks";
import type { Mandate } from "../types";
import { ErrorNote } from "./ui";

/**
 * Funding through PayPal checkout. The backend's create-order/capture endpoints are built with the PayPal
 * Server SDK; until they are switched on, the server answers with a readable message shown here.
 */
export default function FundButton({ mandate, onFunded }: { mandate: Mandate; onFunded: () => void }) {
  const [amount, setAmount] = useState("50");
  const { busy, error, run } = useAction();

  const fund = () => run(async () => {
    const order = await api.post<{ id: string }>(`/mandates/${mandate.id}/fund/create-order/`, { amount });
    await api.post(`/mandates/${mandate.id}/fund/capture/`, { order_id: order.id });
    onFunded();
  });

  return (
    <div>
      <div className="row">
        <input aria-label="Amount in US dollars" type="number" min="1" step="1" value={amount} style={{ width: "6.5rem" }}
          onChange={(e) => setAmount(e.target.value)} />
        <button className="primary" disabled={busy || Number(amount) <= 0 || mandate.status !== "ACTIVE"} onClick={fund}>
          {busy ? "Opening PayPal…" : "Fund with PayPal"}
        </button>
      </div>
      <ErrorNote error={error} />
    </div>
  );
}
