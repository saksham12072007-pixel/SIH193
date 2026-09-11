import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api } from "./api";
import type { InstitutionalUser } from "../types";

interface AuthContextValue {
  user: InstitutionalUser | null;
  token: string | null;
  isLoading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<InstitutionalUser | null>(null);
  const [token, setToken] = useState(() => localStorage.getItem("institutional_access_token"));
  const [isLoading, setIsLoading] = useState(Boolean(token));

  useEffect(() => {
    const expire = () => {
      localStorage.removeItem("institutional_access_token");
      setToken(null);
      setUser(null);
    };
    window.addEventListener("auth:expired", expire);
    if (token) api.get<InstitutionalUser>("/institutional/me").then(setUser).catch(expire).finally(() => setIsLoading(false));
    return () => window.removeEventListener("auth:expired", expire);
  }, [token]);

  const value = useMemo<AuthContextValue>(() => ({
    user,
    token,
    isLoading,
    async login(email, password) {
      const result = await api.post<{ access_token: string }>("/institutional/login", { email, password });
      localStorage.setItem("institutional_access_token", result.access_token);
      setToken(result.access_token);
    },
    logout() {
      localStorage.removeItem("institutional_access_token");
      setToken(null);
      setUser(null);
    },
  }), [user, token, isLoading]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

// The hook shares the provider context and is intentionally exported with the provider.
// eslint-disable-next-line react-refresh/only-export-components
export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used within AuthProvider");
  return context;
}
