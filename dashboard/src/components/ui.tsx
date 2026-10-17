// The dashboard's shared building blocks (issue #93), in the bank style of Alex's
// "Capital One" mockup: a light navy headline, segmented pill tabs, sections (a
// light heading over a rule), account-style rows and tables, chips and pill buttons.
import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, TdHTMLAttributes, ThHTMLAttributes } from "react";
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

/** A large title with a short grey subtitle on the same baseline, the tab's one-line takeaway, then its tabs. */
export function PageHeader({ title, subtitle, takeaway, children }: {
  title: string;
  subtitle?: string;
  takeaway?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <header className="mb-8">
      <h1 className="text-title font-light text-heading">{title}</h1>
      {subtitle && <p className="mt-1.5 text-ui text-secondary">{subtitle}</p>}
      {takeaway && <p className="mt-4 max-w-[90ch] text-[18px] leading-7 text-ink">{takeaway}</p>}
      {children && <div className="mt-6">{children}</div>}
    </header>
  );
}

/** Segmented pill tabs; the selected one is filled navy. */
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
    <div role="tablist" className="flex flex-wrap gap-2">
      {tabs.map((t) => (
        <button
          key={t.id}
          role="tab"
          aria-selected={value === t.id}
          onClick={() => onChange(t.id)}
          className={`rounded-full px-4 py-1.5 text-ui ${
            value === t.id ? "bg-heading font-semibold text-white" : "bg-neutral-bg text-secondary hover:bg-accent-tint hover:text-heading"
          }`}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

/** A light navy heading over a rule. */
export function Section({ title, right, children }: { title: string; right?: ReactNode; children: ReactNode }) {
  return (
    <section>
      <div className="flex flex-wrap items-end justify-between gap-3 border-b border-rule pb-2">
        <h2 className="text-section font-light text-heading">{title}</h2>
        {right}
      </div>
      <div className="mt-1">{children}</div>
    </section>
  );
}

export function Eyebrow({ children }: { children: ReactNode }) {
  return <div className="text-eyebrow font-semibold uppercase text-secondary">{children}</div>;
}

export function Table({ children }: { children: ReactNode }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-left text-ui">{children}</table>
    </div>
  );
}

export function Th({ num, className = "", ...rest }: ThHTMLAttributes<HTMLTableCellElement> & { num?: boolean }) {
  return (
    <th
      {...rest}
      className={`border-b border-rule py-2.5 pr-6 text-th font-semibold text-secondary last:pr-0 ${num ? "text-right" : ""} ${className}`}
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
      className={`py-3.5 pr-6 align-top last:pr-0 ${rule ? "border-b border-rule" : ""} ${
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
      className={`whitespace-nowrap rounded-button border-[1.5px] border-accent font-semibold disabled:opacity-50 ${
        small ? "px-3 py-1 text-th" : "px-[18px] py-2 text-ui"
      } ${primary ? "bg-accent text-white hover:bg-accent/90" : "bg-page text-accent hover:bg-accent-tint"} ${className}`}
    />
  );
}

/** Facts in a row: a small label over a navy value; `big` for the few numbers a judge should read first. */
export function Strip({ items, big = false }: { items: { label: string; value: ReactNode; sub?: ReactNode }[]; big?: boolean }) {
  return (
    <div className="flex flex-wrap gap-x-12 gap-y-4 py-1">
      {items.map((it) => (
        <div key={it.label} className="min-w-0">
          <div className="text-th text-secondary">{it.label}</div>
          <div className={big ? "text-[30px] leading-10 font-light text-heading" : "text-[18px] leading-7 font-semibold text-heading"}>
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
        <div key={label} className="grid grid-cols-[minmax(8rem,auto)_1fr] gap-6 border-b border-rule py-2.5">
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
      className={`rounded-full border-[1.5px] border-rule px-4 py-1.5 text-ui text-ink placeholder:text-secondary focus:border-accent focus:outline-none ${
        props.className ?? ""
      }`}
    />
  );
}

/** "Loading…", an error, or an empty state, in plain secondary text. */
export function Note({ tone = "neutral", children }: { tone?: "neutral" | "danger"; children: ReactNode }) {
  return <p className={tone === "danger" ? "text-danger" : "text-secondary"}>{children}</p>;
}
