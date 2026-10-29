import assert from "node:assert/strict";
import test from "node:test";
import worker from "./worker.js";

test("API paths fail closed without a deployed backend", async () => {
  for (const path of ["/api", "/api/health", "/api/v1/predictions"]) {
    const request = new Request("https://example.test" + path);
    const response = await worker.fetch(request, {
      ASSETS: {
        fetch: () => {
          throw new Error("assets must not handle API");
        },
      },
    });
    assert.equal(response.status, 503);
    assert.match(response.headers.get("content-type"), /application\/json/);
    assert.equal(response.headers.get("cache-control"), "no-store");
    assert.deepEqual(await response.json(), {
      status: "unavailable",
      reason: "backend_not_deployed",
    });
  }
});

test("non-API paths are served from versioned static assets", async () => {
  const request = new Request("https://example.test/assets/index.js");
  let forwarded = false;
  const response = await worker.fetch(request, {
    ASSETS: {
      fetch: async (incoming) => {
        assert.equal(incoming, request);
        forwarded = true;
        return new Response("asset", { status: 200 });
      },
    },
  });
  assert.equal(await response.text(), "asset");
  assert.equal(forwarded, true);
});
