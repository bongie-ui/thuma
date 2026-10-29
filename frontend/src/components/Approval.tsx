import { useState } from "react";
import { api, money } from "../api";
import { useAction } from "../hooks";
import type { PayRequest, RequestDetail } from "../types";
import { ErrorNote, riskTone } from "./ui";

const FLAG_LABEL: Record<string, string> = {
  URGENCY_PRESSURE: "Urgency pressure",
  IMPERSONATION: "Impersonation",
  THIRD_PARTY_PAYMENT: "Pay someone else",
  EMERGENCY_STORY: "Emergency story",
  CREDENTIAL_REQUEST: "Asks for a PIN or code",
  REVERSAL_SCAM: "Reversal scam",
  PRIZE_SCAM: "Prize scam",
  STYLE_MISMATCH: "Doesn't sound like them",
  PURPOSE_MISMATCH: "Not what the money is for",
  OTHER: "Other",
};

/** The red card every funder sees when a request is held for possible fraud. */
export function FraudCard({ r }: { r: PayRequest }) {
  const risk = r.risk!;
  return (
    <div className="card fraud">
      <div className="row between">
        <h3 style={{ margin: 0 }}>Possible fraud: do not pay yet</h3>
        <span className={`badge ${riskTone(risk.level)}`}>Risk {risk.score}/100</span>
      </div>
      <p className="small" style={{ marginTop: "0.4rem" }}>
        {money(r.amount, r.currency)} {r.product} {r.beneficiary_name ? `for ${r.beneficiary_name}` : ""}, asked by{" "}
        <strong>{r.requester}</strong>{r.requester_phone ? ` from ${r.requester_phone}` : ""}.
      </p>
      {r.message_text && <blockquote>{r.message_text}</blockquote>}
      <div className="verify">
        <strong>Before anyone pays:</strong>
        <p style={{ margin: "0.3rem 0 0" }}>{risk.suggested_verification}</p>
      </div>
      <RiskDetails r={r} />
    </div>
  );
}

export function RiskDetails({ r }: { r: PayRequest }) {
  const risk = r.risk!;
  return (
    <>
      {risk.signals.length > 0 && (
        <>
          <strong className="small">Checks that fired</strong>
          <ul className="signals">
            {risk.signals.map((s) => <li key={s.signal}><span className="w">+{s.weight}</span>{s.detail}</li>)}
          </ul>
        </>
      )}
      {risk.ai_flags.length > 0 && (
        <>
          <strong className="small">What the assistant noticed</strong>
          <ul className="signals">
            {risk.ai_flags.map((f, i) => (
              <li key={i}>
                <span className="badge bad">{FLAG_LABEL[f.flag] ?? f.flag}</span> {f.reason}
                {f.quote && <span className="muted"> “{f.quote}”</span>}
              </li>
            ))}
          </ul>
        </>
      )}
      {risk.ai_summary && <p className="small muted">{risk.ai_summary}</p>}
    </>
  );
}

/** Approve / reject an escalation; verify or report a fraud hold. Only actions the backend allows are shown. */
export function ApprovalActions({ r, onDone }:
  { r: PayRequest & { allowed_actions?: string[] }; onDone: (r: RequestDetail) => void }) {
  const [note, setNote] = useState("");
  const { busy, error, run } = useAction();
  const allowed = r.allowed_actions ?? (r.status === "HELD_FRAUD" ? ["VERIFIED_SAFE", "REJECT", "REPORT_FRAUD"]
    : r.status === "ESCALATED" ? ["APPROVE", "REJECT", "REPORT_FRAUD"] : []);
  if (allowed.length === 0) return null;

  const act = (action: string) => run(async () => {
    if (action === "REPORT_FRAUD" && !window.confirm("Report this as fraud? The request is cancelled and the numbers in it are blocked for your family.")) return;
    onDone(await api.post<RequestDetail>(`/requests/${r.id}/approval/`, { action, note }));
  });
  const held = r.status === "HELD_FRAUD";

  return (
    <div className="stack" style={{ marginTop: "0.75rem" }}>
      <div>
        <label htmlFor={`note-${r.id}`}>{held ? "How did you verify it?" : "Note (optional)"}</label>
        <input id={`note-${r.id}`} value={note} onChange={(e) => setNote(e.target.value)}
          placeholder={held ? "e.g. Called her on the registered number; she did not ask for this" : ""} />
      </div>
      <div className="row">
        {allowed.includes("APPROVE") && <button className="primary" disabled={busy} onClick={() => act("APPROVE")}>Approve</button>}
        {allowed.includes("VERIFIED_SAFE") && (
          <button disabled={busy || !note.trim()} onClick={() => act("VERIFIED_SAFE")} title="Needs a note saying how you verified">
            I verified it, pay
          </button>
        )}
        {allowed.includes("REJECT") && <button disabled={busy} onClick={() => act("REJECT")}>Reject</button>}
        {allowed.includes("REPORT_FRAUD") && <button className="danger solid" disabled={busy} onClick={() => act("REPORT_FRAUD")}>Report fraud</button>}
      </div>
      <p className="small muted" style={{ margin: 0 }}>Approving re-checks every hard rule and the balance. A funder can never override a refusal.</p>
      <ErrorNote error={error} />
    </div>
  );
}
