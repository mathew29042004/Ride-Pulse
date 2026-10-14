/**
 * Phone or desktop layout for the rider and driver apps. Big screens get the desktop layout by
 * default (full-screen map, side panel); anyone can switch to the phone view to see the mobile
 * design, and the choice is remembered on this device.
 */
import { createContext, type ReactNode, useContext, useEffect, useState } from "react";

export type LayoutMode = "phone" | "desktop";
const KEY = "rp.layout";
// Laptops and tablets in landscape get the website layout (a phone is narrower than this).
const WIDE = "(min-width: 768px)";

const LayoutContext = createContext<{ mode: LayoutMode; setMode: (m: LayoutMode) => void }>({ mode: "phone", setMode: () => undefined });

function stored(): LayoutMode | null {
  try {
    const value = localStorage.getItem(KEY);
    return value === "phone" || value === "desktop" ? value : null;
  } catch {
    return null;
  }
}

export function LayoutProvider({ children }: { children: ReactNode }) {
  const [wide, setWide] = useState(() => matchMedia(WIDE).matches);
  const [choice, setChoice] = useState<LayoutMode | null>(stored);
  useEffect(() => {
    const query = matchMedia(WIDE);
    const onChange = () => setWide(query.matches);
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, []);
  // Small screens are always phones; big screens follow the user's choice (desktop by default).
  const mode: LayoutMode = wide ? (choice ?? "desktop") : "phone";
  const setMode = (m: LayoutMode) => {
    setChoice(m);
    try {
      localStorage.setItem(KEY, m);
    } catch {
      /* not remembered */
    }
  };
  return <LayoutContext.Provider value={{ mode, setMode }}>{children}</LayoutContext.Provider>;
}

export function useLayout() {
  return useContext(LayoutContext);
}

/** Space the desktop side panel takes on the left of the map (panel + margins). */
export const DESKTOP_PANEL_PX = 432;
