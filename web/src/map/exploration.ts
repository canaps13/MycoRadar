import { useEffect, useRef, useState } from "react";
import type { MultiPolygon, Polygon } from "geojson";

export type ExplorerSource = {
  id: string;
  provider: string;
  product: string;
  source_url: string;
  license: string;
  license_url: string;
  version: string;
  fetched_at: string;
  source_published_at: string | null;
  effective_resolution_m: number | null;
};
export type ExplorerRegion = {
  id: string;
  code: string;
  name: string;
  timezone: string;
  geometry: Polygon | MultiPolygon;
  bounds: number[];
  label_point: [number, number];
  source_ids: string[];
};
export type Exploration = {
  status: "partial";
  catalog_version: string;
  context_version: string;
  label: string;
  timezone: string;
  bounds: number[];
  context_bounds: number[];
  requested_date: string;
  selected_region_id: string | null;
  selected_taxon_id: string | null;
  regions: ExplorerRegion[];
  species: {
    id: string;
    scientific_name: string;
    source_ids: string[];
    visibility: "public";
    sensitive: false;
  }[];
  species_state: {
    status: "available" | "partial" | "unavailable";
    reason: string | null;
  };
  sources: ExplorerSource[];
  source_age_days: null;
  habitat: {
    status: "unavailable";
    score: null;
    effective_resolution_m: null;
    computed_at: null;
  };
  fruiting: Exploration["habitat"];
};

function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value))
    throw Error("Invalid object");
  return value as Record<string, unknown>;
}
function text(value: unknown): string {
  if (typeof value !== "string" || !value.length || value.length > 10000)
    throw Error("Invalid text");
  return value;
}
function url(value: unknown): string {
  const parsed = new URL(text(value));
  if (
    !["https:", "http:"].includes(parsed.protocol) ||
    parsed.username ||
    parsed.password
  )
    throw Error("Invalid source link");
  return parsed.href;
}
function point(value: unknown): [number, number] {
  if (
    !Array.isArray(value) ||
    value.length !== 2 ||
    !value.every((n) => typeof n === "number" && Number.isFinite(n)) ||
    Math.abs(value[0]) > 180 ||
    Math.abs(value[1]) > 90
  )
    throw Error("Invalid position");
  return [value[0], value[1]];
}
function box(value: unknown): number[] {
  if (!Array.isArray(value) || value.length !== 4)
    throw Error("Invalid bounds");
  const lower = point(value.slice(0, 2)),
    upper = point(value.slice(2));
  if (lower[0] >= upper[0] || lower[1] >= upper[1])
    throw Error("Invalid bounds order");
  return [...lower, ...upper];
}
function list(value: unknown, maximum = 100): unknown[] {
  if (!Array.isArray(value) || value.length > maximum)
    throw Error("Invalid collection");
  return value;
}
function geometry(value: unknown): Polygon | MultiPolygon {
  const data = record(value);
  const polygons =
    data.type === "Polygon"
      ? [data.coordinates]
      : data.type === "MultiPolygon"
        ? list(data.coordinates, 10000)
        : null;
  if (!polygons?.length) throw Error("Invalid geometry");
  let vertices = 0;
  for (const polygon of polygons)
    for (const ring of list(polygon, 10000)) {
      const coordinates = list(ring, 100000);
      if (coordinates.length < 4) throw Error("Invalid ring");
      for (const coordinate of coordinates) {
        point(coordinate);
        if (++vertices > 100000) throw Error("Geometry budget exceeded");
      }
    }
  return data as unknown as Polygon | MultiPolygon;
}
function layer(value: unknown): Exploration["habitat"] {
  const data = record(value);
  if (
    data.status !== "unavailable" ||
    data.score !== null ||
    data.effective_resolution_m !== null ||
    data.computed_at !== null
  )
    throw Error("Unsupported scientific publication");
  return {
    status: "unavailable",
    score: null,
    effective_resolution_m: null,
    computed_at: null,
  };
}
export function parseExploration(value: unknown): Exploration {
  const data = record(value);
  if (data.status !== "partial" || data.source_age_days !== null)
    throw Error("Unsupported state");
  for (const field of ["catalog_version", "context_version"])
    if (!/^[a-f0-9]{64}$/.test(text(data[field])))
      throw Error("Invalid version");
  const regions = list(data.regions).map((item): ExplorerRegion => {
    const region = record(item);
    return {
      id: text(region.id),
      code: text(region.code),
      name: text(region.name),
      timezone: text(region.timezone),
      bounds: box(region.bounds),
      label_point: point(region.label_point),
      source_ids: list(region.source_ids).map(text),
      geometry: geometry(region.geometry),
    };
  });
  if (
    !regions.length ||
    new Set(regions.map((r) => r.id)).size !== regions.length
  )
    throw Error("Invalid sector identities");
  const sources = list(data.sources).map((item): ExplorerSource => {
    const source = record(item);
    const fetched = text(source.fetched_at);
    if (!Number.isFinite(Date.parse(fetched)))
      throw Error("Invalid collection date");
    const published =
      source.source_published_at === null
        ? null
        : text(source.source_published_at);
    if (published !== null && !Number.isFinite(Date.parse(published)))
      throw Error("Invalid source date");
    const resolution = source.effective_resolution_m;
    if (
      resolution !== null &&
      (typeof resolution !== "number" ||
        !Number.isFinite(resolution) ||
        resolution <= 0)
    )
      throw Error("Invalid resolution");
    return {
      id: text(source.id),
      provider: text(source.provider),
      product: text(source.product),
      source_url: url(source.source_url),
      license_url: url(source.license_url),
      license: text(source.license),
      version: text(source.version),
      fetched_at: fetched,
      source_published_at: published,
      effective_resolution_m: resolution,
    };
  });
  if (
    regions.some((r) =>
      r.source_ids.some((id) => !sources.some((s) => s.id === id)),
    )
  )
    throw Error("Missing provenance");
  const species = list(data.species).map((item) => {
    const s = record(item);
    const references = list(s.source_ids).map(text);
    if (
      s.visibility !== "public" ||
      s.sensitive !== false ||
      !references.length ||
      references.some((id) => !sources.some((source) => source.id === id))
    )
      throw Error("Unadmitted species");
    return {
      id: text(s.id),
      scientific_name: text(s.scientific_name),
      source_ids: references,
      visibility: "public" as const,
      sensitive: false as const,
    };
  });
  const state = record(data.species_state);
  if (
    !["available", "partial", "unavailable"].includes(String(state.status)) ||
    (state.status === "unavailable" && species.length)
  )
    throw Error("Invalid species availability");
  if (!/^\d{4}-\d{2}-\d{2}$/.test(text(data.requested_date)))
    throw Error("Invalid exploration date");
  if (
    !Number.isFinite(Date.parse(String(data.requested_date))) ||
    new Date(String(data.requested_date)).toISOString().slice(0, 10) !==
      data.requested_date
  )
    throw Error("Invalid calendar date");
  const regionId =
    data.selected_region_id === null ? null : text(data.selected_region_id);
  const taxonId =
    data.selected_taxon_id === null ? null : text(data.selected_taxon_id);
  if (
    (regionId && !regions.some((r) => r.id === regionId)) ||
    (taxonId && !species.some((s) => s.id === taxonId))
  )
    throw Error("Invalid selection");
  return {
    status: "partial",
    catalog_version: text(data.catalog_version),
    context_version: text(data.context_version),
    label: text(data.label),
    timezone: text(data.timezone),
    bounds: box(data.bounds),
    context_bounds: box(data.context_bounds),
    requested_date: text(data.requested_date),
    selected_region_id: regionId,
    selected_taxon_id: taxonId,
    regions,
    species,
    sources,
    source_age_days: null,
    species_state: {
      status: state.status as Exploration["species_state"]["status"],
      reason: state.reason === null ? null : text(state.reason),
    },
    habitat: layer(data.habitat),
    fruiting: layer(data.fruiting),
  };
}

export function useExploration(
  region: string | null,
  day: string,
  taxon: string,
) {
  const [view, setView] = useState<Exploration | null>(null);
  const [mapData, setMapData] = useState<Exploration | null>(null);
  const [status, setStatus] = useState<"loading" | "partial" | "unavailable">(
    "loading",
  );
  const [attempt, retry] = useState(0);
  const [initializing, setInitializing] = useState(true);
  const version = useRef<string | null>(null);
  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 5000);
    setStatus("loading");
    setView(null);
    async function load() {
      try {
        const parameters = new URLSearchParams();
        if (region) parameters.set("region_id", region);
        if (day) parameters.set("valid_at", day);
        if (taxon) parameters.set("taxon_id", taxon);
        if (version.current) parameters.set("catalog_version", version.current);
        const request = () =>
          fetch(`/api/v1/exploration?${parameters}`, {
            signal: controller.signal,
            cache: "no-store",
          });
        let response = await request();
        if (response.status === 409) {
          parameters.delete("catalog_version");
          response = await request();
        }
        if (!response.ok) throw Error("Unavailable catalogue");
        const result = parseExploration(await response.json());
        if (
          result.selected_region_id !== region ||
          result.selected_taxon_id !== (taxon || null) ||
          (day && result.requested_date !== day)
        )
          throw Error("Stale query response");
        if (active) {
          version.current = result.catalog_version;
          setMapData((previous) =>
            previous?.catalog_version === result.catalog_version &&
            previous.context_version === result.context_version
              ? previous
              : result,
          );
          setView(result);
          setStatus("partial");
        }
      } catch {
        if (active) setStatus("unavailable");
      } finally {
        clearTimeout(timeout);
        if (active) setInitializing(false);
      }
    }
    void load();
    return () => {
      active = false;
      controller.abort();
      clearTimeout(timeout);
    };
  }, [region, day, taxon, attempt]);
  return {
    view,
    mapData,
    status,
    initializing,
    reload: () => retry((n) => n + 1),
  };
}
