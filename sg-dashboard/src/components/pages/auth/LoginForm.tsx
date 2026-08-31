"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Eye, EyeOff, Loader2, ShieldCheck } from "lucide-react";
import toast from "react-hot-toast";

export function LoginForm() {
  const router = useRouter();
  const [form, setForm] = useState({ username: "", password: "", totp_code: "" });
  const [showPass, setShowPass] = useState(false);
  const [needsMfa, setNeedsMfa] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!form.username || !form.password) {
      setError("Username and password are required");
      return;
    }
    setError("");
    setLoading(true);

    try {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(form),
      });

      const data = await res.json();

      if (res.status === 428 || data.detail?.includes("MFA") || data.require_mfa) {
        setNeedsMfa(true);
        setLoading(false);
        return;
      }

      if (!res.ok) {
        setError(data.detail || "Login failed. Check your credentials.");
        setLoading(false);
        return;
      }

      toast.success("Signed in");
      router.replace("/dashboard");
      router.refresh();
    } catch {
      setError("Network error. Check that auth service is running.");
      setLoading(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div>
        <label className="block text-xs text-text-secondary mb-1.5 font-medium">Username</label>
        <input
          type="text"
          autoComplete="username"
          className="input"
          placeholder="your_username"
          value={form.username}
          onChange={(e) => setForm({ ...form, username: e.target.value })}
          disabled={loading}
        />
      </div>

      <div>
        <label className="block text-xs text-text-secondary mb-1.5 font-medium">Password</label>
        <div className="relative">
          <input
            type={showPass ? "text" : "password"}
            autoComplete="current-password"
            className="input pr-10"
            placeholder="••••••••"
            value={form.password}
            onChange={(e) => setForm({ ...form, password: e.target.value })}
            disabled={loading}
          />
          <button
            type="button"
            onClick={() => setShowPass(!showPass)}
            className="absolute right-3 top-1/2 -translate-y-1/2 text-text-muted hover:text-text-secondary"
          >
            {showPass ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
          </button>
        </div>
      </div>

      {needsMfa && (
        <div className="animate-fade-in">
          <label className="block text-xs text-text-secondary mb-1.5 font-medium flex items-center gap-1.5">
            <ShieldCheck className="w-3.5 h-3.5 text-accent" />
            Authenticator Code
          </label>
          <input
            type="text"
            inputMode="numeric"
            pattern="[0-9]*"
            maxLength={6}
            autoComplete="one-time-code"
            className="input font-mono tracking-[0.5em] text-center text-lg"
            placeholder="000000"
            value={form.totp_code}
            onChange={(e) => setForm({ ...form, totp_code: e.target.value })}
            autoFocus
            disabled={loading}
          />
          <p className="text-2xs text-text-muted mt-1.5">
            Enter the 6-digit code from your authenticator app
          </p>
        </div>
      )}

      {error && (
        <div className="text-xs text-bear bg-bear/10 border border-bear/20 rounded px-3 py-2 animate-fade-in">
          {error}
        </div>
      )}

      <button
        type="submit"
        disabled={loading}
        className="w-full btn-primary py-2.5 text-sm font-semibold"
      >
        {loading ? (
          <span className="flex items-center justify-center gap-2">
            <Loader2 className="w-4 h-4 animate-spin" />
            Signing in…
          </span>
        ) : needsMfa ? (
          "Verify & Sign In"
        ) : (
          "Sign In"
        )}
      </button>
    </form>
  );
}
