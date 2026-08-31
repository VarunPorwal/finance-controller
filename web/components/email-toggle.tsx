"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/client";

const SETTINGS_KEY = ["settings"] as const;

function formatLastSent(iso: string | null | undefined): string {
  if (!iso) return "never sent";
  const d = new Date(iso);
  return `last sent ${d.toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })}`;
}

/**
 * "Email me when a run finishes" — off by default (api/routers/settings.py),
 * persisted in tenants.settings. The last-sent time is the honesty check: a
 * toggle with no evidence it ever fired is not trustworthy.
 */
export function EmailToggle() {
  const queryClient = useQueryClient();
  const { data } = useQuery({
    queryKey: SETTINGS_KEY,
    queryFn: async () => (await apiClient.GET("/api/v1/settings", {})).data ?? null,
  });

  const toggle = useMutation({
    mutationFn: async (next: boolean) => {
      const { data } = await apiClient.PATCH("/api/v1/settings", {
        params: { query: {} },
        body: { email_on_run_complete: next },
      });
      return data;
    },
    onMutate: async (next) => {
      await queryClient.cancelQueries({ queryKey: SETTINGS_KEY });
      const previous = queryClient.getQueryData(SETTINGS_KEY);
      queryClient.setQueryData(SETTINGS_KEY, (old: typeof data) => ({
        email_on_run_complete: next,
        email_last_sent_at: old?.email_last_sent_at ?? null,
      }));
      return { previous };
    },
    onError: (_err, _next, context) => {
      if (context?.previous) queryClient.setQueryData(SETTINGS_KEY, context.previous);
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: SETTINGS_KEY });
    },
  });

  const checked = data?.email_on_run_complete ?? false;

  return (
    <div className="flex items-center gap-2.5 rounded-lg border border-border px-3.5 py-2 text-[12.5px]">
      <label className="flex items-center gap-2">
        <input
          type="checkbox"
          checked={checked}
          onChange={(e) => toggle.mutate(e.target.checked)}
          disabled={toggle.isPending}
        />
        <span className="text-text-heading font-medium">Email me when a run finishes</span>
      </label>
      <span className="text-text-muted">· {formatLastSent(data?.email_last_sent_at)}</span>
    </div>
  );
}
