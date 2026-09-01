export function LoadingState() {
  return (
    <div className="grid gap-6 lg:grid-cols-3">
      <div className="space-y-3 rounded-2xl border border-border bg-card/60 p-6 backdrop-blur lg:col-span-2">
        <Shimmer className="h-4 w-1/3" />
        <Shimmer className="h-3 w-full" />
        <Shimmer className="h-3 w-11/12" />
        <Shimmer className="h-3 w-10/12" />
        <Shimmer className="h-3 w-9/12" />
        <Shimmer className="h-3 w-11/12" />
      </div>
      <div className="space-y-6">
        <div className="space-y-3 rounded-2xl border border-border bg-card/60 p-6 backdrop-blur">
          <Shimmer className="h-4 w-1/2" />
          <Shimmer className="h-10 w-full" />
          <Shimmer className="h-2 w-full" />
        </div>
        <div className="space-y-3 rounded-2xl border border-border bg-card/60 p-6 backdrop-blur">
          <Shimmer className="h-4 w-1/2" />
          <Shimmer className="h-8 w-full" />
          <Shimmer className="h-8 w-full" />
        </div>
      </div>
    </div>
  );
}

function Shimmer({ className = "" }: { className?: string }) {
  return (
    <div
      className={
        "animate-pulse rounded-md bg-gradient-to-r from-muted via-accent to-muted " +
        className
      }
    />
  );
}
