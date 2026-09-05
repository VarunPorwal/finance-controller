import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async redirects() {
    return [
      // Older links. Ingest lives on the Run screen; the old dashboard
      // paths map onto the same screens at the root.
      { source: "/sources", destination: "/run", permanent: true },
      { source: "/ingest", destination: "/run", permanent: true },
      { source: "/exceptions", destination: "/decisions", permanent: true },
      { source: "/exceptions/:id", destination: "/decisions", permanent: true },
      { source: "/activity", destination: "/controller-activity", permanent: true },
      { source: "/eval", destination: "/evaluation", permanent: true },
      { source: "/", destination: "/landing", permanent: false },
      { source: "/app1", destination: "/overview", permanent: true },
      { source: "/app1/:path*", destination: "/:path*", permanent: true },
    ];
  },
};

export default nextConfig;
