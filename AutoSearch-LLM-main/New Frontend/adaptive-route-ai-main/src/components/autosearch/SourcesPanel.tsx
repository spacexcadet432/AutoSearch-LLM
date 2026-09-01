import { ChevronDown, ExternalLink, Link2 } from "lucide-react";
import { useState } from "react";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { PanelHeader } from "./PanelHeader";

export interface Source {
  title: string;
  url: string;
  snippet: string;
}

export function SourcesPanel({ sources }: { sources: Source[] }) {
  return (
    <section className="rounded-2xl border border-border bg-card/60 p-6 shadow-card-elevated backdrop-blur">
      <PanelHeader
        icon={Link2}
        label="Retrieved Sources"
        hint={`${sources.length} results`}
      />
      <ul className="space-y-2">
        {sources.map((s, i) => (
          <SourceItem key={s.url + i} index={i + 1} source={s} />
        ))}
      </ul>
    </section>
  );
}

function SourceItem({ index, source }: { index: number; source: Source }) {
  const [open, setOpen] = useState(false);
  let host = source.url;
  try {
    host = new URL(source.url).hostname.replace(/^www\./, "");
  } catch {
    /* noop */
  }
  return (
    <li>
      <Collapsible open={open} onOpenChange={setOpen}>
        <div className="rounded-lg border border-border bg-background/40 transition-colors hover:border-border-strong">
          <CollapsibleTrigger className="flex w-full items-center gap-3 px-3 py-2.5 text-left">
            <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md border border-border bg-card/80 font-mono text-[10px] text-muted-foreground">
              {index}
            </span>
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm font-medium text-foreground">
                {source.title}
              </div>
              <div className="truncate font-mono text-[11px] text-muted-foreground">
                {host}
              </div>
            </div>
            <ChevronDown
              className={
                "h-4 w-4 shrink-0 text-muted-foreground transition-transform " +
                (open ? "rotate-180" : "")
              }
            />
          </CollapsibleTrigger>
          <CollapsibleContent className="overflow-hidden data-[state=closed]:animate-accordion-up data-[state=open]:animate-accordion-down">
            <div className="border-t border-border px-3 py-3 text-sm text-muted-foreground">
              <p className="leading-relaxed">{source.snippet}</p>
              <a
                href={source.url}
                target="_blank"
                rel="noreferrer noopener"
                className="mt-3 inline-flex items-center gap-1.5 font-mono text-[11px] uppercase tracking-wider text-primary hover:text-primary-glow"
              >
                Open source
                <ExternalLink className="h-3 w-3" />
              </a>
            </div>
          </CollapsibleContent>
        </div>
      </Collapsible>
    </li>
  );
}
