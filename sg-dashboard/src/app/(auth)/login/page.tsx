import { LoginForm } from "@/components/pages/auth/LoginForm";
import { TrendingUp } from "lucide-react";

export default function LoginPage() {
  return (
    <div className="min-h-screen bg-background flex items-center justify-center p-4 bg-grid-pattern bg-grid-sm">
      {/* Glow */}
      <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
        <div className="w-96 h-96 bg-accent/5 rounded-full blur-3xl" />
      </div>

      <div className="relative w-full max-w-sm">
        {/* Logo */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-12 h-12 rounded-xl bg-accent mb-4 shadow-glow-accent">
            <TrendingUp className="w-6 h-6 text-text-inverse" />
          </div>
          <h1 className="text-2xl font-bold text-text-primary tracking-tight">SG Trading</h1>
          <p className="text-sm text-text-muted mt-1">NSE/BSE Algorithmic Platform</p>
        </div>

        {/* Form card */}
        <div className="card border-border-strong shadow-card">
          <div className="p-6">
            <LoginForm />
          </div>
        </div>

        <p className="text-center text-2xs text-text-muted mt-6">
          Personal deployment · All sessions are audited
        </p>
      </div>
    </div>
  );
}
