import { TopBar } from "@/components/layout/TopBar";
import { MLModelsContent } from "@/components/pages/ml-models/MLModelsContent";

export default function MLModelsPage() {
  return (
    <>
      <TopBar title="ML Models" />
      <div className="flex-1 overflow-y-auto p-5">
        <MLModelsContent />
      </div>
    </>
  );
}
