import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import Explorer from "./Explorer";

vi.mock("./MapView", () => ({
  default: () => <div>Renderer covered by browser tests</div>,
}));

describe("sector exploration", () => {
  it("selects and clears an administrative sector without claiming ecological results", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
    render(<Explorer />);
    const button = screen.getByRole("button", { name: "Var 83" });
    expect(button).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(button);
    expect(button).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("Secteur administratif FR-83.")).toBeVisible();
    expect(screen.getAllByText("Indisponible")).toHaveLength(2);
    fireEvent.click(
      screen.getByRole("button", { name: "Effacer la sélection" }),
    );
    expect(button).toHaveAttribute("aria-pressed", "false");
    expect(
      screen.getByRole("heading", { name: "À vous d’explorer" }),
    ).toBeVisible();
    expect(
      await screen.findByText(/API cartographique indisponible/),
    ).toBeVisible();
  });

  it("retains attribution and distinguishes collection from unknown source dates and resolution", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
    render(<Explorer />);
    expect(screen.getByRole("link", { name: "IGN" })).toBeVisible();
    expect(screen.getByRole("link", { name: "Natural Earth" })).toBeVisible();
    fireEvent.click(
      screen.getByText("Sources, dates et limites cartographiques"),
    );
    expect(screen.getAllByText("Non fournie")).toHaveLength(2);
    const details = screen
      .getByText("Sources, dates et limites cartographiques")
      .closest("details")!;
    expect(within(details).getAllByText("Non établie")).toHaveLength(2);
    expect(
      screen.getByText(/ce n’est pas une résolution de 10 mètres/),
    ).toBeInTheDocument();
    expect(
      await screen.findByText(/API cartographique indisponible/),
    ).toBeVisible();
  });
});
