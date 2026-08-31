import { TopBar } from "@/components/layout/TopBar";
import { getSession } from "@/lib/auth/session";
import { isAdmin } from "@/lib/auth/session";
import { redirect } from "next/navigation";
import { AdminContent } from "@/components/pages/admin/AdminContent";

export default async function AdminPage() {
  const session = await getSession();
  if (!session || !isAdmin(session.user)) {
    redirect("/dashboard");
  }

  return (
    <>
      <TopBar title="Admin" />
      <div className="flex-1 overflow-y-auto p-5">
        <AdminContent user={session.user} />
      </div>
    </>
  );
}
