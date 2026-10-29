-- Read-only examples, also executed by integration tests on synthetic fixtures.
-- A cell is a grid footprint, not a claim about effective prediction resolution.
SELECT c.id, c.resolution_m, r.id AS region_id, r.country_code
FROM cells c
JOIN cell_regions cr ON cr.cell_id = c.id
JOIN regions r ON r.id = cr.region_id
WHERE c.geometry && ST_MakeEnvelope(-1, -1, 2, 2, 4326)
  AND ST_Intersects(c.geometry, ST_MakeEnvelope(-1, -1, 2, 2, 4326));

-- Explicit visibility filtering is mandatory in future public APIs.
-- This example returns no private observations or geometries.
SELECT o.id, o.event_start, o.event_end, o.location_uncertainty_m,
       v.license, v.license_url, v.attribution, v.source_url, v.fetched_at
FROM occurrences o
JOIN source_versions v ON v.id = o.source_version_id
WHERE o.visibility = 'public' AND v.status = 'validated';

-- Provenance for all recorded run inputs, without inventing a prediction.
SELECT r.id, r.model_version, r.status, v.dataset_id, v.version,
       v.checksum_sha256, v.source_published_at, v.fetched_at
FROM prediction_runs r
JOIN prediction_run_inputs i ON i.run_id = r.id
JOIN source_versions v ON v.id = i.source_version_id;
