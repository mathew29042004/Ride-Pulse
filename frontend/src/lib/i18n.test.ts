import { describe, expect, it } from "vitest";

import { setLanguage, t } from "./i18n";

describe("t", () => {
  it("translates, fills placeholders and falls back to English", () => {
    setLanguage("en");
    expect(t("Where to?")).toBe("Where to?");
    expect(t("Meet at {place}", { place: "T. Nagar" })).toBe("Meet at T. Nagar");

    setLanguage("ta");
    expect(t("Where to?")).toBe("எங்கே செல்ல வேண்டும்?");
    expect(t("Meet at {place}", { place: "T. Nagar" })).toBe("T. Nagar-ல் சந்திக்கவும்");

    setLanguage("hi");
    expect(t("Book {ride} · {fare}", { ride: "Mini", fare: "₹120" })).toBe("Mini बुक करें · ₹120");
    expect(t("Not translated yet")).toBe("Not translated yet");
    setLanguage("en");
  });
});
