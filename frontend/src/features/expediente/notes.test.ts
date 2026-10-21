import { describe, expect, it } from "vitest";
import { NOTE_MAX, noteDate, withNote } from "./notes";

describe("field notes", () => {
  it("adds a note to the observaciones on its own line, once", () => {
    expect(withNote("", "  Acceso por la quebrada Lobo. ")).toBe("Acceso por la quebrada Lobo.");
    expect(withNote("Vimos humo.\n", "Acceso por la quebrada Lobo.")).toBe("Vimos humo.\nAcceso por la quebrada Lobo.");
    expect(withNote("Vimos humo.\nAcceso por la quebrada Lobo.", "Acceso por la quebrada Lobo.")).toBe(
      "Vimos humo.\nAcceso por la quebrada Lobo.",
    );
    expect(withNote("Vimos humo.", "   ")).toBe("Vimos humo.");
  });

  it("dates a note, and shows nothing for a missing or broken date", () => {
    expect(noteDate("2026-10-16T15:00:00Z")).toBe("16 oct 2026");
    expect(noteDate("")).toBe("");
    expect(noteDate("ayer")).toBe("");
  });

  it("keeps the API limit", () => {
    expect(NOTE_MAX).toBe(500);
  });
});
