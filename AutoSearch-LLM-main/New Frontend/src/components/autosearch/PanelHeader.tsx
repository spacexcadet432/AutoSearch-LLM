import type { LucideIcon } from "lucide-react";

export function PanelHeader({
  icon: Icon,
  label,
  hint,
}: {
  icon: LucideIcon;
  label: string;
  hint?: string;
}) {
  return (
    <div className="mb-4 flex items-center justify-between">
      <div className="flex items-center gap-2">
        <span className="flex h-7 w-7 items-center justify-center rounded-md border border-border bg-background/60 text-primary">
          <Icon className="h-3.5 w-3.5" />
        </span>
        <h2 className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
          {label}
        </h2>
      </div>
      {hint && (
        <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground/70">
          {hint}
        </span>
      )}
    </div>
  );
}
