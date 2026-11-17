import tokens from "../theme/figma-tokens.json";
import { AppHeader, Avatar, Button, Chip, SendButton, Table, TextField, type ButtonVariant, type Column } from "../components/ui";

/** Development page that renders the Figma design system (tokens + components) for a side-by-side check. */

interface DemoRow {
  studentNo: string;
  name: string;
  term: string;
  tuition: string;
  paid: string;
  balance: string;
}

const rows: DemoRow[] = [
  { studentNo: "S1004", name: "Mert Kaya", term: "2026-FALL", tuition: "$7,500.00", paid: "$0.00", balance: "$7,500.00" },
  { studentNo: "S1007", name: "Elif Demir", term: "2026-FALL", tuition: "$2,500.00", paid: "$1,000.00", balance: "$1,500.00" },
];

const columns: Column<DemoRow>[] = [
  { key: "s", header: "Student", render: (r) => r.studentNo },
  { key: "n", header: "Name", render: (r) => r.name, muted: true },
  { key: "t", header: "Term", render: (r) => r.term, muted: true },
  { key: "tu", header: "Tuition", render: (r) => r.tuition },
  { key: "p", header: "Paid", render: (r) => r.paid },
  { key: "b", header: "Balance", render: (r) => r.balance, emphasis: true },
];

const variants: ButtonVariant[] = ["primary", "success", "secondary", "ghost", "danger"];

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-lg">
      <h2 className="type-heading">{title}</h2>
      {children}
    </section>
  );
}

export function Styleguide() {
  return (
    <div className="min-h-screen">
      <AppHeader right={<Avatar initials="S1" />} />
      <main className="mx-auto flex max-w-[1184px] flex-col gap-2xl px-xl py-2xl">
        <div>
          <h1 className="type-display">Design system</h1>
          <p className="type-body-sm text-text-on-dark-muted">{tokens.source}</p>
        </div>

        <Section title="Colors">
          <div className="grid grid-cols-2 gap-md sm:grid-cols-4 lg:grid-cols-5">
            {Object.entries(tokens.colors).map(([name, hex]) => (
              <div key={name} className="flex items-center gap-md rounded-lg border border-border-dark bg-bg-surface p-md">
                <span className="size-8 shrink-0 rounded-sm border border-border-dark-strong" style={{ background: `var(${name})` }} />
                <span className="min-w-0">
                  <span className="block truncate type-caption">{name.replace("--color-", "")}</span>
                  <span className="block type-mono text-text-on-dark-muted">{hex}</span>
                </span>
              </div>
            ))}
          </div>
        </Section>

        <Section title="Text styles">
          <div className="flex flex-col gap-sm">
            {Object.entries(tokens.textStyles).map(([name, s]) => (
              <div key={name} className="flex items-baseline gap-xl border-b border-border-dark pb-sm">
                <span className="w-40 shrink-0 type-caption text-text-on-dark-muted">{name}</span>
                <span className={s.utility}>Tuition is due by September 30, 2026</span>
                <span className="ml-auto type-mono text-text-on-dark-muted">{s.size}/{s.lineHeight} · {s.weight}</span>
              </div>
            ))}
          </div>
        </Section>

        <Section title="Radius and spacing">
          <div className="flex flex-wrap items-end gap-xl">
            {Object.entries(tokens.radius).map(([name, v]) => (
              <div key={name} className="flex flex-col items-center gap-sm">
                <span className="size-14 border border-border-dark-strong bg-bg-elevated" style={{ borderRadius: `var(${name})` }} />
                <span className="type-caption text-text-on-dark-muted">{name.replace("--radius-", "")} {v}</span>
              </div>
            ))}
            {Object.entries(tokens.spacing).map(([name, v]) => (
              <div key={name} className="flex flex-col items-center gap-sm">
                <span className="bg-accent-primary" style={{ width: `var(${name})`, height: `var(${name})` }} />
                <span className="type-caption text-text-on-dark-muted">{name.replace("--spacing-", "")} {v}</span>
              </div>
            ))}
          </div>
        </Section>

        <Section title="Buttons">
          <div className="flex flex-wrap items-center gap-md">
            {variants.map((v) => (
              <Button key={v} variant={v}>{v[0].toUpperCase() + v.slice(1)}</Button>
            ))}
            <Button size="lg">Sign in</Button>
            <Button disabled>Disabled</Button>
          </div>
        </Section>

        <Section title="Inputs and small components">
          <div className="flex flex-wrap items-start gap-xl">
            <TextField className="w-80" label="Username" placeholder="e.g. s1001" />
            <TextField className="w-80" label="Username" placeholder="e.g. s1001" error="Invalid username or password" />
            <div className="flex items-center gap-md pt-xl">
              <Chip>What is my balance?</Chip>
              <Avatar initials="S1" />
              <SendButton type="button" />
            </div>
          </div>
        </Section>

        <Section title="Table">
          <div className="rounded-lg border border-border-dark bg-bg-surface">
            <Table columns={columns} rows={rows} rowKey={(r) => r.studentNo} />
          </div>
        </Section>
      </main>
    </div>
  );
}
