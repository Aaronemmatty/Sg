import { TopBar } from "@/components/layout/TopBar";
import { PortfolioContent } from "@/components/pages/portfolio/PortfolioContent";

export default function PortfolioPage() {
  return (
    <>
      <TopBar title="Portfolio" />
      <div className="flex-1 overflow-y-auto p-5">
        <PortfolioContent />
      </div>
    </>
  );
}
