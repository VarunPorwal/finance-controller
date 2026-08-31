export function PlaceholderPanel({ title, note }: { title: string; note: string }) {
  return (
    <div className="rounded-[var(--radius-card)] border border-dashed border-border bg-card p-8 text-center">
      <p className="text-sm font-semibold tracking-wide text-text-muted uppercase">{title}</p>
      <p className="mt-2 text-sm text-text-body">{note}</p>
    </div>
  );
}
