import { Check, Sparkles } from "lucide-react";

const features = [
  "No hallucinations",
  "Real-time grounding",
  "Bring your own API keys",
];

export function HeroSection() {
  return (
    <section className="relative pt-16 pb-12 sm:pt-24 sm:pb-16 text-center">
      <div className="mx-auto inline-flex items-center gap-2 rounded-full border border-border-strong bg-card/60 px-3 py-1 text-xs font-medium tracking-wide text-muted-foreground backdrop-blur">
        <Sparkles className="h-3.5 w-3.5 text-primary" />
        <span className="font-mono uppercase">AI Routing Demo</span>
      </div>

      <h1 className="mx-auto mt-6 max-w-4xl text-balance text-4xl font-semibold leading-[1.1] tracking-tight sm:text-5xl md:text-6xl">
        AutoSearch-LLM —{" "}
        <span className="bg-gradient-to-r from-primary to-primary-glow bg-clip-text text-transparent">
          Adaptive AI
        </span>{" "}
        with Real-Time Web Grounding
      </h1>

      <p className="mx-auto mt-5 max-w-2xl text-balance text-base text-muted-foreground sm:text-lg">
        Dynamically routes queries between parametric LLM knowledge and live
        web retrieval.
      </p>

      <ul className="mx-auto mt-8 flex flex-wrap items-center justify-center gap-2 sm:gap-3">
        {features.map((f) => (
          <li
            key={f}
            className="inline-flex items-center gap-2 rounded-full border border-border bg-card/60 px-3 py-1.5 text-xs font-medium text-foreground/90 backdrop-blur sm:text-sm"
          >
            <span className="flex h-4 w-4 items-center justify-center rounded-full bg-primary/15 text-primary">
              <Check className="h-3 w-3" strokeWidth={3} />
            </span>
            {f}
          </li>
        ))}
      </ul>
    </section>
  );
}
