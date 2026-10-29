import assert from "node:assert/strict";

const defaultOrigin = "https://mycoradar-preview.valentinlamede13.workers.dev";
const origin = process.env.MYCORADAR_PREVIEW_URL || defaultOrigin;

async function get(path) {
  return fetch(new URL(path, origin), {
    cache: "no-store",
    redirect: "error",
    signal: AbortSignal.timeout(15000),
  });
}

async function verify() {
  const root = await get("/");
  assert.equal(root.status, 200);
  const html = await root.text();
  assert.ok(html.includes('<div id="root"></div>'));
  assert.match(html, /MycoRadar/i);
  const assets = html.match(/\/assets\/[^"]+/g) || [];
  assert.ok(assets.length >= 2);
  for (const path of assets) {
    const response = await get(path);
    assert.equal(response.status, 200);
    assert.ok((await response.arrayBuffer()).byteLength > 0);
  }
  const api = await get("/api/health");
  assert.equal(api.status, 503);
  const state = await api.json();
  assert.equal(state.reason, "backend_not_deployed");
}

let success = false;
for (let attempt = 0; attempt < 8; attempt++) {
  try {
    await verify();
    success = true;
    console.log("Preview vérifiée: " + origin);
    break;
  } catch (error) {
    console.error(error);
    await new Promise((resolve) => setTimeout(resolve, 2500));
  }
}
if (!success) process.exitCode = 1;
