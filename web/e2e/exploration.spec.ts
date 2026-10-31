import { expect, test } from "@playwright/test";

test("the real API supplies territory, calendar and provenance without scientific scores", async ({
  page,
}, testInfo) => {
  const initial = page.waitForResponse((response) =>
    response.url().includes("/api/v1/exploration"),
  );
  await page.goto("/");
  const response = await initial;
  expect(response.ok()).toBe(true);
  const publication = await response.json();
  expect(publication.regions.map((r: { id: string }) => r.id)).toEqual([
    "FR-13",
    "FR-83",
    "FR-84",
  ]);
  expect(publication.species).toEqual([]);
  for (const layer of ["habitat", "fruiting"]) {
    expect(publication[layer].status).toBe("unavailable");
    expect(publication[layer].score).toBeNull();
  }
  const explorer = page.locator("[data-api-state]");
  await expect(explorer).toHaveAttribute("data-api-state", "partial");
  await expect(page.getByLabel("Espèce pilote")).toBeDisabled();
  await expect(page.getByLabel("Espèce pilote")).toHaveText(
    "Aucune espèce admise",
  );
  await expect(page.getByText("Calendrier : Europe/Paris")).toBeVisible();
  await page.getByRole("button", { name: "Var 83" }).click();
  await expect(explorer).toHaveAttribute("data-api-state", "partial");
  const dated = page.waitForResponse((r) => {
    const url = new URL(r.url());
    return (
      url.pathname === "/api/v1/exploration" &&
      url.searchParams.get("valid_at") === "2026-10-29" &&
      url.searchParams.get("region_id") === "FR-83"
    );
  });
  await page.getByLabel("Date d’exploration").fill("2026-10-29");
  const datedResponse = await dated;
  const datedPublication = await datedResponse.json();
  expect(datedPublication.requested_date).toBe("2026-10-29");
  expect(datedPublication.selected_region_id).toBe("FR-83");
  expect(datedPublication.catalog_version).toBe(publication.catalog_version);
  await expect(explorer).toHaveAttribute("data-api-state", "partial");
  await page.getByText("Provenance et qualité", { exact: true }).click();
  const quality = page.locator(".confidence-detail");
  await expect(quality).toContainText("Publication API");
  await expect(quality).toContainText("2026-10-29");
  await expect(quality).toContainText("Inconnu");
  await expect(quality).toContainText("Non établie");
  await expect(page.getByText("Indisponible", { exact: true })).toHaveCount(2);
  await expect(page.locator("[data-map-state]")).toHaveAttribute(
    "data-map-state",
    "ready",
    { timeout: 20000 },
  );
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await explorer.screenshot({
    path: testInfo.outputPath("exploration-connected.png"),
    scale: "css",
  });
});

test("loading, unavailable and recovery remain explicit when the API fails", async ({
  page,
}) => {
  let fail = true;
  let release: (() => void) | undefined;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route("**/api/v1/exploration*", async (route) => {
    if (!fail) return route.continue();
    await gate;
    await route.fulfill({
      status: 503,
      contentType: "application/json",
      body: "{}",
    });
  });
  await page.goto("/");
  const explorer = page.locator("[data-api-state]");
  await expect(explorer).toHaveAttribute("data-api-state", "loading");
  await expect(
    page.getByText("Chargement des données du territoire…"),
  ).toBeVisible();
  await expect(page.getByText("Indisponible", { exact: true })).toHaveCount(2);
  release!();
  await expect(explorer).toHaveAttribute("data-api-state", "unavailable");
  await expect(
    page.getByText(/fond local et sources datées accessibles/),
  ).toBeVisible();
  await page.getByRole("button", { name: "Var 83" }).click();
  await expect(page.getByRole("button", { name: "Var 83" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await expect(explorer).toHaveAttribute("data-api-state", "unavailable");
  fail = false;
  await page.getByRole("button", { name: "Recharger les données" }).click();
  await expect(explorer).toHaveAttribute("data-api-state", "partial");
  await page.getByText("Provenance et qualité", { exact: true }).click();
  await expect(page.locator(".confidence-detail")).toContainText(
    "Publication API",
  );
  await expect(page.getByText("Indisponible", { exact: true })).toHaveCount(2);
});
