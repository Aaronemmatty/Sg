import { type NextRequest, NextResponse } from "next/server";
import { setSessionCookies } from "@/lib/auth/session";
import { SERVICES } from "@/lib/api/client";

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    const { username, password, totp_code } = body;

    if (!username || !password) {
      return NextResponse.json(
        { detail: "Username and password are required" },
        { status: 400 }
      );
    }

    const authRes = await fetch(`${SERVICES.auth}/api/v1/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password, totp_code }),
    });

    if (!authRes.ok) {
      const err = await authRes.json().catch(() => ({ detail: "Login failed" }));
      return NextResponse.json(err, { status: authRes.status });
    }

    const tokens = await authRes.json();
    await setSessionCookies(
      tokens.access_token,
      tokens.refresh_token,
      tokens.expires_in ?? 900
    );

    // Fetch user profile
    const profileRes = await fetch(`${SERVICES.auth}/api/v1/auth/me`, {
      headers: { Authorization: `Bearer ${tokens.access_token}` },
    });
    const user = profileRes.ok ? await profileRes.json() : null;

    return NextResponse.json({ success: true, user });
  } catch (err) {
    console.error("Login error:", err);
    return NextResponse.json({ detail: "Internal error" }, { status: 500 });
  }
}
