import { Eye, EyeOff, type LucideIcon } from "lucide-react";
import { useState } from "react";
import { Input } from "@/components/ui/input";

interface ApiKeyCardProps {
  label: string;
  placeholder: string;
  icon: LucideIcon;
  value: string;
  onChange: (v: string) => void;
}

export function ApiKeyCard({
  label,
  placeholder,
  icon: Icon,
  value,
  onChange,
}: ApiKeyCardProps) {
  const [reveal, setReveal] = useState(false);
  return (
    <div className="group rounded-xl border border-border bg-card/60 p-4 backdrop-blur transition-colors hover:border-border-strong">
      <div className="flex items-center gap-3">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-border bg-background/60 text-primary">
          <Icon className="h-4 w-4" />
        </div>
        <div className="min-w-0 flex-1">
          <label className="block text-xs font-medium uppercase tracking-wider text-muted-foreground">
            {label}
          </label>
          <div className="relative mt-1">
            <Input
              type={reveal ? "text" : "password"}
              value={value}
              onChange={(e) => onChange(e.target.value)}
              placeholder={placeholder}
              spellCheck={false}
              autoComplete="off"
              className="h-9 border-0 bg-transparent px-0 font-mono text-sm shadow-none focus-visible:ring-0"
            />
          </div>
        </div>
        <button
          type="button"
          onClick={() => setReveal((v) => !v)}
          aria-label={reveal ? "Hide key" : "Reveal key"}
          className="flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
        >
          {reveal ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
        </button>
      </div>
    </div>
  );
}
