import { money, when } from "../api";
import { useApi } from "../hooks";
import type { LedgerEntry } from "../types";
import { ErrorNote, Loading } from "./ui";

const EVENTS: Record<string, string> = {
  FUNDED: "Funded",
  REQUESTED: "Request received",
  ASSESSED: "Risk checked",
  DECIDED: "Rules decided",
  APPROVED_BY_FUNDER: "Funder approved",
  PAID: "Paid out",
  DELIVERED: "Delivered",
  FAILED: "Payment failed",
  FRAUD_HELD: "Held for fraud check",
  FRAUD_CONFIRMED: "Reported as fraud",
  RULES_CHANGED: "Rules signed",
};

function detail(e: LedgerEntry): string {
  const d = e.data as Record<string, unknown>;
  if (e.event === "DECIDED") return String(d.reason ?? d.outcome ?? "");
  if (e.event === "ASSESSED") return `Risk ${String(d.level ?? "").toLowerCase()} (${d.score ?? 0})`;
  if (e.event === "RULES_CHANGED") return `Version ${d.version}`;
  if (e.event === "FUNDED") return d.rail === "PAYPAL" ? "via PayPal" : String(d.rail ?? "");
  if (e.event === "DELIVERED") return d.collected ? "Cash collected" : `${d.product ?? ""} delivered`;
  if (e.event === "FRAUD_CONFIRMED") return Array.isArray(d.blocked) && d.blocked.length ? `Blocked ${d.blocked.join(", ")}` : "";
  return String(d.product ?? "");
}

/** Append-only audit trail, newest first. */
export default function Ledger({ query }: { query: string }) {
  const { data, error, loading } = useApi<LedgerEntry[]>(`/ledger/?${query}`);
  if (loading && !data) return <Loading what="Loading the ledger" />;
  return (
    <>
      <ErrorNote error={error} />
      <ul className="timeline">
        {data?.map((e) => (
          <li key={e.id}>
            <span className="t muted small">{when(e.created_at)}</span>
            <span>
              <strong>{EVENTS[e.event] ?? e.event}</strong>
              <span className="muted"> · {e.actor_name}</span>
              {detail(e) && <div className="small muted">{detail(e)}</div>}
              {e.request && <div className="small"><a href={`#/requests/${e.request}`}>View request</a></div>}
            </span>
            <span className="small">{e.amount ? money(e.amount) : ""}</span>
          </li>
        ))}
      </ul>
      {data?.length === 0 && <p className="muted">Nothing recorded yet.</p>}
    </>
  );
}
