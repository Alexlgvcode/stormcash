// StormDesk workspace: the path from detection to a person's decision, with
// each stage's real counts, then the review queue (where a person approves or
// rejects), Droid's runs with their cost and latency, and the evals. AI only
// proposes; deterministic code proves cases, and only a person approves (§0).
import { useState, type ReactNode } from "react";
import type { CaseSummary, FlagRow } from "../api";
import { FlagsView } from "../components/StormDesk";
import { Embedded, PageHeader, Tabs } from "../components/ui";
import { useLive } from "../live";
import { DroidTab } from "./Droid";
import { EvalsTab } from "./Evals";

const VIEWS = [
  { id: "queue", label: "Review queue" },
  { id: "droid", label: "Agent runs" },
  { id: "evals", label: "Evals" },
] as const;
type View = (typeof VIEWS)[number]["id"];

interface ConsoleTotals {
  totals: {
    droid_runs: number;
    valid: number;
    credits_total: number | null;
    mean_duration_ms: number | null;
    fake_runs: number;
    tool_calls: number;
  };
}

type Who = "rules" | "ai" | "person";
const WHO: Record<Who, { text: string; cls: string }> = {
  rules: { text: "Deterministic", cls: "border-teal/60 text-success" },
  ai: { text: "AI · advisory", cls: "border-accent/50 text-accent" },
  person: { text: "A person", cls: "border-ink/70 text-heading" },
};

function Stage({ n, title, who, value, sub }: { n: number; title: string; who: Who; value: ReactNode; sub: ReactNode }) {
  return (
    <li className="relative min-w-0 bg-surface px-3 py-3 sm:px-4">
      <div className="flex flex-wrap items-center justify-between gap-x-2 gap-y-1">
        <span className="text-eyebrow font-semibold uppercase text-secondary">{n}. {title}</span>
        <span className={`whitespace-nowrap rounded border px-1.5 text-[11px] leading-[18px] font-semibold uppercase tracking-wide ${WHO[who].cls}`}>
          {WHO[who].text}
        </span>
      </div>
      <div className="mt-1.5 text-[22px] leading-8 font-semibold tabular-nums text-heading">{value}</div>
      <div className="text-th text-secondary">{sub}</div>
    </li>
  );
}

function Pipeline() {
  const flags = useLive<FlagRow[]>("/v1/flags?limit=200", ["flag", "approval", "town"]);
  const cases = useLive<CaseSummary[]>("/v1/cases?limit=200", ["case_opened", "town"]);
  const droid = useLive<ConsoleTotals>("/v1/droid/console", ["flag", "stormdesk_step"], 2000);
  const f = flags.data ?? [];
  const reviewed = f.filter((x) => x.review);
  const agree = reviewed.filter((x) => x.review?.verdict === "agree").length;
  const open = f.filter((x) => x.status === "open").length;
  const approved = f.filter((x) => x.status === "approved").length;
  const rejected = f.filter((x) => x.status === "rejected").length;
  const t = droid.data?.totals;
  const dash = (v: unknown, show: ReactNode) => (v == null ? "—" : show);
  return (
    <ol aria-label="From detection to a decision"
      className="mb-8 grid grid-cols-2 gap-px overflow-hidden rounded-[10px] border border-rule bg-rule lg:grid-cols-3 2xl:grid-cols-6">
      <Stage n={1} title="Detection" who="rules" value={dash(flags.data, f.length)}
        sub="detector hits turned into flags (cap drain, silent shop, dark area)" />
      <Stage n={2} title="Case" who="rules" value={dash(cases.data, cases.data?.length)}
        sub="proven by signed records, no model involved" />
      <Stage n={3} title="Agent" who="ai" value={dash(t, t?.droid_runs)}
        sub={t ? `Droid runs · ${t.valid} valid · ${t.mean_duration_ms != null ? `${(t.mean_duration_ms / 1000).toFixed(1)} s mean` : "—"} · ${t.fake_runs} by the rules-only stand-in` : "…"} />
      <Stage n={4} title="Reviewer" who="ai" value={dash(flags.data, reviewed.length)}
        sub={`second opinions · ${agree} agree · ${reviewed.length - agree} don't`} />
      <Stage n={5} title="Human decision" who="person" value={dash(flags.data, open)}
        sub={`waiting · ${approved} approved · ${rejected} rejected`} />
      <Stage n={6} title="Audit" who="rules" value={dash(flags.data, approved + rejected)}
        sub="decisions signed with the operator's name, stored with the run" />
    </ol>
  );
}

export function StormDeskTab({ initial }: { initial: string | null }) {
  const [view, setView] = useState<View>(() => (VIEWS.some((v) => v.id === initial) ? initial as View : "queue"));
  const pick = (v: View) => {
    setView(v);
    history.replaceState(null, "", `#stormdesk/${v}`);
  };
  return (
    <div>
      <PageHeader title="StormDesk" subtitle="The agent proposes, a second agent reviews, a person decides. It never moves money on its own.">
        <Tabs tabs={VIEWS} value={view} onChange={pick} />
      </PageHeader>
      <Pipeline />
      <Embedded.Provider value>
        {view === "queue" ? <FlagsView /> : view === "droid" ? <DroidTab /> : <EvalsTab />}
      </Embedded.Provider>
    </div>
  );
}
