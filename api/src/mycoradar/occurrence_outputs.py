"""Only admitted capabilities enter API payloads, tile inputs, exports, logs or URL paths."""

import csv
import io
import json
import zipfile
from dataclasses import asdict
from datetime import datetime

from mycoradar.occurrence_privacy import (
    PrivacyPolicy,
    PublicPublication,
    check_publication,
)


def _metadata(publication: PublicPublication) -> list[dict[str, object]]:
    licenses = {
        "CC0-1.0": "https://creativecommons.org/publicdomain/zero/1.0/",
        "CC-BY-4.0": "https://creativecommons.org/licenses/by/4.0/",
        "Etalab-2.0": "https://github.com/etalab/licence-ouverte/blob/master/LO.md",
    }
    return [
        {
            **source.model_dump(
                mode="json", exclude={"public_distribution_authorized", "minimum_uncertainty_m"}
            ),
            "license_url": licenses[source.license],
        }
        for source in publication.sources
    ]


def api_payload(
    publication: PublicPublication, policy: PrivacyPolicy, *, now: datetime | None = None
) -> dict[str, object]:
    check_publication(publication, policy, now=now)
    items = []
    for record in publication.records:
        item = asdict(record)
        item["event_date"] = record.event_date.isoformat() if record.event_date else None
        items.append(item)
    return {
        "status": "partial" if items else "unavailable",
        "reason": "public_occurrences_are_not_complete_coverage"
        if items
        else "no_releasable_records",
        "policy_version": publication.policy_version,
        "policy_expires_at": publication.expires_at.isoformat() if publication.expires_at else None,
        "items": items,
        "sources": _metadata(publication),
    }


def tile_geojson(
    publication: PublicPublication, policy: PrivacyPolicy, *, now: datetime | None = None
) -> dict[str, object]:
    # Input to a future tile compiler, not a tile server or a new HTTP endpoint.
    payload = api_payload(publication, policy, now=now)
    features = []
    for record in publication.records:
        properties = asdict(record)
        del properties["longitude"], properties["latitude"]
        properties["event_date"] = record.event_date.isoformat() if record.event_date else None
        features.append(
            {
                "type": "Feature",
                "id": record.id,
                "properties": properties,
                "geometry": {"type": "Point", "coordinates": [record.longitude, record.latitude]},
            }
        )
    return {
        "type": "FeatureCollection",
        "features": features,
        "status": payload["status"],
        "sources": payload["sources"],
        "policy_version": payload["policy_version"],
        "policy_expires_at": payload["policy_expires_at"],
    }


def export_zip(
    publication: PublicPublication, policy: PrivacyPolicy, *, now: datetime | None = None
) -> bytes:
    metadata = api_payload(publication, policy, now=now)
    content = io.StringIO(newline="")
    fields = [
        "id",
        "source_id",
        "taxon_id",
        "country_code",
        "longitude",
        "latitude",
        "location_uncertainty_m",
        "generalized",
        "event_date",
    ]
    writer = csv.DictWriter(content, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for record in publication.records:
        writer.writerow(asdict(record))
    metadata.pop("items")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, value in (
            ("occurrences.csv", content.getvalue()),
            ("metadata.json", json.dumps(metadata, ensure_ascii=False, sort_keys=True)),
        ):
            entry = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            archive.writestr(entry, value)
    return buffer.getvalue()


def public_paths(
    publication: PublicPublication, policy: PrivacyPolicy, *, now: datetime | None = None
) -> tuple[str, ...]:
    check_publication(publication, policy, now=now)
    # Relative references for future occurrence consumers; no route is installed here.
    return tuple(f"/v1/occurrences/{record.id}" for record in publication.records)


def audit_payload(
    publication: PublicPublication, policy: PrivacyPolicy, *, now: datetime | None = None
) -> dict[str, object]:
    check_publication(publication, policy, now=now, audit_only=True)
    return {
        "processed": publication.processed,
        "accepted": len(publication.records),
        "excluded": publication.processed - len(publication.records),
        "reasons": dict(publication.excluded),
    }
