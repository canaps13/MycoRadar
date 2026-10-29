/** Offline display geometry preparation. No ecological calculation or network I/O. */
import { readFile, writeFile, mkdir } from "node:fs/promises";
import { createHash } from "node:crypto";
import { fileURLToPath } from "node:url";
import { resolve } from "node:path";
import { bbox } from "@turf/bbox";
import { bboxClip } from "@turf/bbox-clip";
import { simplify } from "@turf/simplify";
import polylabel from "polylabel";
import { format } from "prettier";
import type { BBox, FeatureCollection, MultiPolygon, Polygon } from "geojson";

const root = fileURLToPath(new URL("../../", import.meta.url));
const manifestPath = "data/map-sources/manifest.json";
const receiptPath = "data/map-sources/output-receipt.json";
const hash = (bytes: string | Uint8Array) =>
  createHash("sha256").update(bytes).digest("hex");
const read = (path: string) => readFile(resolve(root, path));
const manifest = JSON.parse((await read(manifestPath)).toString());
const recipe = [
  manifestPath,
  "web/scripts/prepare-map.ts",
  "web/package-lock.json",
];
const recipeHashes = Object.fromEntries(
  await Promise.all(recipe.map(async (path) => [path, hash(await read(path))])),
);

if (process.argv.includes("--verify")) {
  const receipt = JSON.parse((await read(receiptPath)).toString());
  for (const [path, expected] of Object.entries({
    ...receipt.recipe,
    ...receipt.outputs,
    // The small IGN source is retained; Natural Earth raw bytes are cached offline.
    [manifest.sources[0].path]: manifest.sources[0].sha256,
  })) {
    if (hash(await read(path)) !== expected)
      throw new Error(`Map receipt mismatch: ${path}`);
  }
  if (JSON.stringify(receipt.recipe) !== JSON.stringify(recipeHashes))
    throw new Error("Map recipe changed; regenerate the display assets.");
  console.log(
    "Map receipt verified: recipe, retained source and display assets.",
  );
} else {
  const inputs: FeatureCollection<Polygon | MultiPolygon>[] = [];
  for (const source of manifest.sources) {
    const bytes = await read(source.path);
    if (bytes.length > 20_000_000 || hash(bytes) !== source.sha256)
      throw new Error(`Unexpected source bytes: ${source.id}`);
    inputs.push(JSON.parse(bytes.toString()));
  }
  const [ign, land] = inputs;
  const pilot: FeatureCollection<Polygon | MultiPolygon> = {
    type: "FeatureCollection",
    features: manifest.territories.map(
      (territory: {
        id: string;
        name: string;
        boundary: { value: string };
      }) => {
        const matches = ign.features.filter(
          (f) => f.properties?.code_insee === territory.boundary.value,
        );
        if (matches.length !== 1)
          throw new Error(`Missing sector ${territory.id}`);
        const feature = simplify(matches[0], {
          tolerance: manifest.pilot_tolerance_degrees,
          highQuality: true,
        });
        feature.properties = {
          id: territory.id,
          code: territory.boundary.value,
          name: territory.name,
        };
        delete feature.id;
        delete feature.bbox;
        return feature;
      },
    ),
  };
  const background: FeatureCollection<Polygon | MultiPolygon> = {
    type: "FeatureCollection",
    features: land.features
      .filter((feature) => {
        const b = bbox(feature);
        const c = manifest.context_bounds;
        return b[0] < c[2] && b[2] > c[0] && b[1] < c[3] && b[3] > c[1];
      })
      .map((feature) => {
        const clipped = simplify(
          bboxClip(feature, manifest.context_bounds as BBox),
          { tolerance: manifest.land_tolerance_degrees, highQuality: true },
        );
        if (
          clipped.geometry.type !== "Polygon" &&
          clipped.geometry.type !== "MultiPolygon"
        )
          throw new Error("Expected a polygonal land layer");
        clipped.properties = {};
        delete clipped.bbox;
        delete clipped.id;
        return { ...clipped, geometry: clipped.geometry };
      })
      .filter((f) => f.geometry.coordinates.length > 0),
  };
  const outputs: Record<string, string> = {};
  async function output(path: string, bytes: string) {
    await mkdir(resolve(root, path, ".."), { recursive: true });
    await writeFile(resolve(root, path), bytes);
    outputs[path] = hash(bytes);
  }
  async function geometry(name: string, data: FeatureCollection) {
    const bytes = JSON.stringify(data) + "\n";
    const path = `web/public/map/${name}-${hash(bytes).slice(0, 12)}.geojson`;
    await output(path, bytes);
    return path.replace("web/public", "");
  }
  await output(
    "web/public/maplibre-LICENSE.txt",
    (await read("web/node_modules/maplibre-gl/LICENSE.txt")).toString(),
  );
  const catalog = {
    schema_version: manifest.schema_version,
    label: manifest.pilot_label,
    bounds: bbox(pilot),
    context_bounds: manifest.context_bounds,
    land_url: await geometry("land", background),
    sectors_url: await geometry("pilot", pilot),
    sectors: pilot.features.map((feature) => {
      const polygons =
        feature.geometry.type === "Polygon"
          ? [feature.geometry.coordinates]
          : feature.geometry.coordinates;
      // Largest polygon envelope: label is strictly inside that polygon, including holes.
      const largest = [...polygons].sort((a, b) => {
        const envelopeArea = (rings: number[][][]) => {
          const xs = rings[0].map((p) => p[0]);
          const ys = rings[0].map((p) => p[1]);
          return (
            (Math.max(...xs) - Math.min(...xs)) *
            (Math.max(...ys) - Math.min(...ys))
          );
        };
        return envelopeArea(b) - envelopeArea(a);
      })[0];
      const label = polylabel(
        largest.map((ring) => ring.map((p): [number, number] => [p[0], p[1]])),
        0.0005,
      );
      return {
        ...feature.properties,
        bounds: bbox(feature),
        label_point: [label[0], label[1]],
      };
    }),
    sources: manifest.sources.map((source: Record<string, unknown>) => {
      const { path: _path, ...publicMetadata } = source;
      void _path;
      return publicMetadata;
    }),
  };
  await output(
    "web/src/map/catalog.json",
    await format(JSON.stringify(catalog), { parser: "json" }),
  );
  await writeFile(
    resolve(root, receiptPath),
    JSON.stringify(
      {
        schema_version: "display-map-receipt-v1",
        recipe: recipeHashes,
        outputs,
      },
      null,
      2,
    ) + "\n",
  );
  console.log("Prepared offline map assets:", outputs);
}
