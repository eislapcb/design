"use client";

import {
  createContext,
  useContext,
  useEffect,
  useState,
  useCallback,
  type ReactNode,
} from "react";
import { apiFetch } from "./api";
import type { User } from "./types";

interface AuthCtx {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (name: string, email: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthCtx>({
  user: null,
  loading: true,
  login: async () => {},
  register: async () => {},
  logout: () => {},
});

interface LoginResponse {
  success: boolean;
  session?: { access_token: string };
  user?: User;
  profile?: { name: string };
  error?: string;
}

interface RegisterResponse {
  success: boolean;
  user?: User;
  error?: string;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = localStorage.getItem("eisla_token");
    if (!token) {
      setLoading(false);
      return;
    }
    apiFetch<{ success: boolean; user: User }>("/api/auth/me")
      .then((data) => setUser(data.user))
      .catch(() => localStorage.removeItem("eisla_token"))
      .finally(() => setLoading(false));
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const data = await apiFetch<LoginResponse>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
    if (!data.success) throw new Error(data.error || "Login failed");
    const token = data.session?.access_token;
    if (!token) throw new Error("No session token returned");
    localStorage.setItem("eisla_token", token);
    setUser(data.user ?? null);
  }, []);

  const register = useCallback(
    async (name: string, email: string, password: string) => {
      const data = await apiFetch<RegisterResponse>("/api/auth/register", {
        method: "POST",
        body: JSON.stringify({ name, email, password }),
      });
      if (!data.success) throw new Error(data.error || "Registration failed");

      // Registration doesn't return a session, so log in immediately
      await login(email, password);
    },
    [login]
  );

  const logout = useCallback(() => {
    const token = localStorage.getItem("eisla_token");
    if (token) {
      apiFetch("/api/auth/logout", { method: "POST" }).catch(() => {});
    }
    localStorage.removeItem("eisla_token");
    setUser(null);
  }, []);

  return (
    <AuthContext.Provider value={{ user, loading, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
