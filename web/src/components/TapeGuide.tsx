/**
 * How-to-read-the-tape drawer for the dashboard (and any Live-page embed).
 * Copy comes from GET /api/dfy/tape-guide — same payload as Hermes
 * GET /v1/dfy/tape-guide.
 */

import { useEffect, useState } from "react";

interface GlossaryRow {
  term: string;
  example: string;
  plain: string;
}

interface TapeGuidePayload {
  title: string;
  lede: string;
  live_url: string;
  glossary: GlossaryRow[];
  worked_example: { cryptic: string; plain: string };
}

export function TapeGuide() {
  const [open, setOpen] = useState(false);
  const [payload, setPayload] = useState<TapeGuidePayload | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open || payload) return;
    let cancelled = false;
    fetch("/api/dfy/tape-guide")
      .then(async (res) => {
        if (!res.ok) throw new Error(`tape-guide ${res.status}`);
        return res.json();
      })
      .then((data: TapeGuidePayload) => {
        if (!cancelled) setPayload(data);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, [open, payload]);

  return (
    <div className="px-1 pb-2">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="text-[0.65rem] uppercase tracking-wider text-muted-foreground hover:text-foreground"
      >
        {open ? "Hide tape guide" : "How to read the tape"}
      </button>
      {open && (
        <div className="mt-2 max-h-64 space-y-2 overflow-y-auto text-[0.7rem] leading-5 text-muted-foreground">
          {error && <p className="text-destructive/90">{error}</p>}
          {payload && (
            <>
              <p>{payload.lede}</p>
              <p className="whitespace-pre-wrap rounded border border-border/60 bg-muted/20 p-2 text-foreground/90">
                {payload.worked_example.plain}
              </p>
              {payload.glossary.slice(0, 6).map((row) => (
                <p key={row.term}>
                  <span className="text-foreground">{row.term}</span>
                  {" — "}
                  {row.plain}
                </p>
              ))}
              <a
                href={payload.live_url}
                className="text-foreground underline"
                target="_blank"
                rel="noreferrer"
              >
                Open Live
              </a>
            </>
          )}
        </div>
      )}
    </div>
  );
}
