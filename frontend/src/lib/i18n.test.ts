import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { LANGUAGES, setLanguage, t } from "./i18n";

describe("t", () => {
  it("translates, fills placeholders and falls back to English", async () => {
    await setLanguage("en");
    expect(t("Where to?")).toBe("Where to?");
    expect(t("Meet at {place}", { place: "T. Nagar" })).toBe("Meet at T. Nagar");

    await setLanguage("ta");
    expect(t("Where to?")).toBe("எங்கே செல்ல வேண்டும்?");
    expect(t("Meet at {place}", { place: "T. Nagar" })).toBe("T. Nagar-ல் சந்திக்கவும்");

    await setLanguage("hi");
    expect(t("Book {ride} · {fare}", { ride: "Mini", fare: "₹120" })).toBe("Mini बुक करें · ₹120");
    expect(t("A phrase nobody wrote")).toBe("A phrase nobody wrote");

    await setLanguage("ml");
    expect(t("Where to?")).toBe("എങ്ങോട്ട്?");
    await setLanguage("en");
  });
});

// Every literal t("…") in the rider and driver apps (and the screens they share) must exist in every language, with the
// same {placeholders}; otherwise people see English in the middle of their language.
const SKIP = new Set(["Maruti Suzuki", "Swift", "TN 09 AB 1234", "Ride Pulse"]);

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return files(path);
    return /\.tsx?$/.test(name) && !name.endsWith(".test.ts") ? [path] : [];
  });
}

const root = join(__dirname, "..");
const used = new Set<string>();
for (const file of [...files(join(root, "pages/rider")), ...files(join(root, "pages/driver")), ...files(join(root, "pages/shared")), ...files(join(root, "components"))]) {
  for (const match of readFileSync(file, "utf8").matchAll(/\bt\(\s*"((?:[^"\\]|\\.)*)"/g)) {
    const key = JSON.parse(`"${match[1]}"`) as string;
    if (!SKIP.has(key)) used.add(key);
  }
}
// Labels kept as data (ride preferences and accessibility needs) are shown through t() too.
for (const match of readFileSync(join(root, "lib/preferences.ts"), "utf8").matchAll(/(?:label|hint|driverLabel): "([^"]+)"/g)) {
  used.add(match[1]);
}
const placeholders = (text: string) => (text.match(/\{\w+\}/g) ?? []).sort().join();

describe.each(LANGUAGES.filter((l) => l.code !== "en"))("$label", ({ code }) => {
  const dictionary = JSON.parse(readFileSync(join(root, "locales", `${code}.json`), "utf8")) as Record<string, string>;
  it("has every phrase the apps use", () => {
    expect([...used].filter((key) => !(key in dictionary))).toEqual([]);
  });
  it("keeps the placeholders", () => {
    expect(Object.entries(dictionary).filter(([key, value]) => placeholders(key) !== placeholders(value))).toEqual([]);
  });
});
