"use client";

import { FormEvent, useMemo, useState } from "react";

type QueryResponse = {
  answer: string;
  used_search: boolean;
  sources: string[];
  latency: number;
  routing_decision: string;
  confidence?: number | null;
};

const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL;

export default function QueryPanel() {
  const [query, setQuery] = useState("");
  const [openaiApiKey, setOpenaiApiKey] = useState("");
  const [serperApiKey, setSerperApiKey] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<QueryResponse | null>(null);

  const canSubmit = useMemo(
    () =>
      query.trim().length > 1 &&
      openaiApiKey.trim().length > 0 &&
      serperApiKey.trim().length > 0 &&
      !loading,
    [query, openaiApiKey, serperApiKey, loading],
  );

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    setResult(null);
    setLoading(true);

    try {
      if (!backendUrl) {
        throw new Error("Missing NEXT_PUBLIC_BACKEND_URL configuration.");
      }

      const response = await fetch(`${backendUrl}/query`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          query: query.trim(),
          openai_api_key: openaiApiKey.trim(),
          serper_api_key: serperApiKey.trim(),
        }),
      });

      const raw = await response.text();
      let data: unknown = {};
      try {
        data = raw ? JSON.parse(raw) : {};
      } catch {
        data = {};
      }
      if (!response.ok) {
        const message =
          typeof data === "object" &&
          data !== null &&
          "detail" in data &&
          typeof (data as { detail?: unknown }).detail === "string"
            ? (data as { detail: string }).detail
            : "Request failed";
        throw new Error(message);
      }
      setResult(data as QueryResponse);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error occurred");
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="container">
      <section className="card">
        <h1>AutoSearch-LLM</h1>
        <p className="sub">
          Adaptive routing between direct LLM answer and grounded web retrieval.
        </p>
        <p className="sub">
          Your API keys are used only for this request and never stored.
        </p>

        <form onSubmit={onSubmit} className="form">
          <label>
            OpenAI API Key
            <input
              type="password"
              placeholder="sk-..."
              value={openaiApiKey}
              onChange={(event) => setOpenaiApiKey(event.target.value)}
              autoComplete="off"
            />
          </label>

          <label>
            Serper API Key
            <input
              type="password"
              placeholder="serper-..."
              value={serperApiKey}
              onChange={(event) => setSerperApiKey(event.target.value)}
              autoComplete="off"
            />
          </label>

          <label>
            Query
            <textarea
              rows={5}
              placeholder="Ask a question..."
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
          </label>

          <button type="submit" disabled={!canSubmit}>
            {loading ? "Processing..." : "Submit"}
          </button>
        </form>
      </section>

      {error && (
        <section className="card error">
          <p>{error}</p>
        </section>
      )}

      {result && (
        <section className="card">
          <h2>Answer</h2>
          <p className="answer">{result.answer}</p>

          <div className="meta">
            <span>
              <strong>Used Search:</strong> {String(result.used_search)}
            </span>
            <span>
              <strong>Routing Decision:</strong> {result.routing_decision}
            </span>
            <span>
              <strong>Latency:</strong> {result.latency}s
            </span>
            {typeof result.confidence === "number" ? (
              <span>
                <strong>Confidence:</strong> {result.confidence}
              </span>
            ) : null}
          </div>

          <h3>Sources</h3>
          {result.sources.length === 0 ? (
            <p className="sub">No sources returned.</p>
          ) : (
            <ul>
              {result.sources.map((url) => (
                <li key={url}>
                  <a href={url} target="_blank" rel="noreferrer">
                    {url}
                  </a>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
    </main>
  );
}
