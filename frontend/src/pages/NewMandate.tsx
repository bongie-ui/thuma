import { useEffect, useState } from "react";
import { api } from "../api";
import { ErrorNote } from "../components/ui";
import { useAction, useApi, useSession } from "../hooks";
import { navigate } from "../router";
import type { Draft, Family, Mandate, Rule } from "../types";

const EXAMPLE =
  "Up to $600 for cement and bricks for the house in Gwanda. Pay the hardware store directly, only after a photo shows the foundation is done. Cement no more than $11 a bag.";
const NUMBER_PARAMS = new Set(["amount", "max_unit_price", "hours"]);

export default function NewMandate() {
  const { session } = useSession();
  const family = useApi<Family>("/family/");
  const [text, setText] = useState("");
  const [draft, setDraft] = useState<Draft | null>(null);
  const [title, setTitle] = useState("");
  const [rules, setRules] = useState<Rule[]>([]);
  const [errors, setErrors] = useState<string[]>([]);
  const [coFunders, setCoFunders] = useState<number[]>([]);
  const drafting = useAction();
  const saving = useAction();

  const makeDraft = () => drafting.run(async () => {
    const d = await api.post<Draft>("/mandates/draft/", { text });
    setDraft(d);
    setTitle(d.title);
    setRules(d.rules);
    setErrors(d.errors);
  });

  // Re-validate and re-describe whenever the funder edits the rules.
  useEffect(() => {
    if (!draft) return;
    const t = window.setTimeout(async () => {
      try {
        const res = await api.post<{ errors: string[]; rules: Rule[] }>("/mandates/preview-rules/", {
          type: draft.type, rules: rules.map(({ kind, params }) => ({ kind, params })),
        });
        setErrors(res.errors);
        setRules((current) => current.map((r, i) => ({ ...r, text: res.rules[i]?.text ?? r.text })));
      } catch {
        /* the save step reports errors too */
      }
    }, 350);
    return () => window.clearTimeout(t);
    // Only the rule values matter, not their descriptions.
  }, [draft, JSON.stringify(rules.map((r) => [r.kind, r.params]))]); // eslint-disable-line react-hooks/exhaustive-deps

  const setParam = (i: number, name: string, value: string) =>
    setRules((rs) => rs.map((r, j) => (j === i ? { ...r, params: { ...r.params, [name]: Number(value) } } : r)));
  const removeRule = (i: number) => setRules((rs) => rs.filter((_, j) => j !== i));

  const confirm = () => saving.run(async () => {
    const m = await api.post<Mandate>("/mandates/", {
      type: draft!.type, title, purpose_text: draft!.purpose_text,
      rules: rules.map(({ kind, params }) => ({ kind, params })), co_funder_ids: coFunders,
    });
    navigate(`/mandates/${m.id}`);
  });

  const others = family.data?.members.filter((m) => m.user_id !== session.user?.id) ?? [];

  return (
    <>
      <a href="#/" className="small">← Mandates</a>
      <h1 style={{ marginTop: "0.5rem" }}>New mandate</h1>
      <div className="card">
        <label htmlFor="purpose">What is the money for, and how may it be spent?</label>
        <textarea id="purpose" rows={4} value={text} placeholder={EXAMPLE} onChange={(e) => setText(e.target.value)} />
        <div className="row" style={{ marginTop: "0.6rem" }}>
          <button className="primary" disabled={drafting.busy || text.trim().length < 10} onClick={makeDraft}>
            {drafting.busy ? <><span className="spinner" /> Drafting…</> : draft ? "Draft again" : "Draft the rules"}
          </button>
          {!text && <button className="link-btn" onClick={() => setText(EXAMPLE)}>Use the example</button>}
        </div>
        <p className="small muted" style={{ marginTop: "0.6rem", marginBottom: 0 }}>
          The assistant only proposes rules. Nothing is saved until you confirm and sign them.
        </p>
      </div>
      <ErrorNote error={drafting.error} />

      {draft && (
        <div className="card section">
          <span className="mandate-type">{draft.type_label}</span>
          <div className="field">
            <label htmlFor="title">Title</label>
            <input id="title" value={title} onChange={(e) => setTitle(e.target.value)} />
          </div>
          {draft.explanation && <p className="muted small" style={{ marginTop: "0.6rem" }}>{draft.explanation}</p>}

          <h3 style={{ marginTop: "1rem" }}>Rules</h3>
          <ul className="rules">
            {rules.map((r, i) => (
              <li key={i}>
                <span className="tick">✓</span>
                <div style={{ flex: 1 }}>
                  <div>{r.text}</div>
                  <div className="row small" style={{ marginTop: "0.25rem" }}>
                    {Object.entries(r.params).filter(([k]) => NUMBER_PARAMS.has(k)).map(([k, v]) => (
                      <label key={k} className="row" style={{ fontWeight: 500, margin: 0 }}>
                        {k.replace(/_/g, " ")}
                        <input type="number" min="0" step="any" value={String(v)} style={{ width: "7rem" }}
                          onChange={(e) => setParam(i, k, e.target.value)} />
                      </label>
                    ))}
                  </div>
                </div>
                <button className="link-btn small" onClick={() => removeRule(i)} aria-label={`Remove rule: ${r.text}`}>Remove</button>
              </li>
            ))}
          </ul>

          {draft.questions.length > 0 && (
            <div className="notice info" style={{ marginTop: "0.75rem" }}>
              <strong>The assistant needs to know:</strong>
              <ul style={{ margin: "0.3rem 0 0", paddingLeft: "1.2rem" }}>{draft.questions.map((q) => <li key={q}>{q}</li>)}</ul>
            </div>
          )}
          {errors.length > 0 && (
            <div className="notice warn" style={{ marginTop: "0.75rem" }}>
              <strong>Fix before signing:</strong>
              <ul style={{ margin: "0.3rem 0 0", paddingLeft: "1.2rem" }}>{errors.map((e) => <li key={e}>{e}</li>)}</ul>
            </div>
          )}

          {others.length > 0 && (
            <div className="field" style={{ marginTop: "1rem" }}>
              <label>Who funds it with you?</label>
              <div className="checks">
                {others.map((m) => (
                  <label key={m.user_id}>
                    <input type="checkbox" checked={coFunders.includes(m.user_id)}
                      onChange={(e) => setCoFunders((c) => (e.target.checked ? [...c, m.user_id] : c.filter((x) => x !== m.user_id)))} />
                    {m.name}
                  </label>
                ))}
              </div>
            </div>
          )}

          <hr />
          <div className="row">
            <button className="primary" disabled={saving.busy || errors.length > 0 || !title.trim()} onClick={confirm}>
              {saving.busy ? "Signing…" : "Confirm and sign"}
            </button>
            <span className="small muted">Signing locks these rules. Changing them later needs the owner and a new signature.</span>
          </div>
          <ErrorNote error={saving.error} />
        </div>
      )}
    </>
  );
}
