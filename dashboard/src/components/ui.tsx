// The dashboard's shared building blocks, in the command-center style: a navy
// page, panels one step lighter, hairline rules, segmented tabs, state chips in
// teal / amber / coral, tabular numerals and monospace ids. Built on #124's set,
// re-themed; the names and props are unchanged so every tab keeps working.
import { createContext, useContext, useState, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode,
  type TdHTMLAttributes, type ThHTMLAttributes } from "react";
import { Icon, type IconName } from "./Icon";

export type Tone = "success" | "danger" | "warning" | "neutral" | "agents";

const PILL: Record<Tone, string> = {
  success: "bg-success-bg text-success",
  danger: "bg-danger-bg text-danger",
  warning: "bg-warning-bg text-warning",
  neutral: "bg-neutral-bg text-neutral",
  agents: "bg-accent-tint text-accent", // "Agents disagree · a person decides"
};

export function Pill({ tone, title, children }: { tone: Tone; title?: string; children: ReactNode }) {
  return (
    <span title={title} className={`inline-flex items-center whitespace-nowrap rounded-pill px-2.5 py-0.5 text-th font-semibold ${PILL[tone]}`}>
      {children}
    </span>
  );
}

/** "simulated" / "replayed" / "real": where a number comes from, always next to it (§0 honest copy). */
export function Source({ kind }: { kind: "real" | "simulated" | "replayed" | "derived" }) {
  const cls = {
    real: "border-teal/60 text-success",
    simulated: "border-rule text-secondary",
    replayed: "border-amber/60 text-warning",
    derived: "border-accent/50 text-accent",
  }[kind];
  return (
    <span className={`inline-flex items-center whitespace-nowrap rounded border px-1.5 text-[11px] leading-[18px] font-semibold uppercase tracking-wide ${cls}`}>
      {kind}
    </span>
  );
}

/** Inside a workspace (StormDesk's Droid and Evals views), a tab's header drops to a section heading. */
export const Embedded = createContext(false);

/** A title with a short grey subtitle, the tab's one-line takeaway, then its tabs. */
export function PageHeader({ title, subtitle, takeaway, children }: {
  title: string;
  subtitle?: string;
  takeaway?: ReactNode;
  children?: ReactNode;
}) {
  const embedded = useContext(Embedded);
  return (
    <header className={embedded ? "mb-6" : "mb-6 sm:mb-8"}>
      {embedded ? (
        <h2 className="text-section font-semibold text-heading">{title}</h2>
      ) : (
        <h1 className="text-[24px] leading-8 font-semibold text-heading sm:text-title">{title}</h1>
      )}
      {subtitle && <p className="mt-1 text-ui text-secondary">{subtitle}</p>}
      {takeaway && <p className="mt-3 max-w-[90ch] text-[16px] leading-6 text-ink">{takeaway}</p>}
      {children && <div className="mt-5">{children}</div>}
    </header>
  );
}

/** Segmented tabs; the selected one is off-white on navy. ≥44px tall on touch screens. */
export function Tabs<T extends string>({
  tabs,
  value,
  onChange,
}: {
  tabs: readonly { id: T; label: string }[];
  value: T;
  onChange: (id: T) => void;
}) {
  return (
    <div role="tablist" className="inline-flex max-w-full flex-wrap gap-1 rounded-[10px] border border-rule bg-surface p-1">
      {tabs.map((t) => (
        <button
          key={t.id}
          role="tab"
          aria-selected={value === t.id}
          onClick={() => onChange(t.id)}
          className={`min-h-9 rounded-[7px] px-3.5 text-ui pointer-coarse:min-h-11 ${
            value === t.id ? "bg-ink font-semibold text-on-light" : "text-secondary hover:bg-raised hover:text-heading"
          }`}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

/** A heading over a rule. */
export function Section({ title, right, children }: { title: string; right?: ReactNode; children: ReactNode }) {
  return (
    <section className="min-w-0">
      <div className="flex flex-wrap items-end justify-between gap-3 border-b border-rule pb-2">
        <h2 className="text-section font-semibold text-heading">{title}</h2>
        {right}
      </div>
      <div className="mt-1">{children}</div>
    </section>
  );
}

/** A surface panel with an eyebrow title: for the few places where grouping needs a boundary. */
export function Panel({ title, right, className = "", children }: {
  title?: ReactNode;
  right?: ReactNode;
  className?: string;
  children: ReactNode;
}) {
  return (
    <section className={`min-w-0 rounded-[10px] border border-rule bg-surface ${className}`}>
      {(title || right) && (
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-rule px-4 py-2.5">
          {title && <div className="text-eyebrow font-semibold uppercase text-secondary">{title}</div>}
          {right}
        </div>
      )}
      <div className="px-4 py-3">{children}</div>
    </section>
  );
}

export function Eyebrow({ children }: { children: ReactNode }) {
  return <div className="text-eyebrow font-semibold uppercase text-secondary">{children}</div>;
}

export function Table({ children }: { children: ReactNode }) {
  return (
    <div className="max-w-full overflow-x-auto">
      {/* Narrow screens: smaller type, tighter gutters, and long words wrap, so tables fit instead of scrolling. */}
      <table className="w-full border-collapse text-left text-ui tabular-nums max-sm:text-th max-sm:[&_td]:pr-2.5 max-sm:[&_td]:break-words max-sm:[&_td]:whitespace-normal max-sm:[&_th]:pr-2.5">{children}</table>
    </div>
  );
}

export function Th({ num, className = "", ...rest }: ThHTMLAttributes<HTMLTableCellElement> & { num?: boolean }) {
  return (
    <th
      {...rest}
      className={`border-b border-rule py-2.5 pr-5 text-th font-semibold text-secondary last:pr-0 ${num ? "text-right" : ""} ${className}`}
    />
  );
}

/** A table cell; `rule={false}` drops its hairline when a detail row follows. */
export function Td({
  num,
  rule = true,
  className = "",
  ...rest
}: TdHTMLAttributes<HTMLTableCellElement> & { num?: boolean; rule?: boolean }) {
  return (
    <td
      {...rest}
      className={`py-3 pr-5 align-top last:pr-0 ${rule ? "border-b border-rule" : ""} ${
        num ? "whitespace-nowrap text-right tabular-nums" : ""
      } ${className}`}
    />
  );
}

const STATUS: Record<Tone, { icon: IconName; color: string }> = {
  success: { icon: "check", color: "text-success" },
  danger: { icon: "cross", color: "text-danger" },
  warning: { icon: "alert", color: "text-warning" },
  neutral: { icon: "minus", color: "text-secondary" },
  agents: { icon: "minus", color: "text-accent" },
};

/** One item of a status line: an icon in the tone's color, then the text. */
export function StatusItem({ tone, children }: { tone: Tone; children: ReactNode }) {
  const s = STATUS[tone];
  return (
    <span className="inline-flex items-center gap-1.5">
      <Icon name={s.icon} size={18} className={s.color} />
      <span className="text-ink">{children}</span>
    </span>
  );
}

export function Button({
  primary = false,
  small = false,
  className = "",
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { primary?: boolean; small?: boolean }) {
  return (
    <button
      {...rest}
      className={`whitespace-nowrap rounded-button border font-semibold disabled:opacity-50 pointer-coarse:min-h-11 ${
        small ? "min-h-8 px-3 text-th" : "min-h-10 px-4 text-ui"
      } ${primary ? "border-ink bg-ink text-on-light hover:bg-ink/90" : "border-rule bg-surface text-heading hover:bg-raised"} ${className}`}
    />
  );
}

/** Facts in a row: a small label over a value; `big` for the few numbers to read first. */
export function Strip({ items, big = false }: { items: { label: string; value: ReactNode; sub?: ReactNode }[]; big?: boolean }) {
  return (
    <div className="flex flex-wrap gap-x-10 gap-y-4 py-1">
      {items.map((it) => (
        <div key={it.label} className="min-w-0">
          <div className="text-th text-secondary">{it.label}</div>
          <div className={big ? "text-[28px] leading-9 font-semibold text-heading tabular-nums" : "text-[17px] leading-7 font-semibold text-heading tabular-nums"}>
            {it.value}
          </div>
          {it.sub && <div className="text-th text-secondary">{it.sub}</div>}
        </div>
      ))}
    </div>
  );
}

/** label · value rows separated by hairlines (a definition list without boxes). */
export function Facts({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <dl>
      {rows.map(([label, value]) => (
        <div key={label} className="grid grid-cols-1 gap-x-6 gap-y-0.5 border-b border-rule py-2.5 sm:grid-cols-[minmax(8rem,auto)_1fr]">
          <dt className="text-secondary">{label}</dt>
          <dd className="min-w-0 break-words">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

/** A small text input in the house style. */
export function TextInput(props: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      className={`min-h-10 rounded-button border border-rule bg-surface px-3 text-ui text-ink placeholder:text-secondary focus:border-accent focus:outline-none pointer-coarse:min-h-11 ${
        props.className ?? ""
      }`}
    />
  );
}

/** A select in the house style. */
export function Select({ value, onChange, options, label }: {
  value: string;
  onChange: (v: string) => void;
  options: readonly { id: string; label: string }[];
  label: string;
}) {
  return (
    <label className="flex min-w-0 items-center gap-2 text-th text-secondary">
      <span className="whitespace-nowrap">{label}</span>
      <select value={value} onChange={(e) => onChange(e.target.value)}
        className="min-h-10 min-w-0 rounded-button border border-rule bg-surface px-2 text-ui text-ink focus:border-accent focus:outline-none pointer-coarse:min-h-11">
        {options.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
      </select>
    </label>
  );
}

/** A long id, truncated, in monospace; press to copy the whole thing. */
export function CopyId({ value, chars = 10, className = "" }: { value: string | null | undefined; chars?: number; className?: string }) {
  const [copied, setCopied] = useState(false);
  if (!value) return <span className="text-secondary">—</span>;
  const shown = value.length > chars + 1 ? `${value.slice(0, chars)}…` : value;
  return (
    <button
      type="button"
      title={`${value}\n(click to copy)`}
      aria-label={`Copy ${value}`}
      onClick={(e) => {
        e.stopPropagation();
        navigator.clipboard?.writeText(value).then(() => {
          setCopied(true);
          setTimeout(() => setCopied(false), 1200);
        }).catch(() => undefined);
      }}
      className={`inline-flex max-w-full items-center gap-1 rounded px-1 -mx-1 font-mono text-th text-ink hover:bg-raised pointer-coarse:min-h-11 ${className}`}
    >
      <span className="truncate">{shown}</span>
      <span className="text-[11px] font-sans text-secondary">{copied ? "copied" : ""}</span>
    </button>
  );
}

/** "Loading…", an error, or an empty state, in plain secondary text. */
export function Note({ tone = "neutral", children }: { tone?: "neutral" | "danger"; children: ReactNode }) {
  return <p className={tone === "danger" ? "text-danger" : "text-secondary"}>{children}</p>;
}
