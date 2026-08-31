import { NextResponse } from "next/server";
import { clearSessionCookies, getAccessToken } from "@/lib/auth/session";
import { SERVICES } from "@/lib/api/client";

export async function POST() {
  const token = await getAccessToken();

  if (token) {
    // Best-effort revoke at auth_service
    await fetch(`${SERVICES.auth}/api/v1/auth/logout`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
    }).catch(() => null);
  }

  await clearSessionCookies();
  return NextResponse.json({ success: true });
}
