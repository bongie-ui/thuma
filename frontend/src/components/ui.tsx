import type { ReactNode } from "react";
import { money, when } from "../api";
import type { PayRequest, Payment, RequestStatus } from "../types";

const STATUS: Record<RequestStatus, [string, string]> = {
  NEW: ["New", ""],
  ASSESSED: ["Checking", "info"],
  APPROVED: ["Approved, paying", "info"],
  PAID: ["Paid", "ok"],
  REFUSED: ["Refused", "bad"],
  ESCALATED: ["Needs a funder", "warn"],
  HELD_FRAUD: ["Held: possible fraud", "bad"],
  CONFIRMED_FRAUD: ["Fraud confirmed", "bad"],
  FAILED: ["Payment failed", "bad"],
  CANCELLED: ["Cancelled", ""],
};

export function statusTone(status: RequestStatus) {
  return STATUS[status]?.[1] ?? "";
}

export function StatusBadge({ status }: { status: RequestStatus }) {
  const [label, tone] = STATUS[status] ?? [status, ""];
  return <span className={`badge ${tone}`}>{label}</span>;
}

export function SimTag({ label = "Simulated rail" }: { label?: string }) {
  return <span className="sim" title="This step is simulated; no real money moves on it">{label}</span>;
}

export function Loading({ what = "Loading" }: { what?: string }) {
  return <p className="muted row"><span className="spinner" /> {what}…</p>;
}

export function ErrorNote({ error }: { error: string | null | undefined }) {
  return error ? <div className="notice error" role="alert">{error}</div> : null;
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="card empty">{children}</div>;
}

export function riskTone(level: string) {
  return level === "HIGH" ? "bad" : level === "MEDIUM" ? "warn" : "ok";
}

export function lastMileLabel(p: Payment): string | null {
  switch (p.last_mile_status) {
    case "DELIVERING": return "Delivering to the phone";
    case "DELIVERED": return "Delivered";
    case "AWAITING_COLLECTION": return `Awaiting collection (code ${p.collection_code})`;
    case "COLLECTED": return "Cash collected";
    default: return null;
  }
}

export function PaymentLine({ payment, payeeSimulated }: { payment: Payment; payeeSimulated?: boolean }) {
  const lastMile = lastMileLabel(payment);
  const payout = payment.simulated
    ? "Simulated payout"
    : payment.status === "SUCCESS" ? "PayPal Payout sent" : payment.status === "PENDING" ? "PayPal Payout pending"
    : `PayPal Payout ${payment.status.toLowerCase()}`;
  return (
    <span className="row small">
      <span className={`badge ${payment.status === "SUCCESS" ? "ok" : payment.status === "PENDING" ? "info" : "bad"}`}>
        {payout}
      </span>
      {payment.simulated && <SimTag />}
      {lastMile && <span className="badge brand">{lastMile}</span>}
      {lastMile && payeeSimulated && !payment.simulated && <SimTag label="Simulated last mile" />}
    </span>
  );
}

export function RequestRow({ r, showMandate = true }: { r: PayRequest; showMandate?: boolean }) {
  return (
    <a className="card card-link req" href={`#/requests/${r.id}`}>
      <div className="main">
        <div className="row between">
          <strong>{r.product ? r.product.replace(/_/g, " ") : "Request"}{r.beneficiary_name ? ` for ${r.beneficiary_name}` : ""}</strong>
          <span className="amt">{money(r.amount, r.currency)}</span>
        </div>
        <div className="small muted">
          {r.requester}{r.requester_phone && r.requester !== r.requester_phone ? ` (${r.requester_phone})` : ""}
          {" · "}{when(r.created_at)}{showMandate ? ` · ${r.mandate_title}` : ""}
          {r.payee_name ? ` · to ${r.payee_name}` : ""}
        </div>
        <div className="row" style={{ marginTop: "0.35rem" }}>
          <StatusBadge status={r.status} />
          {r.risk && r.risk.level !== "LOW" && (
            <span className={`badge ${riskTone(r.risk.level)}`}>Risk {r.risk.level.toLowerCase()} · {r.risk.score}</span>
          )}
          {r.payment && <PaymentLine payment={r.payment} payeeSimulated={r.payee_simulated} />}
        </div>
        {r.decision && r.status !== "PAID" && r.status !== "APPROVED" && (
          <p className="small muted" style={{ margin: "0.35rem 0 0" }}>{r.decision.reason}</p>
        )}
      </div>
    </a>
  );
}

export const FUNDER_COLORS = ["#0f5c4c", "#c9952a", "#5b7fbf", "#b35c7a", "#6f8f3d"];
