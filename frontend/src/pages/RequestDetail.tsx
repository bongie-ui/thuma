import { api, money, uploadUrl, when } from "../api";
import { ApprovalActions, FraudCard, RiskDetails } from "../components/Approval";
import Ledger from "../components/Ledger";
import { ErrorNote, Loading, PaymentLine, riskTone, SimTag, StatusBadge } from "../components/ui";
import { useAction, useApi, usePoll, useSession } from "../hooks";
import type { RequestDetail as Detail } from "../types";

const KIND: Record<string, string> = {
  QUOTE: "Quote", INVOICE: "Invoice", MILESTONE_PHOTO: "Progress photo", RECEIPT: "Receipt", OTHER: "File",
};

export default function RequestDetail({ id }: { id: string }) {
  const { session } = useSession();
  const { data: r, error, reload, setData } = useApi<Detail>(`/requests/${id}/`);
  const collect = useAction();
  const moving = !!r && (r.status === "APPROVED" || r.payment?.status === "PENDING" || r.payment?.last_mile_status === "DELIVERING");
  usePoll(reload, 2500, moving);

  if (error) return <ErrorNote error={error} />;
  if (!r) return <Loading />;
  const decision = r.decisions[r.decisions.length - 1];
  const tx = r.payment;

  return (
    <>
      <a href={`#/mandates/${r.mandate}`} className="small">← {r.mandate_title}</a>
      <div className="section-title" style={{ marginTop: "0.5rem" }}>
        <div>
          <h1>{money(r.amount, r.currency)} {r.product.replace(/_/g, " ")}{r.beneficiary_name ? ` for ${r.beneficiary_name}` : ""}</h1>
          <div className="muted small">
            Asked by {r.requester}{r.requester_phone ? ` (${r.requester_phone})` : ""} via {r.channel.toLowerCase()} · {when(r.created_at)}
            {r.payee_name ? ` · pays ${r.payee_name}` : ""}
          </div>
        </div>
        <StatusBadge status={r.status} />
      </div>

      {r.status === "HELD_FRAUD" && r.risk && (
        <>
          <FraudCard r={r} />
          <div className="card"><ApprovalActions r={r} onDone={setData} /></div>
        </>
      )}
      {r.status === "ESCALATED" && (
        <div className="card" style={{ borderColor: "var(--warn)" }}>
          <h3>A funder needs to decide</h3>
          <p>{decision?.reason}</p>
          <ApprovalActions r={r} onDone={setData} />
        </div>
      )}
      {r.status === "CONFIRMED_FRAUD" && <div className="notice error">Reported as fraud. Nothing was paid and the numbers involved are blocked for this family.</div>}

      {(r.message_text || r.summary_en) && (
        <div className="card section">
          {r.message_text && <blockquote style={{ margin: 0 }}>“{r.message_text}”</blockquote>}
          {r.summary_en && r.summary_en !== r.message_text && <p className="small muted" style={{ margin: "0.4rem 0 0" }}>In English: {r.summary_en}</p>}
        </div>
      )}

      {tx && (
        <div className="card section">
          <h3>Payment</h3>
          <PaymentLine payment={tx} payeeSimulated={r.payee_simulated} />
          <p className="small muted" style={{ margin: "0.5rem 0 0" }}>
            Reference <span className="mono">{tx.reference}</span>{tx.external_id ? <> · PayPal <span className="mono">{tx.external_id}</span></> : null}
          </p>
          {tx.last_mile_status === "AWAITING_COLLECTION" && session.demo_mode && (
            <div className="row" style={{ marginTop: "0.6rem" }}>
              <button disabled={collect.busy} onClick={() => collect.run(async () => {
                await api.post(`/demo/last-mile/${tx.id}/collect/`, { code: tx.collection_code });
                await reload();
              })}>Mark cash collected</button>
              <SimTag label="Demo: simulated agent" />
            </div>
          )}
          <ErrorNote error={collect.error} />
        </div>
      )}

      {decision && (
        <div className="card section">
          <div className="row between">
            <h3 style={{ margin: 0 }}>Why</h3>
            <span className="small muted">{decision.decided_by === "POLICY" ? "Decided by the rules engine" : "Decided after a funder's answer"}</span>
          </div>
          <p style={{ marginTop: "0.4rem" }}>{decision.reason}</p>
          <ul className="rules rule-results">
            {decision.rule_results.map((x, i) => (
              <li key={i} className={x.passed ? "" : "fail"}><span className="tick">{x.passed ? "✓" : "✗"}</span>{x.detail}</li>
            ))}
          </ul>
        </div>
      )}

      {r.risk && r.status !== "HELD_FRAUD" && (
        <div className="card section">
          <div className="row between">
            <h3 style={{ margin: 0 }}>Fraud and risk check</h3>
            <span className={`badge ${riskTone(r.risk.level)}`}>{r.risk.level.toLowerCase()} · {r.risk.score}</span>
          </div>
          {r.risk.signals.length === 0 && r.risk.ai_flags.length === 0 && <p className="small muted">Nothing unusual.</p>}
          <RiskDetails r={r} />
        </div>
      )}

      {r.evidence.length > 0 && (
        <div className="card section">
          <h3>What the assistant read</h3>
          <div className="stack">
            {r.evidence.map((e) => (
              <div key={e.id} className="row" style={{ alignItems: "flex-start" }}>
                {e.upload_id && e.content_type?.startsWith("image/") && (
                  <a href={uploadUrl(e.upload_id)} target="_blank" rel="noreferrer">
                    <img src={uploadUrl(e.upload_id)} alt={e.upload_name ?? KIND[e.kind]} style={{ width: 96, height: 96, objectFit: "cover", borderRadius: 8 }} />
                  </a>
                )}
                <div style={{ flex: 1 }}>
                  <strong>{KIND[e.kind] ?? e.kind}</strong> <span className="small muted">{e.upload_name}</span>
                  <Extracted data={e.extracted} />
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {r.approvals.length > 0 && (
        <div className="card section">
          <h3>Funder answers</h3>
          <ul className="timeline">
            {r.approvals.map((a) => (
              <li key={a.id}><span className="t small muted">{when(a.created_at)}</span><span><strong>{a.user_name}</strong>: {a.action.replace(/_/g, " ").toLowerCase()}{a.note ? `: “${a.note}”` : ""}</span><span /></li>
            ))}
          </ul>
        </div>
      )}

      <div className="card section">
        <h3>Ledger</h3>
        <Ledger key={`${r.status}-${tx?.status}-${tx?.last_mile_status}`} query={`request=${r.id}`} />
      </div>
    </>
  );
}

function Extracted({ data }: { data: Record<string, unknown> }) {
  if (!data || Object.keys(data).length === 0) {
    return <p className="small notice warn" style={{ margin: "0.3rem 0 0" }}>Could not be read, so rules that need it fail.</p>;
  }
  if ("verdict" in data) {
    const tone = data.verdict === "matches" ? "ok" : data.verdict === "unclear" ? "warn" : "bad";
    return (
      <div className="small">
        <span className={`badge ${tone}`}>{String(data.verdict).replace(/_/g, " ")}</span>{" "}
        Saw: {String(data.observed ?? "")}{data.expected ? ` · Expected: ${String(data.expected)}` : ""}
      </div>
    );
  }
  const items = (data.items as { name: string; quantity?: number; unit_price?: number }[]) ?? [];
  return (
    <div className="small">
      {data.supplier ? <div>From {String(data.supplier)}</div> : null}
      {items.map((it, i) => (
        <div key={i}>{it.quantity ? `${it.quantity} × ` : ""}{it.name}{it.unit_price != null ? ` at ${money(it.unit_price)}` : ""}</div>
      ))}
      {data.total != null && <div><strong>Total {money(data.total as number)}</strong></div>}
    </div>
  );
}
