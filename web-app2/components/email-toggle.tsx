"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/client";
import { formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";

const SETTINGS_KEY = ["settings"] as const;

/**
 * "Email me when a run finishes", off by default, persisted in
 * tenants.settings. The last-sent time is the honesty check.
 */
export function EmailToggle() {
  const queryClient = useQueryClient();
  const { data } = useQuery({
    queryKey: SETTINGS_KEY,
    queryFn: async () => (await apiClient.GET("/api/v1/settings", {})).data ?? null,
  });

  const toggle = useMutation({
    mutationFn: async (next: boolean) => {
      const { data: out } = await apiClient.PATCH("/api/v1/settings", { params: { query: {} }, body: { email_on_run_complete: next } });
      return out;
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
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={toggle.isPending}
      onClick={() => toggle.mutate(!checked)}
      title={data?.email_last_sent_at ? `Last sent ${formatDateTime(data.email_last_sent_at)}` : "Never sent"}
      className="flex h-[32px] items-center gap-2.5 rounded-[8px] border border-line-strong bg-surface-2 px-2.5 text-[12px] text-ink-2 transition-colors hover:bg-surface-3"
    >
      <span className={cn("relative h-[16px] w-[28px] rounded-full transition-colors", checked ? "bg-ok" : "bg-line-strong")}>
        <span
          className={cn(
            "absolute top-[2px] h-[12px] w-[12px] rounded-full bg-white transition-transform",
            checked ? "translate-x-[14px]" : "translate-x-[2px]",
          )}
        />
      </span>
      Email on run
      <span className="text-[10.5px] text-ink-3">{data?.email_last_sent_at ? formatDateTime(data.email_last_sent_at) : "never sent"}</span>
    </button>
  );
}
