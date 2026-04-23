# openapi/generated/

CI-populated Python client types generated from the `deep-analysis-server` OpenAPI spec.

## How this works

The `deep-analysis-server` repo publishes its OpenAPI spec at `openapi/openapi.json`. A CI workflow in this repo (added in Phase 3) fetches that spec and runs an OpenAPI generator to produce typed Python client models here.

**Do not hand-write files in this directory.** Any manually written client types for server models will drift. Regenerate instead.

## Generator

TBD during Phase 3. Candidates:
- `openapi-python-client` (generates Pydantic models + async httpx client)
- `datamodel-code-generator` (generates Pydantic models only; pair with custom httpx layer)

Decision deferred until the server's OpenAPI spec exists.

## Status

Empty — populated by CI. No generated files yet (Phase 1).
