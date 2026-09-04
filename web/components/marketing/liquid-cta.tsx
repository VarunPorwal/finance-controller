import Link from "next/link";
import { ArrowRight } from "lucide-react";

/**
 * The one metallic moment: the primary CTA on the landing page, nowhere in
 * the app. A conic sheen over brushed white, in CSS. ThreeUI's WebGL
 * liquid-metal pill renders inside an opaque iframe with no readable label
 * on a dark ground, so the CSS treatment is the one that ships.
 */
export function LiquidCta({ href, label }: { href: string; label: string }) {
  return (
    <Link href={href} className="m-metal">
      {label}
      <ArrowRight width={15} height={15} />
    </Link>
  );
}
