import { cookies } from "next/headers";
import { jwtVerify, importSPKI, type JWTPayload } from "jose";
import type { Session, User } from "@/types";

const SESSION_COOKIE = "sg_session";
const ACCESS_COOKIE = "sg_access";

// ─── Cookie helpers ─────────────────────────────────────────────────────────

export async function getAccessToken(): Promise<string | null> {
  const store = await cookies();
  return store.get(ACCESS_COOKIE)?.value ?? null;
}

export async function setSessionCookies(
  accessToken: string,
  refreshToken: string,
  expiresIn: number
): Promise<void> {
  const store = await cookies();
  const expiresAt = Date.now() + expiresIn * 1000;

  store.set(ACCESS_COOKIE, accessToken, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    maxAge: expiresIn,
    path: "/",
  });

  store.set(SESSION_COOKIE, refreshToken, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    maxAge: 60 * 60 * 24 * 7, // 7 days for refresh token
    path: "/",
  });
}

export async function clearSessionCookies(): Promise<void> {
  const store = await cookies();
  store.delete(ACCESS_COOKIE);
  store.delete(SESSION_COOKIE);
}

export async function getRefreshToken(): Promise<string | null> {
  const store = await cookies();
  return store.get(SESSION_COOKIE)?.value ?? null;
}

// ─── JWT verification ────────────────────────────────────────────────────────

let cachedPublicKey: Parameters<typeof importSPKI>[0] | null = null;

async function getPublicKey() {
  if (cachedPublicKey) return cachedPublicKey;

  const envKey = process.env.JWT_PUBLIC_KEY;
  if (envKey && envKey.trim()) {
    cachedPublicKey = await importSPKI(envKey.replace(/\\n/g, "\n"), "RS256");
    return cachedPublicKey;
  }

  // Auto-fetch from auth_service
  const authUrl = process.env.AUTH_SERVICE_URL || "http://localhost:8001";
  const res = await fetch(`${authUrl}/api/v1/auth/public-key`, {
    next: { revalidate: 3600 },
  });
  if (!res.ok) throw new Error("Failed to fetch JWT public key");
  const { public_key } = await res.json();
  cachedPublicKey = await importSPKI(public_key, "RS256");
  return cachedPublicKey;
}

export async function verifyToken(token: string): Promise<JWTPayload | null> {
  try {
    const key = await getPublicKey();
    const { payload } = await jwtVerify(token, key, { algorithms: ["RS256"] });
    return payload;
  } catch (err) {
    console.error("verifyToken error:", err);
    return null;
  }
}

// ─── Get current session (server components) ─────────────────────────────────

export async function getSession(): Promise<Session | null> {
  const token = await getAccessToken();
  if (!token) return null;

  const payload = await verifyToken(token);
  if (!payload) return null;

  const expiresAt = (payload.exp ?? 0) * 1000;
  if (Date.now() >= expiresAt) return null;

  const user: User = {
    user_id: payload.sub ?? "",
    username: (payload["username"] as string) || (payload["email"] as string)?.split("@")[0] || "admin",
    email: (payload["email"] as string) || "admin@sg-trading.com",
    roles: (payload["roles"] as string[]) ?? ["admin"],
    mfa_enabled: (payload["mfa_enabled"] as boolean) ?? false,
  };

  return { user, access_token: token, expires_at: expiresAt };
}

// ─── Role helpers ────────────────────────────────────────────────────────────

export function hasRole(user: User, role: string): boolean {
  return user.roles.includes(role) || user.roles.includes("admin");
}

export function isAdmin(user: User): boolean {
  return user.roles.includes("admin");
}

export function isMlEngineer(user: User): boolean {
  return hasRole(user, "ml_engineer");
}

export function isRiskOfficer(user: User): boolean {
  return hasRole(user, "risk_officer");
}
