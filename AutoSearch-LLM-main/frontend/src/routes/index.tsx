import { createFileRoute } from "@tanstack/react-router";
import { useCallback, useEffect, useState } from "react";
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

const STORAGE_OPENAI = "openai_api_key";
const STORAGE_SERPER = "serper_api_key";

function backendBaseUrl(): string {
  return (
    import.meta.env.VITE_PUBLIC_BACKEND_URL?.replace(/\/$/, "") ||
    import.meta.env.VITE_BACKEND_URL?.replace(/\/$/, "") ||
    ""
  );
}

function hostLabel(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url.slice(0, 48);
  }
}

function mapApiSources(urls: string[]): Source[] {
  return urls.map((url) => ({
    title: hostLabel(url),
    url,
    snippet: "Open the link for the full page. Snippets are not returned by the API for this URL.",
  }));
}

interface ApiQueryResponse {
  answer: string;
  used_search: boolean;
  sources: string[];
  latency: number;
  routing_decision: string;
  confidence?: number | null;
  // Added by the backend reliability work; optional so older backends still work.
  retrieval_status?: string | null;
  grounded?: boolean;
}

interface ApiHealthResponse {
  status: string;
  credentials_configured?: { llm?: boolean; search?: boolean };
}

interface QueryResult {
  answer: string;
  mode: RoutingMode;
  reason: string;
  confidence: number;
  retrievalTriggered: boolean;
  sources: Source[];
  latencyMs: number;
  grounded: boolean;
}

// Mirrors backend retrieval_status values so the UI never implies an answer is
// source-backed when the backend says it is not.
function retrievalNote(status: string | null | undefined, grounded: boolean): string {
  switch (status) {
    case "ok":
      return "Answer grounded in retrieved sources.";
    case "partial":
      return "Answer grounded, but some sources failed to load.";
    case "no_useful_results":
      return "Sources were retrieved but did not support an answer; answered from model knowledge.";
    case "no_results":
      return "No usable sources found; answered from model knowledge.";
    case "failed":
      return "Web retrieval was unavailable; answered from model knowledge.";
    default:
      return grounded ? "Answer grounded in retrieved sources." : "";
  }
}

function mapApiToUi(data: ApiQueryResponse): QueryResult {
  const usedSearch = Boolean(data.used_search);
  const mode: RoutingMode = usedSearch ? "web_retrieval" : "direct_llm";
  const routing = (data.routing_decision || "").toLowerCase();
  const reason =
    routing === "search"
      ? "Classifier routed to web search + grounding."
      : routing === "direct"
        ? "Classifier routed to direct model answer."
        : usedSearch
          ? "Web search path was used for this response."
          : "Direct model path was used for this response.";
  const confidence =
    typeof data.confidence === "number" && !Number.isNaN(data.confidence)
      ? Math.min(1, Math.max(0, data.confidence))
      : 0.75;

  const grounded = Boolean(data.grounded);
  const note = retrievalNote(data.retrieval_status, grounded);

  return {
    answer: data.answer?.trim() || "No answer text returned.",
    mode,
    reason: note ? `${reason} ${note}` : reason,
    confidence,
    retrievalTriggered: usedSearch,
    sources: mapApiSources(data.sources ?? []),
    latencyMs: Math.max(0, Math.round((data.latency ?? 0) * 1000)),
    grounded,
  };
}

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

function Index() {
  const [openaiKey, setOpenaiKey] = useState("");
  const [serperKey, setSerperKey] = useState("");
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<QueryResult | null>(null);
  const [serverHasKeys, setServerHasKeys] = useState(false);
  const [backendReachable, setBackendReachable] = useState<boolean | null>(null);

  useEffect(() => {
    setOpenaiKey(sessionStorage.getItem(STORAGE_OPENAI) || "");
    setSerperKey(sessionStorage.getItem(STORAGE_SERPER) || "");
  }, []);

  // The backend may hold its own credentials (server-side deployment), in which
  // case the user does not need to supply any. /health is cheap and calls no
  // external API, so this costs nothing.
  useEffect(() => {
    const base = backendBaseUrl();
    if (!base) return;
    let cancelled = false;

    (async () => {
      try {
        const response = await fetch(`${base}/health`);
        if (!response.ok) return;
        const health = (await response.json()) as ApiHealthResponse;
        if (cancelled) return;
        const creds = health.credentials_configured;
        setServerHasKeys(Boolean(creds?.llm && creds?.search));
        setBackendReachable(true);
      } catch {
        if (!cancelled) setBackendReachable(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  const persistOpenai = useCallback((value: string) => {
    setOpenaiKey(value);
    sessionStorage.setItem(STORAGE_OPENAI, value);
  }, []);

  const persistSerper = useCallback((value: string) => {
    setSerperKey(value);
    sessionStorage.setItem(STORAGE_SERPER, value);
  }, []);

  const handleRun = useCallback(async () => {
    if (!query.trim()) {
      toast.error("Enter a query first");
      return;
    }
    if (!serverHasKeys && (!openaiKey.trim() || !serperKey.trim())) {
      toast.error("Both API keys are required", {
        description: "This backend has no server-side keys configured.",
      });
      return;
    }

    const base = backendBaseUrl();
    if (!base) {
      toast.error("Missing VITE_PUBLIC_BACKEND_URL", {
        description: "Set it in .env.local or your host dashboard.",
      });
      return;
    }

    setLoading(true);
    setResult(null);

    try {
      // Only send keys the user actually supplied; otherwise the backend
      // falls back to its own configured credentials.
      const body: Record<string, string> = { query: query.trim() };
      if (openaiKey.trim()) body.openai_api_key = openaiKey.trim();
      if (serperKey.trim()) body.serper_api_key = serperKey.trim();

      let response: Response;
      try {
        response = await fetch(`${base}/query`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        setBackendReachable(true);
      } catch {
        // fetch only rejects on network/CORS failure, never on an HTTP error.
        setBackendReachable(false);
        throw new Error(
          `Cannot reach the backend at ${base}. Check that it is running and that CORS allows this origin.`,
        );
      }

      const raw = await response.text();
      let payload: unknown = {};
      try {
        payload = raw ? JSON.parse(raw) : {};
      } catch {
        payload = {};
      }

      if (!response.ok) {
        const detail =
          typeof payload === "object" &&
          payload !== null &&
          "detail" in payload &&
          typeof (payload as { detail?: unknown }).detail === "string"
            ? (payload as { detail: string }).detail
            : `Request failed (${response.status})`;
        throw new Error(detail);
      }

      setResult(mapApiToUi(payload as ApiQueryResponse));
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Unknown error occurred";
      toast.error(message);
    } finally {
      setLoading(false);
    }
  }, [openaiKey, query, serperKey]);

  const handleClear = useCallback(() => {
    setOpenaiKey("");
    setSerperKey("");
    sessionStorage.removeItem(STORAGE_OPENAI);
    sessionStorage.removeItem(STORAGE_SERPER);
    toast.success("Keys cleared from this session");
  }, []);

  const keysSatisfied =
    serverHasKeys || Boolean(openaiKey.trim() && serperKey.trim());
  const runDisabled = !query.trim() || !keysSatisfied || loading;

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
              onChange={persistOpenai}
            />
            <ApiKeyCard
              label="Serper API Key"
              placeholder="Enter your Serper API key"
              icon={Search}
              value={serperKey}
              onChange={persistSerper}
            />
          </div>
          <p className="mt-3 font-mono text-[11px] text-muted-foreground">
            {serverHasKeys
              ? "This backend has its own credentials configured — keys are optional. Anything you enter overrides them for your request."
              : "Keys are stored only for this browser session (sessionStorage) and are sent only to your backend for each request."}
          </p>
          {backendReachable === false && (
            <p className="mt-2 font-mono text-[11px] text-destructive">
              Backend unreachable at {backendBaseUrl() || "(unset)"}.
            </p>
          )}

          <div className="mt-6">
            <QueryInput value={query} onChange={setQuery} onSubmit={handleRun} />
          </div>

          <div className="mt-5">
            <ActionBar
              onRun={handleRun}
              onClear={handleClear}
              loading={loading}
              disabled={runDisabled}
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
            Connected to FastAPI backend · BYO keys
          </span>
        </footer>
      </main>
    </div>
  );
}
