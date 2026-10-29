import { useState } from "react";
import { api, money, newKey } from "../api";
import { useAction, useApi } from "../hooks";
import type { Beneficiary, Coverage, Mandate, RequestDetail } from "../types";
import { ErrorNote, StatusBadge } from "./ui";

const ACTION: Record<string, [string, string]> = {
  airtime: ["Buy airtime", "5"],
  bundles: ["Buy bundles", "10"],
  cash: ["Send cash", "20"],
};

/** Shared-support shortcuts: what each product has used this period, who covered it, and a one-tap request. */
export default function QuickActions({ mandate, beneficiary, onChange }:
  { mandate: Mandate; beneficiary: Beneficiary; onChange: () => void }) {
  const coverage = useApi<Coverage[]>(`/mandates/${mandate.id}/coverage/?beneficiary=${beneficiary.id}`);
  const refresh = () => {
    void coverage.reload();
    onChange();
  };
  return (
    <div className="section">
      <h2>For {beneficiary.name}</h2>
      <p className="small muted">Every funder sees the same caps, so nobody tops up twice.</p>
      <ErrorNote error={coverage.error} />
      <div className="quick">
        {coverage.data?.map((c) => (
          <ProductCard key={c.product} c={c} mandate={mandate} beneficiary={beneficiary} onDone={refresh} />
        ))}
      </div>
    </div>
  );
}

function ProductCard({ c, mandate, beneficiary, onDone }:
  { c: Coverage; mandate: Mandate; beneficiary: Beneficiary; onDone: () => void }) {
  const [label, preset] = ACTION[c.product] ?? [`Send ${c.product}`, "10"];
  const [amount, setAmount] = useState(preset);
  const [result, setResult] = useState<RequestDetail | null>(null);
  const { busy, error, run } = useAction();
  const left = c.cap !== null ? Number(c.cap) - Number(c.used) : null;

  const send = () => run(async () => {
    const r = await api.post<RequestDetail>("/requests/", {
      mandate: mandate.id, beneficiary: beneficiary.id, product: c.product, amount, idempotency_key: newKey(),
    });
    setResult(r);
    onDone();
  });

  return (
    <div className="card">
      <div className="row between">
        <strong style={{ textTransform: "capitalize" }}>{c.product}</strong>
        {c.cap !== null && <span className="small muted">{money(c.used)} of {money(c.cap)} this {c.period}</span>}
      </div>
      {c.cap !== null && (
        <div className="bar"><span style={{ width: `${Math.min(100, (Number(c.used) / Number(c.cap)) * 100)}%`, background: "var(--brand)" }} /></div>
      )}
      <div className="small">{c.summary}</div>
      {c.min_interval_hours && <div className="small muted">At most once every {c.min_interval_hours} hours</div>}
      <div className="row">
        <input aria-label={`${c.product} amount`} type="number" min="1" step="1" value={amount}
          style={{ width: "5.5rem" }} onChange={(e) => setAmount(e.target.value)} />
        <button className="primary" disabled={busy || Number(amount) <= 0 || (left !== null && left <= 0)} onClick={send}>
          {busy ? "Checking…" : label}
        </button>
      </div>
      {result && (
        <div className="small">
          <StatusBadge status={result.status} />{" "}
          {result.status !== "APPROVED" && result.status !== "PAID" && result.decision?.reason}{" "}
          <a href={`#/requests/${result.id}`}>Details</a>
        </div>
      )}
      <ErrorNote error={error} />
    </div>
  );
}
