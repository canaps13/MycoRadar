import { test } from "node:test";
import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { mkdtemp, mkdir, readFile, writeFile, rm } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { tmpdir } from "node:os";

const run = promisify(execFile);
const web = new URL("../", import.meta.url);

async function withBundle(check) {
  const folder = await mkdtemp(join(tmpdir(), "mycoradar-map-"));
  try {
    const receipt = JSON.parse(
      await readFile(new URL("map-bundle-receipt.json", web), "utf8"),
    );
    const files = [
      "map-bundle-receipt.json",
      ...Object.keys(receipt.recipe),
      ...Object.keys(receipt.outputs),
    ];
    for (const file of files) {
      const target = join(folder, file);
      await mkdir(dirname(target), { recursive: true });
      await writeFile(target, await readFile(new URL(file, web)));
    }
    await check(folder, receipt);
  } finally {
    // Only remove the specifically created direct child of the temporary directory.
    assert.equal(dirname(resolve(folder)), resolve(tmpdir()));
    assert.match(
      folder.slice(dirname(folder).length + 1),
      /^mycoradar-map-[a-zA-Z0-9]+$/,
    );
    await rm(folder, { recursive: true, force: true });
  }
}

test("the shipped verifier works in an isolated web-only context without repository data", async () => {
  await withBundle(async (folder) => {
    const result = await run(
      process.execPath,
      [join(folder, "scripts/verify-map-bundle.mjs")],
      { cwd: folder },
    );
    assert.match(result.stdout, /Self-contained map bundle verified/);
  });
});

test("a modified geometry in the isolated bundle fails verification", async () => {
  await withBundle(async (folder, receipt) => {
    const geometry = Object.keys(receipt.outputs).find((path) =>
      path.endsWith(".geojson"),
    );
    assert.ok(geometry);
    await writeFile(
      join(folder, geometry),
      '{"type":"FeatureCollection","features":[]}\n',
    );
    await assert.rejects(
      run(process.execPath, [join(folder, "scripts/verify-map-bundle.mjs")], {
        cwd: folder,
      }),
      /Map bundle mismatch/,
    );
  });
});
