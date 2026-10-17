// One page, five tabs, persistent sidebar (spec §18, issue #93). The tab lives
// in the URL hash so a reload lands on the same tab. `#intro` (or the I key)
// lays the opening slide over the dashboard; the live stream stays connected
// under it.
import { useEffect, useState, type ReactNode } from "react";
import { Intro } from "./components/Intro";
import { Sidebar } from "./components/Sidebar";
import { PageHeader } from "./components/ui";
import { EventsProvider } from "./events";
import { ProofPage } from "./proof/ProofPage";
import { AccountsTab } from "./tabs/Accounts";
import { CasesTab } from "./tabs/Cases";
import { DroidTab } from "./tabs/Droid";
import { EvalsTab } from "./tabs/Evals";
import { TownTab } from "./tabs/Town";

const TABS = ["accounts", "cases", "town", "evals", "droid"] as const;
type TabId = (typeof TABS)[number];

function tabFromHash(): TabId {
  const id = location.hash.replace("#", "");
  return TABS.includes(id as TabId) ? (id as TabId) : "accounts";
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
      <div className="min-h-screen bg-slate-950 text-slate-100 [color-scheme:dark]">
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
      <div className="flex min-h-screen bg-page text-ui text-ink" inert={intro}>
        <Sidebar tab={intro ? "intro" : tab} />
        <main className="min-w-0 flex-1 px-10 pt-8">
          {tab === "accounts" && <AccountsTab />}
          {tab === "cases" && (
            <NotRedesigned title="Cases">
              <CasesTab />
            </NotRedesigned>
          )}
          {tab === "town" && (
            <NotRedesigned title="Town">
              <TownTab />
            </NotRedesigned>
          )}
          {tab === "evals" && (
            <NotRedesigned title="Evals">
              <EvalsTab />
            </NotRedesigned>
          )}
          {tab === "droid" && (
            <NotRedesigned title="Droid">
              <DroidTab />
            </NotRedesigned>
          )}
        </main>
      </div>
      {intro && <Intro onClose={closeIntro} />}
    </EventsProvider>
  );
}

// A tab whose content hasn't moved to the new design yet: its old dark panels,
// unchanged, under the new page title.
function NotRedesigned({ title, children }: { title: string; children: ReactNode }) {
  return (
    <>
      <PageHeader title={title} />
      <div className="-mx-10 min-h-[calc(100vh-7rem)] bg-slate-950 text-base text-slate-100 [color-scheme:dark]">
        {children}
      </div>
    </>
  );
}
