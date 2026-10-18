import { describe, expect, it } from "vitest";
import { addDays, daysBetween, makeWindow, nearestDays, shortDay } from "./days";
import { escapeHtml } from "./format";
import { safeNext } from "./safeNext";
import { sessionExpiresAt } from "./session";

const B62 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz";
const b62 = (n: number) => {
  let s = "";
  do {
    s = B62[n % 62] + s;
    n = Math.floor(n / 62);
  } while (n > 0);
  return s;
};
const b64url = (o: unknown) => btoa(JSON.stringify(o)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
/** A Django TimestampSigner style token: "<base64 json>:<base62 seconds>:<sig>". */
const token = (payload: unknown, seconds: number) => `${b64url(payload)}:${b62(seconds)}:sig`;

describe("days", () => {
  it("moves days across months and years", () => {
    expect(addDays("2026-10-01", -1)).toBe("2026-09-30");
    expect(addDays("2026-12-31", 1)).toBe("2027-01-01");
    expect(daysBetween("2026-10-16", "2026-10-18")).toBe(2);
  });

  it("makes the 3 day window ending today", () => {
    const w = makeWindow("2026-10-18", "2026-10-18");
    expect(w).toMatchObject({ from: "2026-10-16", to: "2026-10-18", isToday: true });
    expect(w.words).toBe("últimos 3 días (16 al 18 de octubre de 2026)");
    expect(w.chip).toBe("Últimos 3 días: 16 al 18 oct 2026");
    expect(w.title).toBe("Solo se muestran los últimos 3 días");
    expect(w.range).toBe("16 al 18 de octubre de 2026");
  });

  it("names a past window across a month boundary", () => {
    const w = makeWindow("2026-10-02", "2026-10-18");
    expect(w).toMatchObject({ from: "2026-09-30", to: "2026-10-02", isToday: false });
    expect(w.words).toBe("3 días hasta el 2 de octubre de 2026");
    expect(w.chip).toBe("3 días hasta el 2 oct 2026");
    expect(w.title).toBe("Solo se muestran 3 días, hasta el 2 de octubre de 2026");
    expect(makeWindow("2026-10-02", "2026-10-02").words).toBe("últimos 3 días (30 de septiembre al 2 de octubre de 2026)");
  });

  it("writes the year in a range that crosses it", () => {
    expect(makeWindow("2027-01-01", "2027-01-01").chip).toBe("Últimos 3 días: 30 dic 2026 al 1 ene 2027");
    expect(shortDay("2026-09-05")).toBe("5 set");
  });

  it("finds the nearest days with data outside the window, oldest first", () => {
    const w = makeWindow("2026-10-18", "2026-10-18");
    expect(nearestDays(["2026-10-01", "2026-10-14", "2026-10-17", "2026-10-20", "2026-10-25"], w, 2)).toEqual(["2026-10-14", "2026-10-20"]);
    expect(nearestDays(["2026-10-17"], w)).toEqual([]);
  });
});

describe("sessionExpiresAt", () => {
  const signedAt = 1_760_000_000;

  it("gives a WhatsApp code session 30 days", () => {
    expect(sessionExpiresAt(token({ via: "code", m: 1 }, signedAt))).toBe((signedAt + 30 * 86400) * 1000);
  });

  it("gives an alert link session 7 days", () => {
    expect(sessionExpiresAt(token({ via: "link", m: 1 }, signedAt))).toBe((signedAt + 7 * 86400) * 1000);
  });

  it("assumes the longer lifetime when the payload is unreadable", () => {
    expect(sessionExpiresAt(`not json:${b62(signedAt)}:sig`)).toBe((signedAt + 30 * 86400) * 1000);
  });

  it("returns null for a token it cannot read", () => {
    expect(sessionExpiresAt("opaque")).toBeNull();
    expect(sessionExpiresAt("abc:!!:sig")).toBeNull();
  });
});

describe("safeNext", () => {
  it("keeps same site paths", () => {
    expect(safeNext("/panel")).toBe("/panel");
    expect(safeNext("/expediente/abc?x=1")).toBe("/expediente/abc?x=1");
  });

  it("drops other hosts, schemes, backslashes and /entrar loops", () => {
    for (const bad of [null, "", "panel", "//evil.example", "https://evil.example", "/\\evil.example", "/entrar?next=/panel"]) {
      expect(safeNext(bad)).toBeNull();
    }
  });
});

describe("escapeHtml", () => {
  it("escapes the five HTML specials", () => {
    expect(escapeHtml(`<a href="x" title='y'>&</a>`)).toBe("&lt;a href=&quot;x&quot; title=&#39;y&#39;&gt;&amp;&lt;/a&gt;");
  });
});
