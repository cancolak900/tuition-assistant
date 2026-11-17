import { useState } from "react";
import { AddTuitionForm } from "../components/admin/AddTuitionForm";
import { BatchUpload } from "../components/admin/BatchUpload";
import { UnpaidTable } from "../components/admin/UnpaidTable";
import { UserMenu } from "../components/UserMenu";
import { AppHeader } from "../components/ui";

/** Figma screen "Admin" (8:27): add/update form and CSV upload on the left, paged unpaid list on the right. */
export function Admin() {
  // Saving a record or uploading a file can change who has an unpaid balance, so the list reloads.
  const [refreshKey, setRefreshKey] = useState(0);
  const refresh = () => setRefreshKey((k) => k + 1);

  return (
    <div className="flex min-h-screen flex-col">
      <AppHeader wide right={<UserMenu />} />
      <main className="mx-auto flex w-full max-w-[1184px] flex-col gap-xl px-xl py-2xl">
        <div className="flex flex-col gap-xs">
          <h1 className="type-heading">Tuition administration</h1>
          <p className="type-body-sm text-text-on-dark-muted">Create or update tuition records and track unpaid balances.</p>
        </div>
        <div className="flex flex-col gap-xl lg:flex-row lg:items-start">
          <div className="flex w-full flex-col gap-xl lg:w-[380px] lg:shrink-0">
            <AddTuitionForm onSaved={refresh} />
            <BatchUpload onDone={refresh} />
          </div>
          <UnpaidTable refreshKey={refreshKey} />
        </div>
      </main>
    </div>
  );
}
