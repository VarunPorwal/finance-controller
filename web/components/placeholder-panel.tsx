export function PlaceholderPanel({ title, note }: { title: string; note: string }) {
  return (
    <div className="border-rule bg-ink-800 rounded-lg border border-dashed p-8 text-center">
      <p className="font-heading text-paper-300 text-sm font-semibold uppercase tracking-wide">
        {title}
      </p>
      <p className="text-paper-500 mt-2 text-sm">{note}</p>
    </div>
  );
}
