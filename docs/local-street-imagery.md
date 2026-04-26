# Local Street Imagery

Local street imagery is a disabled-by-default v1 overlay for imagery owned or controlled by the operator. It does not use Google, Mapillary offline caches, or Panoramax remote APIs.

## Enable

Set these values in the runtime environment for `self-hosted-maps-api`:

```sh
SHM_STREET_IMAGERY_ENABLED=1
SHM_STREET_IMAGERY_ROOT=/var/lib/self-hosted-maps/street-imagery
```

If `SHM_STREET_IMAGERY_ROOT` is omitted, the API uses `${SHM_DATA_ROOT}/street-imagery`. If it is set, it must still resolve under `SHM_DATA_ROOT`. The browser only talks to `/api/street-imagery/...`; it never provides local file paths, URLs, globs, or folder names.

Optional caps:

```sh
SHM_STREET_IMAGERY_MAX_BBOX_AREA=25
SHM_STREET_IMAGERY_MAX_RESULTS=200
SHM_STREET_IMAGERY_MAX_IMAGE_BYTES=20000000
SHM_STREET_IMAGERY_MAX_THUMBNAIL_BYTES=2000000
```

Original files are not served by default. `SHM_STREET_IMAGERY_ALLOW_ORIGINALS=1` exists for controlled deployments, but the safer default is to publish only redacted/public derivatives.

## Index Layout

Version 1 uses a local manifest:

```text
${SHM_STREET_IMAGERY_ROOT}/index.json
${SHM_STREET_IMAGERY_ROOT}/assets/
```

Example:

```json
{
  "schema_version": 1,
  "items": [
    {
      "id": "sequence-001-frame-0001",
      "title": "Main Street",
      "lat": 30.1,
      "lon": -90.2,
      "heading": 180,
      "captured_at": "2026-04-01T12:00:00Z",
      "publish_state": "published",
      "review_state": "approved",
      "redaction_required": true,
      "redaction_state": "redacted",
      "exif_stripped": true,
      "exact_location_allowed": true,
      "attribution": "Local owner",
      "license": { "name": "Owner controlled" },
      "source": { "type": "local", "label": "Operator import" },
      "media": {
        "image": "assets/sequence-001-frame-0001-redacted.jpg",
        "thumbnail": "assets/sequence-001-frame-0001-thumb.jpg",
        "original": "assets/private-originals/sequence-001-frame-0001.jpg"
      }
    }
  ]
}
```

`media.image`, `media.redacted`, and `media.thumbnail` must be relative paths under `SHM_STREET_IMAGERY_ROOT`. Absolute paths, URLs, traversal, symlinks, unsupported MIME types, oversized files, and files whose bytes do not match their image type are rejected.

## Public API

Public endpoints only return publishable records:

- `GET /api/street-imagery/capabilities`
- `GET /api/street-imagery/local/coverage?bbox=minLon,minLat,maxLon,maxLat&limit=200`
- `GET /api/street-imagery/local/items/{itemId}`
- `GET /api/street-imagery/local/items/{itemId}/thumbnail`
- `GET /api/street-imagery/local/items/{itemId}/image`

Records are hidden unless approved or publishable, not private/removed/suppressed, not under active takedown, and redacted when redaction is required. Public JSON returns API media URLs, not filesystem paths.

## Admin Auth

Street imagery admin operations must be owner-authenticated. Unlike older admin map jobs, street imagery admin routes refuse to run unless `SHM_ADMIN_TOKEN` is set and the request includes either `Authorization: Bearer <token>` or `X-SHM-Admin-Token: <token>`.

Current v1 includes `POST /api/admin/street-imagery/reload` as a token-gated validation/reload hook for local operators. Import, redaction, takedown, and publish workflows should build on this stricter owner-auth gate.

## Panoramax

Panoramax is intentionally deferred. If added later, it should be clearly labeled as third-party when remote, remain disabled by default, preserve license/attribution metadata, and avoid silently rehosting third-party imagery unless the operator has rights to do so.
