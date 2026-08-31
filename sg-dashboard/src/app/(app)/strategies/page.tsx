import { TopBar } from "@/components/layout/TopBar";
import { StrategiesContent } from "@/components/pages/strategies/StrategiesContent";

export default function StrategiesPage() {
  return (
    <>
      <TopBar title="Strategies" />
      <div className="flex-1 overflow-y-auto p-5">
        <StrategiesContent />
      </div>
    </>
  );
}
