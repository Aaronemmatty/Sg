import { TopBar } from "@/components/layout/TopBar";
import { RiskContent } from "@/components/pages/risk/RiskContent";

export default function RiskPage() {
  return (
    <>
      <TopBar title="Risk Engine" />
      <div className="flex-1 overflow-y-auto p-5">
        <RiskContent />
      </div>
    </>
  );
}
