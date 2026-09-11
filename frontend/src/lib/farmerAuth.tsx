import { createContext, useContext, useMemo, useState, type ReactNode } from "react";
import { api, farmerPath } from "./api";
import type { Farmer, FarmerSession } from "../types";

interface FarmerAuthContextValue {
  farmer: Farmer | null;
  session: FarmerSession | null;
  login: (phoneNumber: string, originChannel: "sms" | "ussd") => Promise<void>;
  logout: () => void;
}

const FarmerAuthContext = createContext<FarmerAuthContextValue | undefined>(undefined);
const sessionKey = "farmer_session";

function readSession(): FarmerSession | null {
  try {
    const value = localStorage.getItem(sessionKey);
    return value ? JSON.parse(value) as FarmerSession : null;
  } catch {
    return null;
  }
}

export function FarmerAuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<FarmerSession | null>(readSession);
  const [farmer, setFarmer] = useState<Farmer | null>(null);

  const value = useMemo<FarmerAuthContextValue>(() => ({
    farmer,
    session,
    async login(phoneNumber, originChannel) {
      const nextSession = await api.post<FarmerSession>("/farmers/session", {
        phone_number: phoneNumber,
        origin_channel: originChannel,
      });
      localStorage.setItem(sessionKey, JSON.stringify(nextSession));
      setSession(nextSession);
      const profile = await api.get<Farmer>(farmerPath(`/farmers/${nextSession.farmer_id}`, nextSession.session_token));
      setFarmer(profile);
    },
    logout() {
      localStorage.removeItem(sessionKey);
      setSession(null);
      setFarmer(null);
    },
  }), [farmer, session]);

  return <FarmerAuthContext.Provider value={value}>{children}</FarmerAuthContext.Provider>;
}

// The hook intentionally shares this context with the provider module.
// eslint-disable-next-line react-refresh/only-export-components
export function useFarmerAuth() {
  const context = useContext(FarmerAuthContext);
  if (!context) throw new Error("useFarmerAuth must be used within FarmerAuthProvider");
  return context;
}
