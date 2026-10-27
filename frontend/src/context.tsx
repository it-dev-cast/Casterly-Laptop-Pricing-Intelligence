import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, getToken, setToken, setUnauthorizedHandler } from "./api";
import type { User } from "./types";

interface AppState {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
  can: (perm: string) => boolean;
  /** Which dataset the UI shows: real evidence, or the synthetic demo dataset. Never mixed. */
  view: "real" | "demo";
  setView: (v: "real" | "demo") => void;
  toast: (msg: string, err?: boolean) => void;
}

const Ctx = createContext<AppState | null>(null);
const VIEW_KEY = "clpi.view";

export function AppProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [view, setViewState] = useState<"real" | "demo">(() => {
    try {
      return localStorage.getItem(VIEW_KEY) === "demo" ? "demo" : "real";
    } catch {
      return "real";
    }
  });
  const [toastMsg, setToastMsg] = useState<{ msg: string; err: boolean } | null>(null);

  const logout = useCallback(() => {
    setToken(null);
    setUser(null);
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(logout);
    if (!getToken()) {
      setLoading(false);
      return;
    }
    api
      .get<User>("/api/auth/me")
      .then(setUser)
      .catch(() => setToken(null))
      .finally(() => setLoading(false));
  }, [logout]);

  const login = async (email: string, password: string) => {
    const r = await api.post<{ access_token: string; user: User }>("/api/auth/login", { email, password });
    setToken(r.access_token);
    setUser(r.user);
  };

  const setView = (v: "real" | "demo") => {
    setViewState(v);
    try {
      localStorage.setItem(VIEW_KEY, v);
    } catch {
      /* per-viewer convenience only */
    }
  };

  const toast = useCallback((msg: string, err = false) => {
    setToastMsg({ msg, err });
    window.setTimeout(() => setToastMsg(null), err ? 6000 : 3500);
  }, []);

  return (
    <Ctx.Provider
      value={{ user, loading, login, logout, can: (p) => !!user?.permissions.includes(p), view, setView, toast }}
    >
      {children}
      {toastMsg && <div className={`toast fade-in ${toastMsg.err ? "err" : ""}`}>{toastMsg.msg}</div>}
    </Ctx.Provider>
  );
}

export function useApp(): AppState {
  const c = useContext(Ctx);
  if (!c) throw new Error("useApp outside provider");
  return c;
}

/** Small data-loading hook with manual reload. */
export function useLoad<T>(fn: () => Promise<T>, deps: unknown[]): { data: T | null; error: string | null; loading: boolean; reload: () => void } {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [n, setN] = useState(0);
  useEffect(() => {
    let alive = true;
    setLoading(true);
    fn()
      .then((d) => alive && (setData(d), setError(null)))
      .catch((e: Error) => alive && setError(e.message))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, n]);
  return { data, error, loading, reload: () => setN((x) => x + 1) };
}
