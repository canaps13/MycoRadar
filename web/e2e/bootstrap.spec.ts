import { expect, test } from "@playwright/test";

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
