"use client";

import { getSessionId, investigate, type AssistantEvent } from "@/lib/api";
import { useRef, useState } from "react";

function monthLabel(period: string): string {
  const [year, month] = period.split("-");
  const name = new Date(Date.UTC(Number(year), Number(month) - 1, 1)).toLocaleString("en-US", {
    month: "long",
    timeZone: "UTC",
  });
  return `${name} ${year}`;
}

function suggestionsFor(context: Record<string, unknown>): string[] {
  const period = typeof context.period === "string" ? context.period : "2026-05";
  const month = monthLabel(period);
  return [
    `What are the two most expensive services by on-demand cost in ${month}?`,
    `Which region has the highest on-demand cost in ${month}?`,
    `Which instance type costs the most on demand in ${month}?`,
  ];
}

type Turn = {
  role: "user" | "assistant";
  text: string;
  sql: string[];
  status: string;
};

export function AssistantDrawer({ context }: { context: Record<string, unknown> }) {
  const [open, setOpen] = useState(false);
  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);
  const [sessionId, setSessionId] = useState("");
  const abortRef = useRef<AbortController | null>(null);

  function ensureSession() {
    const id = getSessionId();
    setSessionId(id);
    return id;
  }

  async function send(raw?: string) {
    const prompt = (raw ?? question).trim();
    if (!prompt || busy) return;
    ensureSession();
    setBusy(true);
    setQuestion("");
    setTurns((current) => [
      ...current,
      { role: "user", text: prompt, sql: [], status: "" },
      { role: "assistant", text: "", sql: [], status: "Starting investigation…" },
    ]);
    abortRef.current = new AbortController();
    const patch = (update: (turn: Turn) => Turn) => {
      setTurns((current) => {
        const next = [...current];
        const last = next[next.length - 1];
        if (!last || last.role !== "assistant") return current;
        next[next.length - 1] = update(last);
        return next;
      });
    };
    try {
      await investigate(prompt, context, (event, data: AssistantEvent) => {
        if (event === "status") patch((turn) => ({ ...turn, status: data.message ?? "Working…" }));
        if (event === "sql" && data.sql) {
          patch((turn) => ({ ...turn, sql: [...turn.sql, data.sql!] }));
        }
        if (event === "text" && data.delta) {
          patch((turn) => ({ ...turn, text: turn.text + data.delta }));
        }
        if (event === "meta") {
          if (data.error) {
            patch((turn) => ({ ...turn, status: data.error ?? "The investigation could not run." }));
            return;
          }
          patch((turn) => ({ ...turn, status: "Complete" }));
        }
      }, abortRef.current.signal);
    } catch (error) {
      if ((error as Error).name !== "AbortError") {
        patch((turn) => ({ ...turn, status: "The assistant could not reach the analytics backend." }));
      }
    } finally {
      setBusy(false);
    }
  }

  return <>
    <button onClick={() => { ensureSession(); setOpen(true); }} className="fixed bottom-6 right-6 z-40 rounded-full bg-accent text-black px-5 py-3 text-sm font-medium shadow-2xl shadow-black/50">Ask about this view</button>
    {open && <div className="fixed inset-0 z-50 bg-black/55" onClick={() => setOpen(false)} />}
    <aside className={`fixed right-0 top-0 z-50 h-dvh w-full max-w-md border-l border-line bg-[#0b0e10] shadow-2xl transition-transform duration-200 ${open ? "translate-x-0" : "translate-x-full"}`}>
      <div className="h-full flex flex-col">
        <header className="px-6 py-5 border-b border-line flex items-start justify-between gap-4">
          <div className="min-w-0">
            <p className="text-xs tracking-[0.18em] text-muted uppercase">Investigation assistant</p>
            <h2 className="mt-1 text-lg font-medium">Ask about this view</h2>
            {sessionId && (
              <p title={sessionId} className="mt-2 truncate text-[11px] font-mono text-muted">
                {sessionId}
              </p>
            )}
          </div>
          <button onClick={() => { abortRef.current?.abort(); setOpen(false); }} className="text-sm text-muted hover:text-foreground shrink-0">Close</button>
        </header>
        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-8">
          {turns.length === 0 && (
            <div className="space-y-3">
              <p className="text-xs tracking-[0.18em] text-muted uppercase">Suggestions</p>
              <div className="flex flex-col items-start gap-2">
                {suggestionsFor(context).map((suggestion) => (
                  <button
                    key={suggestion}
                    type="button"
                    disabled={busy}
                    onClick={() => send(suggestion)}
                    className="text-sm border border-line rounded-full px-4 py-1.5 text-left leading-5 hover:border-accent hover:text-accent transition-colors disabled:opacity-40"
                  >
                    {suggestion}
                  </button>
                ))}
              </div>
            </div>
          )}
          {turns.map((turn, index) => turn.role === "user" ? (
            <p key={`user:${index}`} className="text-sm text-muted leading-6">{turn.text}</p>
          ) : (
            <div key={`assistant:${index}`} className="space-y-3">
              {(turn.text || (busy && index === turns.length - 1)) && (
                <p className="text-sm leading-7 whitespace-pre-wrap">{turn.text || <span className="animate-pulse text-muted">…</span>}</p>
              )}
              {turn.status && turn.status !== "Complete" && <p className="text-sm text-muted">{turn.status}</p>}
              {turn.sql.length > 0 && (
                <details className="border border-line rounded-xl p-4">
                  <summary className="cursor-pointer text-sm">Show SQL used</summary>
                  <div className="mt-4 space-y-4">
                    {turn.sql.map((statement, sqlIndex) => (
                      <pre key={`sql:${index}:${sqlIndex}`} className="overflow-x-auto whitespace-pre-wrap text-xs text-muted font-mono">{statement}</pre>
                    ))}
                  </div>
                </details>
              )}
            </div>
          ))}
        </div>
        <form className="border-t border-line p-5" onSubmit={(event) => { event.preventDefault(); send(); }}>
          <textarea value={question} onChange={(event) => setQuestion(event.target.value)} rows={3} placeholder="Why did this change?" className="w-full resize-none rounded-xl border border-line bg-background px-3 py-2 text-sm outline-none focus:border-accent" />
          <button disabled={busy || !question.trim()} className="mt-3 w-full rounded-xl bg-accent py-2 text-sm font-medium text-black disabled:opacity-40">{busy ? "Investigating…" : "Investigate"}</button>
        </form>
      </div>
    </aside>
  </>;
}
