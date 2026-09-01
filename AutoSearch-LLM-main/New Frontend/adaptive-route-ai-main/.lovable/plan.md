# AutoSearch-LLM — Frontend Build Plan

A single-page premium AI systems engineering interface. Frontend-only mock for now (no real API calls), structured so wiring real OpenAI + Serper calls later is trivial.

## Scope

- One route: `/` (replace placeholder in `src/routes/index.tsx`)
- Update `__root.tsx` head metadata (title, description, OG) for SEO
- Dark-only theme (navy + subtle blue), no light-mode toggle
- No backend, no Lovable Cloud — keys live in component state only
- Responsive: 1-col mobile, 2-col API key row at md+, results stack on mobile / 2-col grid on lg+

## Design system (`src/styles.css`)

Override tokens to match the reference aesthetic:

- `--background`: deep navy (oklch ~0.18 0.04 260)
- `--card`: slightly lighter navy (~0.22 0.04 260)
- `--border`: subtle blue (~0.35 0.06 250 / low alpha)
- `--primary`: electric blue (~0.65 0.18 250)
- `--primary-foreground`: near-white
- `--muted-foreground`: cool gray-blue
- `--ring`: primary glow
- New custom tokens:
  - `--gradient-hero`: subtle radial navy → blue glow
  - `--gradient-primary`: linear primary → primary-glow
  - `--shadow-glow`: soft blue glow for primary buttons/focus
  - `--shadow-card`: elevated card shadow
  - Grid background: `--grid-line` color + a `.bg-tech-grid` utility (CSS background-image with subtle 1px lines)
- Fonts: load JetBrains Mono (display accents, code, numbers) + Inter (body) via Google Fonts in `__root.tsx` head links. Map to `font-mono` / `font-sans` via Tailwind theme extension in `styles.css`.

## Components (`src/components/autosearch/`)

1. **HeroSection.tsx** — badge ("AI Routing Demo"), H1, subtitle, 3 feature pills with check icons. Subtle animated glow background.
2. **ApiKeyCard.tsx** — reusable card: icon circle, label, masked password input, show/hide toggle. Props: `label`, `icon`, `value`, `onChange`.
3. **ApiKeyRow.tsx** — wraps two `ApiKeyCard`s (OpenAI, Serper) + helper text.
4. **QueryInput.tsx** — large textarea, mono-flavored font, focus ring glow, character hint.
5. **ActionBar.tsx** — "Run Adaptive Query" (primary, glow) + "Clear Keys" (ghost/outline).
6. **AnswerPanel.tsx** — markdown-rendered answer area with citation chips. Use `react-markdown` + `remark-gfm` (need to `bun add`).
7. **RoutingDecisionPanel.tsx** — shows mode badge ("Direct LLM" vs "Web Retrieval"), confidence bar, "Retrieval triggered" status pill.
8. **SourcesPanel.tsx** — list of expandable source cards (Collapsible from shadcn): title, URL, snippet.
9. **MetadataBadges.tsx** — row of small cards: latency (ms), routing mode, source count, confidence %.
10. **LoadingState.tsx** — skeleton shimmer for results panels.
11. **TechGridBackground.tsx** — fixed-position subtle grid + radial glow behind hero.

All components use semantic tokens only (no hardcoded colors).

## Page composition (`src/routes/index.tsx`)

```
<TechGridBackground />
<main container max-w-6xl, vertical rhythm>
  <HeroSection />
  <Card "Configure">
    <ApiKeyRow />
    <QueryInput />
    <ActionBar />
  </Card>
  {hasResult && (
    <section>
      <MetadataBadges />
      <grid lg:grid-cols-3 gap-6>
        <AnswerPanel className="lg:col-span-2" />
        <div stack>
          <RoutingDecisionPanel />
          <SourcesPanel />
        </div>
      </grid>
    </section>
  )}
</main>
```

## Mock behavior

- "Run Adaptive Query" with no keys → toast warning (sonner already installed).
- With keys + query → set loading 1.2s → populate mock response object containing answer markdown, routing decision, 3 mock sources, latency, confidence. This proves the UI; real wiring is a later turn.
- "Clear Keys" → resets both inputs, toast confirmation.

## Dependencies to add

- `react-markdown`
- `remark-gfm`

## SEO / head

- Title: "AutoSearch-LLM — Adaptive AI with Real-Time Web Grounding"
- Description: routing + grounding one-liner (<160 chars)
- og:title, og:description, twitter:card

## Out of scope (this turn)

- Real OpenAI/Serper calls
- Auth / persistence
- Multi-page routing
- Light mode

## Acceptance

- Replaces placeholder index
- Matches premium dark navy + subtle blue aesthetic with grid bg + glow
- Fully responsive, no layout shift, accessible focus states
- All colors via semantic tokens
- Mock query flow end-to-end works
