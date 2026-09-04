"use client";

import { useState, type ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// staleTime 5 minutes: run summary, exceptions, rules, cash bridge, eval,
// records and sources data don't change unless a run happens, so there is
// no reason to refetch on every tab switch. gcTime 30 minutes so navigating
// away and back still shows the last data instantly instead of a skeleton,
// while a background refetch (if the data is stale) keeps it honest.
export function QueryProvider({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 5 * 60 * 1000,
            gcTime: 30 * 60 * 1000,
            refetchOnWindowFocus: false,
            retry: 1,
          },
        },
      }),
  );
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
