import { act, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import App from "./App";

vi.mock("./map/MapView", () => ({ default: () => <div>Carte</div> }));

describe("MycoRadar bootstrap", () => {
  it("keeps predictions unavailable when the HTTP service is healthy", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          new Response(
            JSON.stringify({ status: "ok", service: "mycoradar-api" }),
          ),
        ),
    );
    render(<App />);
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Service API disponible",
    );
    expect(screen.getByText("Prévisions indisponibles")).toBeVisible();
    expect(screen.getByRole("heading", { name: "Habitat" })).toBeVisible();
    expect(
      screen.getByRole("heading", { name: "Fructification" }),
    ).toBeVisible();
    expect(screen.getByRole("heading", { name: "Confiance" })).toBeVisible();
  });

  it.each([
    ["network error", () => Promise.reject(new Error("offline"))],
    [
      "HTTP error",
      () => Promise.resolve(new Response("error", { status: 503 })),
    ],
    [
      "invalid JSON",
      () => Promise.resolve(new Response("<html>not JSON</html>")),
    ],
    [
      "wrong service",
      () =>
        Promise.resolve(
          new Response(JSON.stringify({ status: "ok", service: "other" })),
        ),
    ],
  ])("reports an unavailable API on %s", async (_label, fetchResult) => {
    vi.stubGlobal("fetch", vi.fn(fetchResult));
    render(<App />);
    expect(await screen.findByText("Service API indisponible")).toBeVisible();
    expect(screen.getByText("Prévisions indisponibles")).toBeVisible();
  });

  it("times out a stalled service", async () => {
    vi.useFakeTimers();
    vi.stubGlobal(
      "fetch",
      vi.fn(
        (_url, options: RequestInit) =>
          new Promise((_resolve, reject) => {
            options.signal?.addEventListener("abort", () =>
              reject(new DOMException("Aborted", "AbortError")),
            );
          }),
      ),
    );
    render(<App />);
    expect(screen.getByRole("status")).toHaveTextContent("Vérification");
    await act(() => vi.advanceTimersByTimeAsync(5000));
    expect(screen.getByRole("status")).toHaveTextContent(
      "Service API indisponible",
    );
  });
});
