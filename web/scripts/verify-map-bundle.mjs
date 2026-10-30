// Self-contained frontend verification, including Docker's web-only build context.
import { readFile } from "node:fs/promises";
import { createHash } from "node:crypto";

const web = new URL("../", import.meta.url);
const receipt = JSON.parse(
  await readFile(new URL("map-bundle-receipt.json", web), "utf8"),
);
if (receipt.schema_version !== "display-map-bundle-v1")
  throw new Error("Unsupported map bundle receipt");
for (const [path, expected] of Object.entries({
  ...receipt.recipe,
  ...receipt.outputs,
})) {
  const bytes = await readFile(new URL(path, web));
  const actual = createHash("sha256").update(bytes).digest("hex");
  if (actual !== expected) throw new Error(`Map bundle mismatch: ${path}`);
}
console.log("Self-contained map bundle verified.");
