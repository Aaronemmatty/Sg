import { TopBar } from "@/components/layout/TopBar";
import { BacktestingContent } from "@/components/pages/backtesting/BacktestingContent";

export default function BacktestingPage() {
  return (
    <>
      <TopBar title="Backtesting" />
      <div className="flex-1 overflow-y-auto p-5">
        <BacktestingContent />
      </div>
    </>
  );
}
