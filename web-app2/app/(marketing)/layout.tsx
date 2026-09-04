import "@designcodeio/threeui/style.css";
import "@/components/marketing/marketing.css";

// The marketing route is the only place WebGL ships. App routes never load it.
export default function MarketingLayout({ children }: { children: React.ReactNode }) {
  return <div className="m-root">{children}</div>;
}
