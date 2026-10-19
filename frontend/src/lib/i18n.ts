/**
 * The rider and driver apps in English, Tamil, Hindi, Malayalam, Kannada and Telugu.
 *
 * Strings are keyed by their English text, so `t("Where to?")` reads naturally in the code and
 * anything not translated yet simply shows in English. `{name}` placeholders are filled from the
 * second argument: `t("Meet at {place}", { place })`.
 *
 * Each language lives in `src/locales/<code>.json` and is loaded only when someone picks it, so
 * English users never download the others. Until it arrives, English shows.
 */

import { useSyncExternalStore } from "react";

export type Language = "en" | "ta" | "hi" | "ml" | "kn" | "te";

export const LANGUAGES: { code: Language; label: string }[] = [
  { code: "en", label: "English" },
  { code: "ta", label: "தமிழ்" },
  { code: "hi", label: "हिन्दी" },
  { code: "ml", label: "മലയാളം" },
  { code: "kn", label: "ಕನ್ನಡ" },
  { code: "te", label: "తెలుగు" },
];

const CODES = new Set<string>(LANGUAGES.map((l) => l.code));
const loaders = import.meta.glob<{ default: Record<string, string> }>("../locales/*.json");
let strings: Record<string, string> = {};
let version = 0; // bumps when a language file arrives, so components re-render

const STORAGE_KEY = "rp.lang";

function stored(): Language {
  try {
    const value = localStorage.getItem(STORAGE_KEY);
    if (value && CODES.has(value)) return value as Language;
  } catch {
    /* storage may be unavailable */
  }
  return "en";
}

let current: Language = typeof window === "undefined" ? "en" : stored();
const listeners = new Set<() => void>();

async function load(language: Language) {
  if (language === "en") {
    strings = {};
    return;
  }
  const loader = loaders[`../locales/${language}.json`];
  if (!loader) return;
  const dictionary = (await loader()).default;
  if (current === language) {
    strings = dictionary;
    version += 1;
    listeners.forEach((fn) => fn());
  }
}

if (current !== "en") void load(current);

export function getLanguage(): Language {
  return current;
}

/** Switch language; the returned promise resolves once its strings have loaded. */
export function setLanguage(language: Language): Promise<void> {
  current = language;
  strings = {}; // English until the new language's file arrives
  if (typeof document !== "undefined") document.documentElement.lang = language;
  try {
    localStorage.setItem(STORAGE_KEY, language);
  } catch {
    /* storage may be unavailable */
  }
  listeners.forEach((fn) => fn());
  return load(language);
}

/** Translate into the current language; English (or anything missing) passes through. */
export function t(text: string, vars?: Record<string, string | number>): string {
  const out = (current !== "en" && strings[text]) || text;
  return vars ? out.replace(/\{(\w+)\}/g, (match, key: string) => (key in vars ? String(vars[key]) : match)) : out;
}

function subscribe(fn: () => void) {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}

export function useLanguage(): [Language, (l: Language) => void] {
  useSyncExternalStore(subscribe, () => `${current}#${version}`, () => "en#0");
  return [current, setLanguage];
}

/** Changes when the language or its loaded strings change (the app root remounts on it). */
export function useLanguageKey(): string {
  return useSyncExternalStore(subscribe, () => `${current}#${version}`, () => "en#0");
}

/** `const t = useT()` re-renders the component when the language changes. */
export function useT(): typeof t {
  useLanguage();
  return t;
}
