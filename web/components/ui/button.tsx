"use client";

import type { ButtonHTMLAttributes, ReactNode } from "react";
import { motion } from "framer-motion";
import { cn } from "@/lib/utils";

type Variant = "default" | "primary" | "ghost" | "ok" | "bad" | "model";
type Size = "sm" | "md" | "lg";

const VARIANT: Record<Variant, string> = {
  default: "",
  primary: "btn-primary",
  ghost: "btn-ghost",
  ok: "btn-ok",
  bad: "btn-bad",
  model: "btn-model",
};

const SIZE: Record<Size, string> = { sm: "btn-sm", md: "", lg: "btn-lg" };

/**
 * Press feedback comes from `.btn:active` (scale 0.98, 160ms ease-out). When
 * the label changes, say from "Run" to "Running…", the new text blurs in
 * over the old rather than snapping, so the state change reads as one
 * object changing rather than two swapping.
 */
export function Button({
  variant = "default",
  size = "md",
  icon,
  className,
  children,
  type = "button",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
  size?: Size;
  icon?: ReactNode;
}) {
  const labelKey = typeof children === "string" ? children : undefined;
  return (
    <button type={type} className={cn("btn", VARIANT[variant], SIZE[size], className)} {...props}>
      {icon}
      {labelKey ? (
        <motion.span
          key={labelKey}
          initial={{ opacity: 0, filter: "blur(2px)" }}
          animate={{ opacity: 1, filter: "blur(0px)" }}
          transition={{ duration: 0.16, ease: "easeOut" }}
        >
          {children}
        </motion.span>
      ) : (
        children
      )}
    </button>
  );
}
