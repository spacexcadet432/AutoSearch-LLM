import { GitBranch, Globe, Cpu } from "lucide-react";
import { PanelHeader } from "./PanelHeader";

export type RoutingMode = "web_retrieval" | "direct_llm";

interface Props {
  mode: RoutingMode;
  confidence: number; // 0..1
  retrievalTriggered: boolean;
  reason: string;
}

export function RoutingDecisionPanel({
  mode,
  confidence,
  retrievalTriggered,
  reason,
}: Props) {
  const isWeb = mode === "web_retrieval";
  const Icon = isWeb ? Globe : Cpu;
  const label = isWeb ? "Web Retrieval" : "Direct LLM";
  const pct = Math.round(confidence * 100);

  return (
    <section className="rounded-2xl border border-border bg-card/60 p-6 shadow-card-elevated backdrop-blur">
      <PanelHeader icon={GitBranch} label="Routing Decision" />

      <div className="flex items-center gap-3">
        <span
          className={
            "flex h-10 w-10 items-center justify-center rounded-lg border " +
            (isWeb
              ? "border-primary/40 bg-primary/10 text-primary"
              : "border-border bg-background/60 text-muted-foreground")
          }
        >
          <Icon className="h-5 w-5" />
        </span>
        <div>
          <div className="text-sm font-semibold">{label}</div>
          <div className="font-mono text-xs text-muted-foreground">{reason}</div>
        </div>
      </div>

      <div className="mt-5 space-y-2">
        <div className="flex items-center justify-between font-mono text-[11px] uppercase tracking-wider text-muted-foreground">
          <span>Routing confidence</span>
          <span className="text-foreground">{pct}%</span>
        </div>
        <div className="h-1.5 overflow-hidden rounded-full bg-background/60">
          <div
            className="h-full gradient-primary transition-all"
            style={{ width: `${pct}%` }}
          />
        </div>
      </div>

      <div className="mt-5 flex items-center justify-between rounded-lg border border-border bg-background/40 px-3 py-2 text-xs">
        <span className="font-mono uppercase tracking-wider text-muted-foreground">
          Retrieval triggered
        </span>
        <span
          className={
            "inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider " +
            (retrievalTriggered
              ? "bg-success/15 text-success"
              : "bg-muted text-muted-foreground")
          }
        >
          <span
            className={
              "h-1.5 w-1.5 rounded-full " +
              (retrievalTriggered ? "bg-success" : "bg-muted-foreground")
            }
          />
          {retrievalTriggered ? "True" : "False"}
        </span>
      </div>
    </section>
  );
}
