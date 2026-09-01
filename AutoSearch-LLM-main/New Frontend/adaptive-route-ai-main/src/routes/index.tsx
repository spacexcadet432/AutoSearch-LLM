import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { KeyRound, Search } from "lucide-react";
import { toast } from "sonner";
import { Toaster } from "@/components/ui/sonner";

import { TechGridBackground } from "@/components/autosearch/TechGridBackground";
import { HeroSection } from "@/components/autosearch/HeroSection";
import { ApiKeyCard } from "@/components/autosearch/ApiKeyCard";
import { QueryInput } from "@/components/autosearch/QueryInput";
import { ActionBar } from "@/components/autosearch/ActionBar";
import { AnswerPanel } from "@/components/autosearch/AnswerPanel";
import {
  RoutingDecisionPanel,
  type RoutingMode,
} from "@/components/autosearch/RoutingDecisionPanel";
import {
  SourcesPanel,
  type Source,
} from "@/components/autosearch/SourcesPanel";
import { MetadataBadges } from "@/components/autosearch/MetadataBadges";
import { LoadingState } from "@/components/autosearch/LoadingState";

export const Route = createFileRoute("/")({
  component: Index,
  head: () => ({
    meta: [
      {
        title:
          "AutoSearch-LLM — Adaptive AI with Real-Time Web Grounding",
      },
      {
        name: "description",
        content:
          "Adaptive AI routing system that dynamically chooses between LLM knowledge and live web retrieval for grounded, hallucination-free answers.",
      },
      {
        property: "og:title",
        content: "AutoSearch-LLM — Adaptive AI Routing",
      },
      {
        property: "og:description",
        content:
          "Routes queries between parametric LLM knowledge and real-time web retrieval. Bring your own keys.",
      },
    ],
  }),
});

interface QueryResult {
  answer: string;
  mode: RoutingMode;
  reason: string;
  confidence: number;
  retrievalTriggered: boolean;
  sources: Source[];
  latencyMs: number;
}

function detectTemporal(q: string): boolean {
  const signals = [
    /\b(today|yesterday|tomorrow|now|currently|latest|recent|recently)\b/i,
    /\b(this (week|month|year)|last (week|month|year))\b/i,
    /\b(20\d{2}|news|update|happened|breaking|announce)\b/i,
    /\b(price|stock|score|weather|release[d]?)\b/i,
  ];
  return signals.some((r) => r.test(q));
}

function buildMockResult(query: string): QueryResult {
  const temporal = detectTemporal(query);
  const mode: RoutingMode = temporal ? "web_retrieval" : "direct_llm";

  if (mode === "web_retrieval") {
    return {
      mode,
      reason: "Temporal / knowledge-sensitive signal detected",
      confidence: 0.92,
      retrievalTriggered: true,
      latencyMs: 1843,
      answer: `Based on retrieved sources, here is a grounded synthesis of **"${query.trim()}"**:\n\n- Multiple recent reports converge on the same trajectory.\n- Independent corroboration was found across **3 sources**.\n- Citations are inline below; expand the source cards for snippets.\n\n> The router selected \`web_retrieval\` because the query references time-sensitive information that exceeds the model's training cutoff.\n\n\`\`\`json\n{\n  "router": "web_retrieval",\n  "k": 3,\n  "rerank": "mmr"\n}\n\`\`\``,
      sources: [
        {
          title: "Frontier model release notes — November 2026",
          url: "https://example.com/ai/release-notes",
          snippet:
            "A new wave of frontier model releases this week introduced extended context windows and improved tool-use planning across providers.",
        },
        {
          title: "Industry analysis: routing & retrieval architectures",
          url: "https://research.example.org/routing-retrieval",
          snippet:
            "Adaptive routers that decide between parametric recall and retrieval are emerging as a default pattern for production assistants.",
        },
        {
          title: "Benchmark roundup: grounded vs ungrounded answers",
          url: "https://benchmarks.example.io/grounded",
          snippet:
            "Grounded responses reduced hallucinations by 47% on temporally sensitive evaluations versus direct LLM-only baselines.",
        },
      ],
    };
  }

  return {
    mode,
    reason: "Stable knowledge — no retrieval required",
    confidence: 0.81,
    retrievalTriggered: false,
    latencyMs: 612,
    sources: [],
    answer: `**"${query.trim()}"** — answered directly from parametric knowledge.\n\nThe router classified this query as stable, well-covered by the model's training distribution, and not time-sensitive. No web retrieval was triggered.\n\n- Cost: minimized\n- Latency: optimized\n- Confidence: high\n\n> If you suspect the answer is stale, rephrase to include a temporal cue (e.g., "this week", "latest").`,
  };
}

function Index() {
  const [openaiKey, setOpenaiKey] = useState("");
  const [serperKey, setSerperKey] = useState("");
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<QueryResult | null>(null);

  const handleRun = () => {
    if (!query.trim()) {
      toast.error("Enter a query first");
      return;
    }
    if (!openaiKey || !serperKey) {
      toast.warning("Add both API keys to run a real query", {
        description: "Running mock pipeline for preview.",
      });
    }
    setLoading(true);
    setResult(null);
    window.setTimeout(() => {
      setResult(buildMockResult(query));
      setLoading(false);
    }, 1200);
  };

  const handleClear = () => {
    setOpenaiKey("");
    setSerperKey("");
    toast.success("Keys cleared from session");
  };

  return (
    <div className="relative min-h-screen">
      <TechGridBackground />
      <Toaster />

      <main className="mx-auto w-full max-w-6xl px-4 pb-24 sm:px-6 lg:px-8">
        <HeroSection />

        <section
          aria-label="Query configuration"
          className="rounded-2xl border border-border-strong bg-card/50 p-5 shadow-card-elevated backdrop-blur sm:p-7"
        >
          <div className="mb-5 flex items-center justify-between">
            <h2 className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
              Configure
            </h2>
            <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground/70">
              session-only
            </span>
          </div>

          <div className="grid gap-3 md:grid-cols-2">
            <ApiKeyCard
              label="OpenAI API Key"
              placeholder="sk-..."
              icon={KeyRound}
              value={openaiKey}
              onChange={setOpenaiKey}
            />
            <ApiKeyCard
              label="Serper API Key"
              placeholder="serper-..."
              icon={Search}
              value={serperKey}
              onChange={setSerperKey}
            />
          </div>
          <p className="mt-3 font-mono text-[11px] text-muted-foreground">
            Keys are session-only and never permanently stored.
          </p>

          <div className="mt-6">
            <QueryInput value={query} onChange={setQuery} onSubmit={handleRun} />
          </div>

          <div className="mt-5">
            <ActionBar
              onRun={handleRun}
              onClear={handleClear}
              loading={loading}
            />
          </div>
        </section>

        {(loading || result) && (
          <section
            aria-label="Results"
            className="mt-10 space-y-6 animate-fade-in"
          >
            {result && (
              <MetadataBadges
                latencyMs={result.latencyMs}
                routingMode={
                  result.mode === "web_retrieval" ? "Web Retrieval" : "Direct LLM"
                }
                sourceCount={result.sources.length}
                confidence={result.confidence}
              />
            )}

            {loading ? (
              <LoadingState />
            ) : result ? (
              <div className="grid gap-6 lg:grid-cols-3">
                <div className="lg:col-span-2">
                  <AnswerPanel markdown={result.answer} />
                </div>
                <div className="space-y-6">
                  <RoutingDecisionPanel
                    mode={result.mode}
                    confidence={result.confidence}
                    retrievalTriggered={result.retrievalTriggered}
                    reason={result.reason}
                  />
                  {result.sources.length > 0 && (
                    <SourcesPanel sources={result.sources} />
                  )}
                </div>
              </div>
            ) : null}
          </section>
        )}

        <footer className="mt-20 flex flex-col items-center gap-1 text-center font-mono text-[11px] uppercase tracking-wider text-muted-foreground">
          <span>AutoSearch-LLM · Adaptive Routing Engine</span>
          <span className="text-muted-foreground/60">
            v0.1 · preview build
          </span>
        </footer>
      </main>
    </div>
  );
}
