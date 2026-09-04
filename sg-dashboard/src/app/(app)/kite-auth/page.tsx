import { TopBar } from "@/components/layout/TopBar";
import { getSession, isAdmin, isRiskOfficer } from "@/lib/auth/session";
import { redirect } from "next/navigation";
import { KiteAuthContent } from "@/components/pages/kite-auth/KiteAuthContent";

export default async function KiteAuthPage() {
  const session = await getSession();

  // Strict role guard: only admin or risk_officer may access Kite authentication
  if (!session || (!isAdmin(session.user) && !isRiskOfficer(session.user))) {
    redirect("/dashboard");
  }

  return (
    <>
      <TopBar title="Kite Connect Authentication" />
      <div className="flex-1 overflow-y-auto p-6">
        <KiteAuthContent user={session.user} />
      </div>
    </>
  );
}
