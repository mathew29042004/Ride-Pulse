import { useQueryClient } from "@tanstack/react-query";
import { createContext, type ReactNode, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { api, tokens } from "./api";
import type { Role, User } from "./types";

interface AuthState {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<User>;
  logout: () => Promise<void>;
  acceptTokens: (data: { access: string; refresh: string; user: User }) => void;
  can: (capability: string) => boolean;
  refreshUser: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const queryClient = useQueryClient();

  const refreshUser = useCallback(async () => {
    tokens.pinToTab();
    if (!tokens.access && !tokens.refresh) {
      setUser(null);
      return;
    }
    try {
      setUser(await api.get<User>("auth/me/"));
    } catch {
      tokens.clear();
      setUser(null);
    }
  }, []);

  useEffect(() => {
    refreshUser().finally(() => setLoading(false));
  }, [refreshUser]);

  const acceptTokens = useCallback(
    (data: { access: string; refresh: string; user: User }) => {
      tokens.set(data.access, data.refresh);
      queryClient.clear();
      setUser(data.user);
    },
    [queryClient],
  );

  const login = useCallback(
    async (email: string, password: string) => {
      const data = await api.post<{ access: string; refresh: string; user: User }>("auth/token/", {
        email,
        password,
      });
      acceptTokens(data);
      return data.user;
    },
    [acceptTokens],
  );

  const logout = useCallback(async () => {
    const refresh = tokens.refresh;
    try {
      if (refresh) await api.post("auth/logout/", { refresh });
    } catch {
      /* the token may already be expired; logging out locally is enough */
    }
    tokens.clear();
    queryClient.clear();
    setUser(null);
  }, [queryClient]);

  const value = useMemo<AuthState>(
    () => ({
      user,
      loading,
      login,
      logout,
      acceptTokens,
      refreshUser,
      can: (capability: string) => !!user?.capabilities.includes(capability),
    }),
    [user, loading, login, logout, acceptTokens, refreshUser],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}

export function homeFor(role: Role): string {
  if (role === "RIDER") return "/ride";
  if (role === "DRIVER") return "/drive";
  if (role === "FLEET_OWNER") return "/fleet";
  return "/ops";
}
