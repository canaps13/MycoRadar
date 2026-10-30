import { expect, test } from "@playwright/test";

test("real MapLibre renders, selects polygons, zooms and recenters with local attributed assets", async ({
  page,
}, testInfo) => {
  const external: string[] = [];
  const errors: string[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (
      url.protocol.startsWith("http") &&
      url.origin !== new URL(testInfo.project.use.baseURL!).origin
    )
      external.push(request.url());
  });
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  const map = page.locator("[data-map-state]");
  await expect(map).toHaveAttribute("data-map-state", "ready", {
    timeout: 20000,
  });
  await expect(page.locator("canvas.maplibregl-canvas")).toBeVisible();
  const label = page.locator('[data-sector="FR-83"]');
  await label.scrollIntoViewIfNeeded();
  const rect = await label.boundingBox();
  expect(rect).not.toBeNull();
  await page.mouse.click(rect!.x + rect!.width / 2, rect!.y + rect!.height / 2);
  await expect(page.getByRole("button", { name: "Var 83" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await expect(page.getByText("Secteur administratif FR-83.")).toBeVisible();
  const initialWidth = await page
    .locator('[data-sector="FR-84"]')
    .evaluate((element) => element.getBoundingClientRect().x);
  await page.getByRole("button", { name: "Zoom avant", exact: true }).click();
  await expect
    .poll(async () =>
      page
        .locator('[data-sector="FR-84"]')
        .evaluate((element) => element.getBoundingClientRect().x),
    )
    .not.toBeCloseTo(initialWidth, 0);
  await page.getByRole("button", { name: /Vue d’ensemble/ }).click();
  await expect
    .poll(async () =>
      page
        .locator('[data-sector="FR-84"]')
        .evaluate((element) => element.getBoundingClientRect().x),
    )
    .toBeCloseTo(initialWidth, 0);
  await page.getByRole("button", { name: "Vaucluse 84" }).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByText("Secteur administratif FR-84.")).toBeVisible();
  await expect(
    page.getByRole("link", { name: "IGN", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Natural Earth", exact: true }),
  ).toBeVisible();
  await page.getByText("Sources, dates et limites cartographiques").click();
  await expect(
    page.getByText(/ce n’est pas une résolution de 10 mètres/),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  expect(external).toEqual([]);
  expect(errors).toEqual([]);
  await page.getByText("Sources, dates et limites cartographiques").click();
  await page.locator(".explorer").screenshot({
    path: testInfo.outputPath("map-selected.png"),
    scale: "css",
  });
});

test("a failed map source leaves honest results and usable sector selection, then retries", async ({
  page,
}) => {
  await page.route("**/map/pilot-*.geojson", (route) => route.abort());
  await page.goto("/");
  await expect(
    page.getByText("Carte indisponible", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Var 83" }).click();
  await expect(page.getByText("Secteur administratif FR-83.")).toBeVisible();
  await expect(page.getByText("Indisponible", { exact: true })).toHaveCount(2);
  await page.unroute("**/map/pilot-*.geojson");
  await page.getByRole("button", { name: "Réessayer la carte" }).click();
  await expect(page.locator("[data-map-state]")).toHaveAttribute(
    "data-map-state",
    "ready",
    { timeout: 20000 },
  );
  await expect(page.getByRole("button", { name: "Var 83" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
});

test("absence of WebGL preserves keyboard access to every sector", async ({
  page,
}) => {
  await page.addInitScript(() => {
    const original = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function (
      this: HTMLCanvasElement,
      ...args: Parameters<typeof original>
    ) {
      if (String(args[0]).startsWith("webgl")) return null;
      return original.apply(this, args);
    } as typeof original;
  });
  await page.goto("/");
  await expect(
    page.getByText("Carte indisponible", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Bouches-du-Rhône 13" }).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByText("Secteur administratif FR-13.")).toBeVisible();
  await expect(
    page.getByRole("link", { name: "IGN", exact: true }),
  ).toBeVisible();
});
