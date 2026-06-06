import { cn } from "@/lib/utils";

function Bone({ className }: { className?: string }) {
  return (
    <div
      className={cn(
        "animate-pulse rounded-md bg-muted",
        className,
      )}
    />
  );
}

export function MapSkeleton() {
  return (
    <div className="flex h-full w-full items-center justify-center bg-muted/30">
      <div className="flex flex-col items-center gap-2">
        <Bone className="h-32 w-48 rounded-lg" />
        <Bone className="h-3 w-24" />
      </div>
    </div>
  );
}

export function DatabaseSkeleton() {
  return (
    <div className="flex h-full flex-col gap-2 p-3">
      <Bone className="h-6 w-32" />
      <Bone className="h-24 w-full" />
      <Bone className="h-4 w-full" />
      <Bone className="h-4 w-3/4" />
      <div className="mt-2 flex flex-col gap-1.5">
        {Array.from({ length: 5 }).map((_, i) => (
          <Bone key={i} className="h-6 w-full" />
        ))}
      </div>
    </div>
  );
}

export function ChartSkeleton() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 p-6">
      <Bone className="h-40 w-56 rounded-lg" />
      <Bone className="h-3 w-32" />
    </div>
  );
}

export function ReportSkeleton() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 p-6">
      <Bone className="h-48 w-36 rounded" />
      <Bone className="h-3 w-24" />
    </div>
  );
}

export function AgentSkeleton() {
  return (
    <div className="flex h-full flex-col gap-3 p-3">
      <Bone className="h-12 w-full rounded-lg" />
      <Bone className="h-16 w-full rounded-lg" />
      <Bone className="h-10 w-full rounded-lg" />
      <Bone className="h-10 w-full rounded-lg" />
      <Bone className="h-10 w-3/4 rounded-lg" />
    </div>
  );
}

export function ChatSkeleton() {
  return (
    <div className="flex h-full flex-col gap-4 p-4">
      <div className="flex justify-end">
        <Bone className="h-10 w-48 rounded-lg" />
      </div>
      <div className="flex justify-start">
        <Bone className="h-16 w-64 rounded-lg" />
      </div>
      <div className="flex justify-end">
        <Bone className="h-10 w-40 rounded-lg" />
      </div>
      <div className="mt-auto">
        <Bone className="h-12 w-full rounded-lg" />
      </div>
    </div>
  );
}
