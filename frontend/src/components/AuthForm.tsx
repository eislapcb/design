"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";

interface AuthFormProps {
  mode: "login" | "register";
}

const PW_MIN = 15;
const PW_MAX = 64;

/** NIST SP 800-63B: length is the only requirement (no complexity rules). */
function passwordMeter(pw: string): {
  label: string;
  colour: string;
  pct: number;
} {
  if (pw.length === 0) return { label: "", colour: "bg-cream-dark", pct: 0 };
  if (pw.length < PW_MIN)
    return {
      label: "Too short",
      colour: "bg-red-400",
      pct: Math.round((pw.length / PW_MIN) * 50),
    };
  if (pw.length < 20)
    return { label: "Meets minimum", colour: "bg-amber-400", pct: 60 };
  if (pw.length < 30)
    return { label: "Good length", colour: "bg-blue-400", pct: 80 };
  return { label: "Great length", colour: "bg-green-500", pct: 100 };
}

export function AuthForm({ mode }: AuthFormProps) {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const { login, register } = useAuth();
  const router = useRouter();

  const isRegister = mode === "register";
  const meter = passwordMeter(password);

  const validate = (): string | null => {
    if (isRegister && !name.trim()) return "Name is required";
    if (!email.trim()) return "Email is required";
    if (isRegister && password.length < PW_MIN)
      return `Password must be at least ${PW_MIN} characters`;
    if (isRegister && password.length > PW_MAX)
      return `Password must be ${PW_MAX} characters or fewer`;
    if (isRegister && password !== confirmPassword)
      return "Passwords do not match";
    return null;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    const validationError = validate();
    if (validationError) {
      setError(validationError);
      return;
    }

    setLoading(true);
    try {
      if (isRegister) {
        await register(name, email, password);
      } else {
        await login(email, password);
      }
      router.push("/dashboard");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setLoading(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4 w-full max-w-sm">
      {error && (
        <div className="bg-red-50 text-red-700 px-4 py-3 rounded-lg text-sm">
          {error}
        </div>
      )}

      {isRegister && (
        <div>
          <label htmlFor="name" className="block text-sm font-medium mb-1">
            Name
          </label>
          <input
            id="name"
            type="text"
            required
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Your full name"
            className="w-full px-4 py-2 rounded-lg border border-cream-dark bg-white focus:outline-none focus:ring-2 focus:ring-copper"
          />
        </div>
      )}

      <div>
        <label htmlFor="email" className="block text-sm font-medium mb-1">
          Email
        </label>
        <input
          id="email"
          type="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className="w-full px-4 py-2 rounded-lg border border-cream-dark bg-white focus:outline-none focus:ring-2 focus:ring-copper"
        />
      </div>

      <div>
        <label htmlFor="password" className="block text-sm font-medium mb-1">
          Password
          {isRegister && (
            <span className="font-normal text-dark-light">
              {" "}
              — {PW_MIN} to {PW_MAX} characters
            </span>
          )}
        </label>
        <input
          id="password"
          type="password"
          required
          minLength={isRegister ? PW_MIN : 1}
          maxLength={PW_MAX}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="w-full px-4 py-2 rounded-lg border border-cream-dark bg-white focus:outline-none focus:ring-2 focus:ring-copper"
        />
        {isRegister && password.length > 0 && (
          <div className="mt-2">
            <div className="flex items-center gap-2">
              <div className="flex-1 h-1.5 bg-cream-dark rounded-full overflow-hidden">
                <div
                  className={`h-full ${meter.colour} rounded-full transition-all`}
                  style={{ width: `${meter.pct}%` }}
                />
              </div>
              <span className="text-xs text-dark-light w-20">
                {meter.label}
              </span>
            </div>
            {password.length < PW_MIN ? (
              <p className="text-xs text-dark-light mt-1">
                {PW_MIN - password.length} more character
                {PW_MIN - password.length !== 1 ? "s" : ""} needed
              </p>
            ) : (
              <p className="text-xs text-dark-light mt-1">
                {password.length}/{PW_MAX} characters — longer is stronger
              </p>
            )}
          </div>
        )}
      </div>

      {isRegister && (
        <div>
          <label
            htmlFor="confirmPassword"
            className="block text-sm font-medium mb-1"
          >
            Confirm password
          </label>
          <input
            id="confirmPassword"
            type="password"
            required
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            className={`w-full px-4 py-2 rounded-lg border bg-white focus:outline-none focus:ring-2 focus:ring-copper ${
              confirmPassword && confirmPassword !== password
                ? "border-red-400"
                : "border-cream-dark"
            }`}
          />
          {confirmPassword && confirmPassword !== password && (
            <p className="text-xs text-red-500 mt-1">
              Passwords do not match
            </p>
          )}
        </div>
      )}

      <button
        type="submit"
        disabled={loading}
        className="w-full bg-copper hover:bg-copper-light disabled:opacity-50 text-white py-2 rounded-lg font-medium transition-colors"
      >
        {loading
          ? "Please wait..."
          : isRegister
            ? "Create account"
            : "Sign in"}
      </button>
    </form>
  );
}
