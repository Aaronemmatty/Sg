import { TopBar } from "@/components/layout/TopBar";
import { DashboardContent } from "@/components/pages/dashboard/DashboardContent";

export default function DashboardPage() {
  return (
    <>
      <TopBar title="Dashboard" />
      <div className="flex-1 overflow-y-auto p-5">
        <DashboardContent />
      </div>
    </>
  );
}
