import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DemoBanner, DEMO_NOTICE } from "./DemoBanner";

describe("DemoBanner", () => {
  it("shows the exact synthetic-data notice", () => {
    render(<DemoBanner />);
    const note = screen.getByRole("note", { name: "Synthetic data notice" });
    expect(note).toHaveTextContent(DEMO_NOTICE);
    expect(DEMO_NOTICE).toBe("DEMO ENVIRONMENT — ALL PATIENTS AND CONVERSATIONS ARE SYNTHETIC.");
  });

  it("offers no control to dismiss it", () => {
    render(<DemoBanner />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});
