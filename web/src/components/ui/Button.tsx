import type { ButtonHTMLAttributes } from "react";
import { cn } from "./cn";

/** Figma component "Button": Style (Primary/Success/Secondary/Ghost/Danger) x Size (Medium 32px / Large 44px). */
export type ButtonVariant = "primary" | "success" | "secondary" | "ghost" | "danger";
export type ButtonSize = "md" | "lg";

const variants: Record<ButtonVariant, string> = {
  primary: "bg-accent-primary text-text-on-accent hover:brightness-95",
  success: "bg-accent-success text-text-on-dark hover:brightness-110",
  secondary: "bg-bg-elevated text-text-on-dark border border-border-dark-strong hover:bg-border-dark",
  ghost: "bg-transparent text-text-on-dark-muted hover:text-text-on-dark hover:bg-bg-elevated",
  danger: "bg-transparent text-accent-danger border border-accent-danger hover:bg-accent-danger/10",
};

const sizes: Record<ButtonSize, string> = {
  md: "h-8 px-lg type-button",
  lg: "h-11 px-xl type-label-strong",
};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
}

export function Button({ variant = "primary", size = "md", className, type = "button", ...props }: ButtonProps) {
  return (
    <button
      type={type}
      className={cn(
        "inline-flex items-center justify-center gap-sm rounded-sm whitespace-nowrap transition",
        "cursor-pointer disabled:cursor-not-allowed disabled:opacity-50",
        variants[variant],
        sizes[size],
        className,
      )}
      {...props}
    />
  );
}
