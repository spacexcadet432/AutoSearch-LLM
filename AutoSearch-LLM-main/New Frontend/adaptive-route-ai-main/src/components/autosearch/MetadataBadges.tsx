import { Clock, GitBranch, Layers, Activity } from "lucide-react";
import type { LucideIcon } from "lucide-react";

interface Props {
  latencyMs: number;
  routingMode: string;
  sourceCount: number;
  confidence: number;
}

export function MetadataBadges({
  latencyMs,
  routingMode,
  sourceCount,
  confidence,
}: Props) {
  const items: { icon: LucideIcon; label: string; value: string }[] = [
    { icon: Clock, label: "Latency", value: `${latencyMs} ms` },
    { icon: GitBranch, label: "Routing", value: routingMode },
    { icon: Layers, label: "Sources", value: String(sourceCount) },
    { icon: Activity, label: "Confidence", value: `${Math.round(confidence * 100)}%` },
  ];
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      {items.map(({ icon: Icon, label, value }) => (
        <div
          key={label}
          className="flex items-center gap-3 rounded-xl border border-border bg-card/60 p-3 backdrop-blur"
        >
          <span className="flex h-8 w-8 items-center justify-center rounded-md border border-border bg-background/60 text-primary">
            <Icon className="h-4 w-4" />
          </span>
          <div className="min-w-0">
            <div className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
              {label}
            </div>
            <div className="truncate text-sm font-semibold text-foreground">
              {value}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
