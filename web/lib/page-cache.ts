// Module-level (not component-level) cache keyed by an explicit string, so
// data fetched on one visit to a sidebar tab is still there — instantly,
// no skeleton — the next time that tab mounts, while a fresh fetch runs in
// the background to keep it current. Session-lived only; never persisted.
const store = new Map<string, unknown>();

export function cacheGet<T>(key: string | null | undefined): T | undefined {
  if (!key) return undefined;
  return store.get(key) as T | undefined;
}

export function cacheSet<T>(key: string | null | undefined, value: T): void {
  if (!key) return;
  store.set(key, value);
}
