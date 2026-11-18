import type { ReactNode } from "react";
import { UserMenu } from "../components/UserMenu";
import { AppHeader } from "../components/ui";

/** Signed-in shell used until a screen is built, and for roles without a web screen (bank). */
export function Placeholder({ title, children, wide = false }: { title: string; children: ReactNode; wide?: boolean }) {
  return (
    <div className="flex min-h-dvh flex-col">
      <AppHeader right={<UserMenu />} />
      <main className={wide ? "mx-auto w-full max-w-[1184px] px-lg sm:px-xl py-2xl" : "mx-auto w-full max-w-chat px-lg sm:px-xl py-2xl"}>
        <h1 className="type-display">{title}</h1>
        <div className="mt-sm type-body-sm text-text-on-dark-muted">{children}</div>
      </main>
    </div>
  );
}
