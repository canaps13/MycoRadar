import assert from "node:assert/strict";

const target = process.env.MYCORADAR_PREVIEW_URL ??
  "https://mycoradar-preview.valentinlamede13.workers.dev/";

async function read(url) {
  return fetch(url, {
    redirect: "error",
    cache: "no-store",
    signal: AbortSignal.timeout(15000),
  });
}

async function verify() {
  const response = await read(target);
  assert.equal(response.status, 200, "Accueil HTTP 200 attendu");
  const html = await response.text();
  assert.match(html, /<div id="root"><\/div>/, "Entrée React absente");
  assert.match(html, /MycoRadar/i, "Identité MycoRadar absente");
  const assets = Array.from(html.matchAll(/(?:href|src)="(\/assets\/[^"]+)"/g), (m) => m[1]);
  assert.ok(assets.length >= 2, "Fichiers JS/CSS Vite absents");
  for (const asset of assets) {
    const result = await read(new URL(asset, target));
    assert.equal(result.status, 200, "Asset indisponible: " + asset);
    assert.ok((await result.arrayBuffer()).byteLength > 0, "Asset vide: " + asset);
  }
  const api = await read(new URL("/api/health", target));
  assert.equal(api.status, 503, "La preview ne doit pas feindre un backend sain");
  const state = await api.json();
  assert.equal(state.reason, "backend_not_deployed");
}

let success = false;
for (let attempt = 1; attempt <= 8; attempt++) {
  try {
    await verify();
    console.log("Preview vérifiée: " + target + " (tentative " + attempt + ")");
    success = true;
    break;
  } catch (error) {
    console.error("Preview non conforme (tentative " + attempt + "/8): " + error.message);
    if (attempt < 8) await new Promise((resolve) => setTimeout(resolve, 2500));
  }
}
if (!success) process.exitCode = 1;
