"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";

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

  useEffect(() => {
    const storedOpenaiKey = sessionStorage.getItem("openai_api_key") || "";
    const storedSerperKey = sessionStorage.getItem("serper_api_key") || "";
    if (storedOpenaiKey) {
      setOpenaiApiKey(storedOpenaiKey);
    }
    if (storedSerperKey) {
      setSerperApiKey(storedSerperKey);
    }
  }, []);

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

  const onOpenAiChange = (value: string) => {
    setOpenaiApiKey(value);
    sessionStorage.setItem("openai_api_key", value);
  };

  const onSerperChange = (value: string) => {
    setSerperApiKey(value);
    sessionStorage.setItem("serper_api_key", value);
  };

  const clearKeys = () => {
    setOpenaiApiKey("");
    setSerperApiKey("");
    sessionStorage.removeItem("openai_api_key");
    sessionStorage.removeItem("serper_api_key");
  };

  return (
    <main className="container">
      <section className="hero card">
        <span className="demoBadge">AI Routing Demo</span>
        <h1>AutoSearch-LLM - Adaptive AI with Real-Time Web Grounding</h1>
        <p className="subtitle">
          Dynamically routes queries between LLM knowledge and live web retrieval.
        </p>
        <p className="featureLine">
          <span>No hallucinations</span>
          <span>Real-time data</span>
          <span>Bring your own API keys</span>
        </p>
      </section>

      <section className="card">
        <form onSubmit={onSubmit} className="form">
          <div className="inputGrid">
            <label className="inputCard">
              <span className="labelTitle">
                <span className="labelIcon">OA</span>
                OpenAI API Key
              </span>
              <input
                type="password"
                placeholder="sk-..."
                value={openaiApiKey}
                onChange={(event) => onOpenAiChange(event.target.value)}
                autoComplete="off"
              />
            </label>

            <label className="inputCard">
              <span className="labelTitle">
                <span className="labelIcon">SP</span>
                Serper API Key
              </span>
              <input
                type="password"
                placeholder="Enter your Serper API key"
                value={serperApiKey}
                onChange={(event) => onSerperChange(event.target.value)}
                autoComplete="off"
              />
            </label>
          </div>

          <label className="inputCard">
            <span className="labelTitle">
              <span className="labelIcon">Q</span>
              Query
            </span>
            <textarea
              rows={7}
              placeholder="Ask anything... (e.g., What happened in AI this week?)"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
            <span className="helperText">
              Keys are stored only for this session and cleared when you close the
              tab.
            </span>
          </label>

          <div className="actionsRow">
            <button className="submitBtn" type="submit" disabled={!canSubmit}>
              {loading ? (
                <span className="btnLoading">
                  <span className="spinner" />
                  Processing...
                </span>
              ) : (
                "Run Adaptive Query"
              )}
            </button>
            <button
              className="clearBtn"
              type="button"
              onClick={clearKeys}
              disabled={loading}
            >
              Clear Keys
            </button>
          </div>
        </form>
      </section>

      {error && (
        <section className="card errorCard">
          <p>{error}</p>
        </section>
      )}

      {loading && (
        <section className="card loadingCard">
          <div className="loadingPulse" />
          <div className="loadingPulse short" />
          <div className="loadingPulse" />
        </section>
      )}

      {result && (
        <section className="card resultCard">
          <h2>Answer</h2>
          <p className="answer">{result.answer}</p>

          <div className="meta">
            <span>
              <strong>Routing:</strong>{" "}
              {result.used_search ? "Used Web Search" : "Answered from Model"}
            </span>
            <span>
              <strong>Routing Decision:</strong> {result.routing_decision}
            </span>
            <span>
              <strong>Latency:</strong> {result.latency}s
            </span>
            <span>
              <strong>Sources Used:</strong> {result.sources.length}
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
            <ul className="sourcesList">
              {result.sources.map((url) => (
                <li key={url}>
                  <a href={url} target="_blank" rel="noreferrer">
                    <span className="sourceIcon">link</span>
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
