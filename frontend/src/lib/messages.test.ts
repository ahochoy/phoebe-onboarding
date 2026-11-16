import { describe, expect, it } from "vitest";
import { messageFor } from "./messages";

describe("messageFor", () => {
  it("has plain copy for the 503 database codes", () => {
    expect(messageFor("database_unavailable")).toBe(
      "Phoebe's database is waking up. Try again in a few seconds.",
    );
    expect(messageFor("embedder_mismatch")).toBe(
      "Phoebe's document index needs rebuilding. Try again later.",
    );
  });

  it("falls back to generic copy for an unknown code", () => {
    expect(messageFor("no_such_code")).toBe("Something went wrong. Try again in a moment.");
  });
});
