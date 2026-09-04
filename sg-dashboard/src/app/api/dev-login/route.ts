import { NextResponse } from "next/server";
import { setSessionCookies } from "@/lib/auth/session";
import { SignJWT, importPKCS8 } from "jose";

export async function GET() {
  if (process.env.NODE_ENV === "production") {
    return NextResponse.json({ detail: "Forbidden in production" }, { status: 403 });
  }

  const envKey = process.env.JWT_PRIVATE_KEY;
  if (!envKey) {
    return NextResponse.json({ detail: "JWT_PRIVATE_KEY not set" }, { status: 500 });
  }

  const privateKey = await importPKCS8(envKey.replace(/\\n/g, "\n"), "RS256");

  const token = await new SignJWT({
    sub: "admin-user",
    username: "admin",
    email: "admin@sg-trading.com",
    roles: ["admin", "risk_officer"],
    mfa_enabled: false,
  })
    .setProtectedHeader({ alg: "RS256" })
    .setIssuedAt()
    .setExpirationTime("2h")
    .sign(privateKey);

  await setSessionCookies(token, "dev-refresh-token", 7200);

  return NextResponse.redirect(new URL("/kite-auth", "http://localhost:3000"));
}
