import { useState } from "react";
import { api, newKey } from "../api";
import { useAction, useApi } from "../hooks";
import { navigate } from "../router";
import type { Mandate, Payee, RequestDetail } from "../types";
import { ErrorNote } from "./ui";

export const EVIDENCE_KINDS: [string, string][] = [
  ["QUOTE", "Quote"], ["INVOICE", "Invoice"], ["MILESTONE_PHOTO", "Progress photo"], ["RECEIPT", "Receipt"], ["OTHER", "Other"],
];

export async function uploadFile(file: File) {
  const form = new FormData();
  form.append("file", file);
  return api.post<{ id: string; name: string; content_type: string }>("/uploads/", form);
}

function allowedPayeeIds(m: Mandate) {
  return m.rules.filter((r) => r.kind === "allowed_payees").flatMap((r) => (r.params.payee_ids as string[]) ?? []);
}

/** Ask to pay a supplier, school or provider from a mandate, with quotes, invoices or photos attached. */
export default function RequestForm({ mandate }: { mandate: Mandate }) {
  const payees = useApi<Payee[]>("/payees/");
  const ids = allowedPayeeIds(mandate);
  const options = payees.data?.filter((p) => ids.includes(p.id)) ?? [];
  const [payee, setPayee] = useState("");
  const [product, setProduct] = useState("");
  const [amount, setAmount] = useState("");
  const [message, setMessage] = useState("");
  const [files, setFiles] = useState<{ file: File; kind: string }[]>([]);
  const { busy, error, run } = useAction();

  const submit = () => run(async () => {
    const uploads = [];
    for (const f of files) uploads.push({ upload_id: (await uploadFile(f.file)).id, kind: f.kind });
    const r = await api.post<RequestDetail>("/requests/", {
      mandate: mandate.id, payee: payee || options[0]?.id, product, amount, message_text: message, uploads,
      idempotency_key: newKey(),
    });
    navigate(`/requests/${r.id}`);
  });

  return (
    <div className="card">
      <h3>Request a payment</h3>
      <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))" }}>
        <div>
          <label htmlFor="rf-payee">Pay</label>
          <select id="rf-payee" value={payee || options[0]?.id || ""} onChange={(e) => setPayee(e.target.value)}>
            {options.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </div>
        <div>
          <label htmlFor="rf-product">For</label>
          <input id="rf-product" placeholder="materials, school_fees…" value={product} onChange={(e) => setProduct(e.target.value)} />
        </div>
        <div>
          <label htmlFor="rf-amount">Amount (USD)</label>
          <input id="rf-amount" type="number" min="1" step="0.01" value={amount} onChange={(e) => setAmount(e.target.value)} />
        </div>
      </div>
      <div className="field">
        <label htmlFor="rf-msg">Note</label>
        <input id="rf-msg" value={message} onChange={(e) => setMessage(e.target.value)} />
      </div>
      <div className="field">
        <label htmlFor="rf-files">Quotes, invoices or photos</label>
        <input id="rf-files" type="file" accept="image/*,application/pdf" multiple
          onChange={(e) => setFiles([...files, ...Array.from(e.target.files ?? []).map((file) => ({ file, kind: "QUOTE" }))])} />
        {files.length > 0 && (
          <div className="chips" style={{ padding: "0.4rem 0 0", background: "none" }}>
            {files.map((f, i) => (
              <span className="chip" key={i}>
                {f.file.name}
                <select aria-label="What is this file?" value={f.kind}
                  onChange={(e) => setFiles(files.map((x, j) => (j === i ? { ...x, kind: e.target.value } : x)))}>
                  {EVIDENCE_KINDS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
                </select>
                <button className="link-btn" aria-label={`Remove ${f.file.name}`} onClick={() => setFiles(files.filter((_, j) => j !== i))}>×</button>
              </span>
            ))}
          </div>
        )}
      </div>
      <div className="field">
        <button className="primary" disabled={busy || !product || Number(amount) <= 0 || options.length === 0} onClick={submit}>
          {busy ? <><span className="spinner" /> Reading documents and checking rules…</> : "Submit for checking"}
        </button>
      </div>
      <ErrorNote error={error} />
    </div>
  );
}
