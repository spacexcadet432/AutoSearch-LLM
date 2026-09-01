export function TechGridBackground() {
  return (
    <div
      aria-hidden
      className="pointer-events-none fixed inset-0 -z-10 overflow-hidden"
    >
      <div className="absolute inset-0 bg-tech-grid opacity-60" />
      <div className="absolute inset-x-0 top-0 h-[700px] bg-hero-glow" />
      <div
        className="absolute -top-40 left-1/2 h-[500px] w-[900px] -translate-x-1/2 rounded-full opacity-40 blur-3xl"
        style={{
          background:
            "radial-gradient(closest-side, color-mix(in oklab, var(--primary) 35%, transparent), transparent)",
        }}
      />
    </div>
  );
}
