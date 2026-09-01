import { ArrowRight, Eraser, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";

interface ActionBarProps {
  onRun: () => void;
  onClear: () => void;
  loading?: boolean;
  disabled?: boolean;
}

export function ActionBar({ onRun, onClear, loading, disabled }: ActionBarProps) {
  return (
    <div className="flex flex-col-reverse gap-3 sm:flex-row sm:items-center sm:justify-between">
      <Button
        type="button"
        variant="ghost"
        onClick={onClear}
        className="gap-2 text-muted-foreground hover:text-foreground"
      >
        <Eraser className="h-4 w-4" />
        Clear Keys
      </Button>

      <Button
        type="button"
        onClick={onRun}
        disabled={disabled || loading}
        className="group gradient-primary h-11 gap-2 px-5 font-medium text-primary-foreground shadow-glow transition-transform hover:translate-y-[-1px] disabled:opacity-60"
      >
        {loading ? (
          <>
            <Loader2 className="h-4 w-4 animate-spin" />
            Routing query…
          </>
        ) : (
          <>
            Run Adaptive Query
            <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
          </>
        )}
      </Button>
    </div>
  );
}
