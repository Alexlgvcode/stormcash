// One page, five workspaces, a persistent status bar (spec §18). The tab lives in
// the URL hash ("#cases", or "#stormdesk/evals" for a workspace's view) so a
// reload lands in the same place. #124's hashes (#accounts, #droid, #evals) still work.
import { useEffect, useState } from "react";
import { TopNav } from "./components/TopNav";
import { EventsProvider } from "./events";
import { ProofPage } from "./proof/ProofPage";
import { StatusProvider } from "./status";
import { CasesTab } from "./tabs/Cases";
import { LedgerTab } from "./tabs/Ledger";
import { OverviewTab } from "./tabs/Overview";
import { StormDeskTab } from "./tabs/StormDeskTab";
import { TownTab } from "./tabs/Town";

const TABS = ["overview", "town", "cases", "ledger", "stormdesk"] as const;
type TabId = (typeof TABS)[number];

// #124's tabs, now views inside a workspace.
const LEGACY: Record<string, [TabId, string]> = {
  accounts: ["ledger", "balances"],
  droid: ["stormdesk", "droid"],
  evals: ["stormdesk", "evals"],
};

function route(): [TabId, string | null] {
  const [id, sub] = location.hash.replace("#", "").split("/");
  if (LEGACY[id]) return LEGACY[id];
  return TABS.includes(id as TabId) ? [id as TabId, sub ?? null] : ["overview", null];
}

export default function App() {
  const proof = location.pathname.match(/^\/proof\/(\d+)\/?$/);
  if (proof) {
    // The public page a judge opens from the Proof QR: no header, no tabs, no live stream.
    return (
      <div className="min-h-screen bg-page text-ui text-ink">
        <ProofPage caseId={Number(proof[1])} />
      </div>
    );
  }
  return <Dashboard />;
}

function Dashboard() {
  const [[tab, sub], setRoute] = useState(route);

  useEffect(() => {
    const onHash = () => {
      setRoute(route());
      scrollTo({ top: 0 });
    };
    addEventListener("hashchange", onHash);
    return () => removeEventListener("hashchange", onHash);
  }, []);

  return (
    <EventsProvider>
      <StatusProvider>
        <div className="min-h-screen bg-page text-ui text-ink">
          <TopNav tab={tab} />
          <main className="mx-auto min-w-0 max-w-[1600px] px-4 pt-5 pb-24 sm:px-6 sm:pt-6 lg:px-8 lg:pb-12">
            {tab === "overview" && <OverviewTab />}
            {tab === "town" && <TownTab />}
            {tab === "cases" && <CasesTab />}
            {tab === "ledger" && <LedgerTab key={sub ?? ""} initial={sub} />}
            {tab === "stormdesk" && <StormDeskTab key={sub ?? ""} initial={sub} />}
          </main>
        </div>
      </StatusProvider>
    </EventsProvider>
  );
}
