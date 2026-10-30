import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import Explorer from "./Explorer";
import { parseExploration } from "./exploration";
import { explorationFixture, responseFor } from "../test/exploration-fixture";

vi.mock("./MapView", () => ({
  default: () => <div>Real rendering covered in Playwright</div>,
}));

describe("connected explorer", () => {
  it("uses the real query contract and keeps both scientific layers unavailable", async () => {
    const fetcher = vi.fn((input: string) =>
      Promise.resolve(responseFor(input)),
    );
    vi.stubGlobal("fetch", fetcher);
    render(<Explorer />);
    expect(
      screen.getByText("Chargement des données du territoire…"),
    ).toBeVisible();
    expect(await screen.findByText(/Données partielles/)).toBeVisible();
    expect(screen.getByLabelText("Espèce pilote")).toBeDisabled();
    expect(screen.getByLabelText("Date d’exploration")).toHaveValue(
      "2026-10-30",
    );
    fireEvent.click(screen.getByRole("button", { name: "Var 83" }));
    await waitFor(() =>
      expect(fetcher).toHaveBeenLastCalledWith(
        expect.stringContaining("region_id=FR-83"),
        expect.anything(),
      ),
    );
    await screen.findByText(/Données partielles/);
    fireEvent.change(screen.getByLabelText("Date d’exploration"), {
      target: { value: "2026-11-02" },
    });
    await waitFor(() =>
      expect(fetcher).toHaveBeenLastCalledWith(
        expect.stringContaining("valid_at=2026-11-02"),
        expect.anything(),
      ),
    );
    await screen.findByText(/Données partielles/);
    expect(screen.getAllByText("Indisponible")).toHaveLength(2);
    fireEvent.click(screen.getByText("Provenance et qualité"));
    expect(screen.getByText("Publication API")).toBeVisible();
    expect(screen.getByText("Inconnu")).toBeVisible();
  });

  it("supports a single explicitly synthetic admitted taxon without producing a score", async () => {
    const fetcher = vi.fn((input: string) =>
      Promise.resolve(responseFor(input, true)),
    );
    vi.stubGlobal("fetch", fetcher);
    render(<Explorer />);
    await screen.findByText(/Données partielles/);
    expect(screen.getByLabelText("Espèce pilote")).toBeEnabled();
    fireEvent.change(screen.getByLabelText("Espèce pilote"), {
      target: { value: "synthetic-taxon" },
    });
    await waitFor(() =>
      expect(fetcher).toHaveBeenLastCalledWith(
        expect.stringContaining("taxon_id=synthetic-taxon"),
        expect.anything(),
      ),
    );
    await screen.findByText(/Données partielles/);
    expect(screen.getAllByText("Indisponible")).toHaveLength(2);
  });

  it("retries a lost API without pretending the local map is a live scientific result", async () => {
    const fetcher = vi
      .fn()
      .mockRejectedValueOnce(new Error("offline"))
      .mockImplementation((input: string) =>
        Promise.resolve(responseFor(input)),
      );
    vi.stubGlobal("fetch", fetcher);
    render(<Explorer />);
    expect(
      await screen.findByText(/API cartographique indisponible/),
    ).toBeVisible();
    fireEvent.click(
      screen.getByRole("button", { name: "Recharger les données" }),
    );
    expect(await screen.findByText(/Données partielles/)).toBeVisible();
  });

  it("reloads a changed catalogue once", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(new Response("{}", { status: 409 }))
      .mockResolvedValueOnce(Response.json(explorationFixture()));
    vi.stubGlobal("fetch", fetcher);
    render(<Explorer />);
    expect(await screen.findByText(/Données partielles/)).toBeVisible();
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("ignores an older response after changing the selection", async () => {
    let first!: (response: Response) => void;
    const fetcher = vi
      .fn()
      .mockImplementationOnce(
        () =>
          new Promise<Response>((resolve) => {
            first = resolve;
          }),
      )
      .mockImplementation((input: string) =>
        Promise.resolve(responseFor(input)),
      );
    vi.stubGlobal("fetch", fetcher);
    render(<Explorer />);
    fireEvent.click(screen.getByRole("button", { name: "Var 83" }));
    await screen.findByText(/Données partielles/);
    await act(async () =>
      first(Response.json(explorationFixture({ label: "STALE RESPONSE" }))),
    );
    expect(screen.queryByText(/STALE RESPONSE/)).not.toBeInTheDocument();
  });

  it("times out a stalled API", async () => {
    vi.useFakeTimers();
    vi.stubGlobal(
      "fetch",
      vi.fn(
        (_input: unknown, options: RequestInit) =>
          new Promise((_resolve, reject) => {
            options.signal?.addEventListener("abort", () =>
              reject(Error("aborted")),
            );
          }),
      ),
    );
    render(<Explorer />);
    await act(() => vi.advanceTimersByTimeAsync(5000));
    expect(screen.getByText(/API cartographique indisponible/)).toBeVisible();
  });
});

describe("API runtime validation", () => {
  it.each([
    null,
    {},
    { status: "ok" },
    { ...explorationFixture(), habitat: { status: "available", score: 88 } },
    { ...explorationFixture(), catalog_version: "invalid" },
    { ...explorationFixture(), requested_date: "2026-02-30" },
    { ...explorationFixture(), selected_region_id: "missing" },
  ])("rejects incompatible or invented data", (value) => {
    expect(() => parseExploration(value)).toThrow();
  });
  it("keeps geometry and provenance together", () => {
    const result = parseExploration(explorationFixture());
    expect(result.regions[0].source_ids).toContain(result.sources[0].id);
    expect(result.habitat.score).toBeNull();
  });
});
