import { TopBar } from "@/components/layout/TopBar";
import { SettingsContent } from "@/components/pages/settings/SettingsContent";

export default function SettingsPage() {
  return (
    <>
      <TopBar title="Settings" />
      <div className="flex-1 overflow-y-auto p-5">
        <SettingsContent />
      </div>
    </>
  );
}
