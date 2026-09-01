import { Textarea } from "@/components/ui/textarea";

interface QueryInputProps {
  value: string;
  onChange: (v: string) => void;
  onSubmit?: () => void;
}

export function QueryInput({ value, onChange, onSubmit }: QueryInputProps) {
  return (
    <div className="rounded-xl border border-border bg-background/40 backdrop-blur transition-colors focus-within:border-primary/60 focus-within:shadow-glow">
      <Textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
            e.preventDefault();
            onSubmit?.();
          }
        }}
        placeholder="Ask anything... (e.g., What happened in AI this week?)"
        className="min-h-[140px] resize-none border-0 bg-transparent p-5 font-mono text-[15px] leading-relaxed shadow-none placeholder:text-muted-foreground/60 focus-visible:ring-0"
      />
      <div className="flex items-center justify-between border-t border-border px-5 py-2.5 text-[11px] font-mono uppercase tracking-wider text-muted-foreground">
        <span>Query</span>
        <span className="hidden sm:inline">⌘ + Enter to run</span>
      </div>
    </div>
  );
}
