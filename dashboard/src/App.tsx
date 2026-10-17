// One page, five tabs, persistent header (spec §18). The tab lives in the URL
// hash so a reload lands on the same tab. `#intro` (or the I key) lays the
// opening slide over the dashboard; the live stream stays connected under it.
import { useEffect, useState } from "react";
import { Header } from "./components/Header";
import { Intro } from "./components/Intro";
import { EventsProvider } from "./events";
import { ProofPage } from "./proof/ProofPage";
import { AccountsTab } from "./tabs/Accounts";
import { CasesTab } from "./tabs/Cases";
import { DroidTab } from "./tabs/Droid";
import { EvalsTab } from "./tabs/Evals";
import { TownTab } from "./tabs/Town";

const TABS = [
  { id: "accounts", label: "Accounts" },
  { id: "cases", label: "Cases" },
  { id: "town", label: "Town" },
  { id: "evals", label: "Evals" },
  { id: "droid", label: "Droid" },
] as const;
type TabId = (typeof TABS)[number]["id"];

function tabFromHash(): TabId {
  const id = location.hash.replace("#", "");
  return TABS.some((t) => t.id === id) ? (id as TabId) : "accounts";
}

const introFromHash = () => location.hash === "#intro";
const closeIntro = () => {
  location.hash = "accounts";
};

// I opens the intro, unless the operator is typing (e.g. the operator name on a flag).
function onIntroKey(e: KeyboardEvent) {
  if (e.key.toLowerCase() !== "i" || e.metaKey || e.ctrlKey || e.altKey || e.repeat) return;
  if (e.target instanceof Element && e.target.closest("input, textarea, select, [contenteditable]")) return;
  location.hash = "intro";
}

export default function App() {
  const proof = location.pathname.match(/^\/proof\/(\d+)\/?$/);
  if (proof) {
    // The public page a judge opens from the Proof QR: no header, no tabs, no live stream.
    return (
      <div className="min-h-screen bg-slate-950 text-slate-100">
        <ProofPage caseId={Number(proof[1])} />
      </div>
    );
  }
  return <Dashboard />;
}

function Dashboard() {
  const [tab, setTab] = useState<TabId>(tabFromHash);
  const [intro, setIntro] = useState(introFromHash);

  useEffect(() => {
    const onHash = () => {
      setTab(tabFromHash());
      setIntro(introFromHash());
    };
    addEventListener("hashchange", onHash);
    addEventListener("keydown", onIntroKey);
    return () => {
      removeEventListener("hashchange", onHash);
      removeEventListener("keydown", onIntroKey);
    };
  }, []);

  return (
    <EventsProvider>
      <div className="min-h-screen bg-slate-950 text-slate-100" inert={intro}>
        <Header />
        <nav className="flex gap-1 border-b border-slate-800 px-6">
          {TABS.map((t) => (
            <a
              key={t.id}
              href={`#${t.id}`}
              className={`border-b-4 px-5 py-3 text-xl font-semibold ${
                tab === t.id ? "border-sky-400 text-white" : "border-transparent text-slate-400 hover:text-slate-200"
              }`}
            >
              {t.label}
            </a>
          ))}
        </nav>
        <main>
          {tab === "accounts" && <AccountsTab />}
          {tab === "cases" && <CasesTab />}
          {tab === "town" && <TownTab />}
          {tab === "evals" && <EvalsTab />}
          {tab === "droid" && <DroidTab />}
        </main>
      </div>
      {intro && <Intro onClose={closeIntro} />}
    </EventsProvider>
  );
}
