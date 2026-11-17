// @vitest-environment node
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import tokens from "./figma-tokens.json";

// Keeps theme.css identical to the tokens exported from Figma: a changed value fails here.
const css = readFileSync(fileURLToPath(new URL("./theme.css", import.meta.url)), "utf8");

function declared(name: string): string | undefined {
  const match = css.match(new RegExp(`${name.replace(/[-]/g, "\\-")}:\\s*([^;]+);`));
  return match?.[1].trim();
}

describe("theme matches the Figma tokens", () => {
  it.each(Object.entries(tokens.colors))("color %s = %s", (name, hex) => {
    expect(declared(name)?.toUpperCase()).toBe(hex.toUpperCase());
  });

  it.each([...Object.entries(tokens.radius), ...Object.entries(tokens.spacing)])("%s = %ipx", (name, px) => {
    expect(declared(name)).toBe(`${px}px`);
  });

  it.each(Object.entries(tokens.textStyles))("text style %s", (_name, style) => {
    const rule = css.match(new RegExp(`@utility ${style.utility} \\{([^}]*)\\}`))?.[1];
    expect(rule, `missing @utility ${style.utility}`).toBeDefined();
    expect(rule).toContain(`font-size: ${style.size}px`);
    expect(rule).toContain(`line-height: ${style.lineHeight}px`);
    expect(rule).toContain(`font-weight: ${style.weight}`);
    expect(rule).toContain(style.family === "JetBrains Mono" ? "var(--font-mono)" : "var(--font-sans)");
  });

  it("uses the Figma fonts", () => {
    expect(declared("--font-sans")).toMatch(/^"Outfit"/);
    expect(declared("--font-mono")).toMatch(/^"JetBrains Mono"/);
  });
});
