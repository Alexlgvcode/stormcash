// One page, four tabs, persistent header (spec §18). The tab lives in the URL
// hash so a reload lands on the same tab.
import { useEffect, useState } from "react";
import { Header } from "./components/Header";
import { EventsProvider } from "./events";
import { ProofPage } from "./proof/ProofPage";
import { AccountsTab } from "./tabs/Accounts";
import { CasesTab } from "./tabs/Cases";

const TABS = [
  { id: "accounts", label: "Accounts" },
  { id: "cases", label: "Cases" },
  { id: "town", label: "Town" },
  { id: "evals", label: "Evals" },
] as const;
type TabId = (typeof TABS)[number]["id"];

function tabFromHash(): TabId {
  const id = location.hash.replace("#", "");
  return TABS.some((t) => t.id === id) ? (id as TabId) : "accounts";
}

function NotBuilt({ name }: { name: string }) {
  return <p className="p-8 text-xl text-slate-400">The {name} tab isn't built yet.</p>;
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

  useEffect(() => {
    const onHash = () => setTab(tabFromHash());
    addEventListener("hashchange", onHash);
    return () => removeEventListener("hashchange", onHash);
  }, []);

  return (
    <EventsProvider>
      <div className="min-h-screen bg-slate-950 text-slate-100">
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
          {tab === "town" && <NotBuilt name="Town" />}
          {tab === "evals" && <NotBuilt name="Evals" />}
        </main>
      </div>
    </EventsProvider>
  );
}
