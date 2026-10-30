import { expect, test } from "@playwright/test";

test("the geographic API is reachable through the built frontend proxy", async ({
  request,
}) => {
  const response = await request.get("/api/v1/regions?limit=1&country=FR");
  expect(response.status()).toBe(200);
  const page = await response.json();
  expect(page.status).toBe("partial");
  expect(page.pagination.total).toBe(3);
  expect(page.items[0].id).toBe("FR-13");
  const next = await request.get(`/api/v1/regions${page.pagination.next}`);
  expect((await next.json()).items[0].id).toBe("FR-83");
  const missing = await request.get("/api/v1/cells?region_id=FR-83");
  expect((await missing.json()).status).toBe("unavailable");
});

test("the built page reaches the real API without claiming prediction availability", async ({
  page,
}, testInfo) => {
  await page.goto("/");
  await expect(page).toHaveTitle(/MycoRadar/);
  await expect(page.getByRole("status")).toHaveText("Service API disponible");
  await expect(page.getByText("Prévisions indisponibles")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Habitat" })).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Fructification" }),
  ).toBeVisible();
  await expect(page.getByRole("heading", { name: "Confiance" })).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: testInfo.outputPath("home.png"),
    fullPage: true,
    scale: "css",
  });
});

test("the page stays honest and readable if the API is unreachable", async ({
  page,
}) => {
  await page.route("**/api/health", (route) =>
    route.abort("connectionrefused"),
  );
  await page.goto("/");
  await expect(page.getByRole("status")).toHaveText("Service API indisponible");
  await expect(page.getByText("Prévisions indisponibles")).toBeVisible();
});
