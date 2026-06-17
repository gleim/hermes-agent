/**
 * DfyEventItem — compact row for a single DFY ingest event in the sidebar.
 *
 * Renders:
 *   - A color-coded kind badge (trade=green, indicator=blue, mechanism=yellow, error=red)
 *   - Bot name
 *   - Relative timestamp ("2s ago")
 *   - Truncated data summary
 *   - Hover tooltip with full event JSON
 */

import { useState, useEffect } from "react";

export interface DfyEvent {
  /** Opaque client-side id for React key prop. */
  id: string;
  kind: string;
  bot: string;
  ts: string;
  data: Record<string, unknown>;
  /** Epoch ms when this event was received by the browser. */
  receivedAt: number;
}

// ---------------------------------------------------------------------------
// Kind → color mapping
// ---------------------------------------------------------------------------

type KindCategory = "trade" | "indicator" | "mechanism" | "error" | "other";

const TRADE_KINDS = new Set([
  "trade_event",
  "entry",
  "entry_fill",
  "exit",
  "exit_fill",
  "entry_cancel",
  "exit_cancel",
]);

const MECHANISM_KINDS = new Set([
  "whitelist",
  "runner",
  "status",
  "open_trades",
]);

function kindCategory(kind: string): KindCategory {
  if (TRADE_KINDS.has(kind)) return "trade";
  if (kind === "indicator_digest") return "indicator";
  if (MECHANISM_KINDS.has(kind)) return "mechanism";
  if (kind === "error") return "error";
  return "other";
}

const BADGE_CLASSES: Record<KindCategory, string> = {
  trade:
    "bg-emerald-500/15 text-emerald-400 border border-emerald-500/30",
  indicator:
    "bg-blue-500/15 text-blue-400 border border-blue-500/30",
  mechanism:
    "bg-yellow-500/15 text-yellow-400 border border-yellow-500/30",
  error:
    "bg-destructive/15 text-destructive border border-destructive/30",
  other:
    "bg-muted/40 text-muted-foreground border border-border",
};

const ROW_BORDER: Record<KindCategory, string> = {
  trade: "border-emerald-500/20",
  indicator: "border-blue-500/20",
  mechanism: "border-yellow-500/20",
  error: "border-destructive/30",
  other: "border-border",
};

// ---------------------------------------------------------------------------
// Relative time
// ---------------------------------------------------------------------------

function relativeTime(receivedAt: number, now: number): string {
  const sec = Math.max(0, Math.floor((now - receivedAt) / 1000));
  if (sec < 60) return `${sec}s ago`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ago`;
  return `${Math.floor(min / 60)}h ago`;
}

// ---------------------------------------------------------------------------
// Data summary
// ---------------------------------------------------------------------------

function dataSummary(kind: string, data: Record<string, unknown>): string {
  if (!data || typeof data !== "object") return "";

  // Trade events: show pair + direction
  if (TRADE_KINDS.has(kind)) {
    const parts: string[] = [];
    if (data.pair) parts.push(String(data.pair));
    if (data.direction) parts.push(String(data.direction));
    if (data.profit_ratio != null)
      parts.push(`P/L ${(Number(data.profit_ratio) * 100).toFixed(2)}%`);
    if (data.enter_tag) parts.push(String(data.enter_tag));
    return parts.join(" · ") || JSON.stringify(data).slice(0, 60);
  }

  // Indicator digest: show pair + column count
  if (kind === "indicator_digest") {
    const parts: string[] = [];
    if (data.pair) parts.push(String(data.pair));
    if (data.timeframe) parts.push(String(data.timeframe));
    if (data.column_count != null) parts.push(`${data.column_count} cols`);
    return parts.join(" · ") || JSON.stringify(data).slice(0, 60);
  }

  // Open trades: show count
  if (kind === "open_trades") {
    const rows = data.rows;
    if (Array.isArray(rows)) return `${rows.length} open trades`;
  }

  // Whitelist: show count
  if (kind === "whitelist") {
    if (Array.isArray(data)) return `${(data as unknown[]).length} pairs`;
  }

  // Runner / status: show key fields
  if (kind === "runner" || kind === "status") {
    const keys = Object.keys(data).slice(0, 3);
    return keys.map((k) => `${k}=${JSON.stringify(data[k])}`).join(" ");
  }

  // Fallback: truncated JSON
  const raw = JSON.stringify(data);
  return raw.length > 80 ? raw.slice(0, 77) + "…" : raw;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

const TICK_MS = 10_000; // update relative timestamps every 10s

export function DfyEventItem({ event }: { event: DfyEvent }) {
  const [now, setNow] = useState(() => Date.now());
  const [tooltipVisible, setTooltipVisible] = useState(false);

  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), TICK_MS);
    return () => window.clearInterval(id);
  }, []);

  const cat = kindCategory(event.kind);
  const badgeCls = BADGE_CLASSES[cat];
  const borderCls = ROW_BORDER[cat];
  const summary = dataSummary(event.kind, event.data);
  const relTs = relativeTime(event.receivedAt, now);
  const fullJson = JSON.stringify({ kind: event.kind, bot: event.bot, ts: event.ts, data: event.data }, null, 2);

  return (
    <div
      className={`relative rounded border ${borderCls} bg-muted/10 px-2 py-1.5 text-xs`}
      onMouseEnter={() => setTooltipVisible(true)}
      onMouseLeave={() => setTooltipVisible(false)}
    >
      <div className="flex items-center gap-1.5 min-w-0">
        {/* Kind badge */}
        <span
          className={`shrink-0 rounded px-1 py-0.5 font-mono text-[0.6rem] uppercase tracking-wide ${badgeCls}`}
        >
          {event.kind.replace(/_/g, " ")}
        </span>

        {/* Bot name */}
        <span className="shrink-0 font-mono text-muted-foreground/70 text-[0.65rem]">
          {event.bot}
        </span>

        {/* Spacer */}
        <span className="flex-1 min-w-0" />

        {/* Relative timestamp */}
        <span className="shrink-0 font-mono text-[0.6rem] text-muted-foreground/50 tabular-nums">
          {relTs}
        </span>
      </div>

      {/* Data summary */}
      {summary && (
        <div className="mt-0.5 font-mono text-[0.65rem] text-muted-foreground/80 truncate">
          {summary}
        </div>
      )}

      {/* Hover tooltip with full JSON */}
      {tooltipVisible && (
        <div
          className={
            "absolute left-0 z-50 mt-1 w-72 rounded border border-border " +
            "bg-background shadow-lg p-2 font-mono text-[0.6rem] text-foreground/90 " +
            "whitespace-pre overflow-auto max-h-48 top-full"
          }
          style={{ wordBreak: "break-all" }}
        >
          {fullJson}
        </div>
      )}
    </div>
  );
}
