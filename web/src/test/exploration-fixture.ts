/** Invented geometry, source and taxon; never a production catalogue. */
import type { Exploration } from "../map/exploration";

export function explorationFixture(
  overrides: Partial<Exploration> = {},
): Exploration {
  return {
    status: "partial",
    catalog_version: "a".repeat(64),
    context_version: "b".repeat(64),
    label: "Pilote synthétique",
    timezone: "Europe/Paris",
    bounds: [5, 43, 6, 44],
    context_bounds: [-12, 33, 20, 53],
    requested_date: "2026-10-30",
    selected_region_id: null,
    selected_taxon_id: null,
    regions: [
      {
        id: "FR-83",
        code: "83",
        name: "Var",
        timezone: "Europe/Paris",
        bounds: [5, 43, 6, 44],
        label_point: [5.5, 43.5],
        source_ids: ["synthetic-source"],
        geometry: {
          type: "Polygon",
          coordinates: [
            [
              [5, 43],
              [6, 43],
              [6, 44],
              [5, 44],
              [5, 43],
            ],
          ],
        },
      },
    ],
    species: [],
    species_state: {
      status: "unavailable",
      reason: "pilot_taxon_not_admitted",
    },
    sources: [
      {
        id: "synthetic-source",
        provider: "Synthetic source",
        product: "Synthetic tests only",
        source_url: "https://example.invalid/synthetic",
        license: "CC0-1.0",
        license_url: "https://creativecommons.org/publicdomain/zero/1.0/",
        version: "synthetic-v1",
        fetched_at: "2026-10-29T00:00:00Z",
        source_published_at: null,
        effective_resolution_m: null,
      },
    ],
    source_age_days: null,
    habitat: {
      status: "unavailable",
      score: null,
      effective_resolution_m: null,
      computed_at: null,
    },
    fruiting: {
      status: "unavailable",
      score: null,
      effective_resolution_m: null,
      computed_at: null,
    },
    ...overrides,
  };
}

export function responseFor(
  input: string | URL | Request,
  species = false,
): Response {
  const query = new URL(String(input), "http://localhost").searchParams;
  return Response.json(
    explorationFixture({
      selected_region_id: query.get("region_id"),
      selected_taxon_id: query.get("taxon_id"),
      requested_date: query.get("valid_at") ?? "2026-10-30",
      ...(species
        ? {
            species: [
              {
                id: "synthetic-taxon",
                scientific_name: "Testus syntheticus",
                source_ids: ["synthetic-source"],
                visibility: "public" as const,
                sensitive: false as const,
              },
            ],
            species_state: {
              status: "partial" as const,
              reason: "synthetic_test_only",
            },
          }
        : {}),
    }),
  );
}
