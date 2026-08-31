import { TopBar } from "@/components/layout/TopBar";
import { TradesContent } from "@/components/pages/trades/TradesContent";

export default function TradesPage() {
  return (
    <>
      <TopBar title="Trades" />
      <div className="flex-1 overflow-y-auto p-5">
        <TradesContent />
      </div>
    </>
  );
}
