# STR Assurance Engine - Status

## Status

Status: In Progress

Last Updated: 20/11/2026

| Feature | Issue | State |
|---------|-------|-------|
| AIMBOM generation | | Complete |
| AIMBOM deprecation (new versions from changed reports) | | Complete |
| Signing (JSF, ES256) | | Complete |
| AIMBOM validation | #25 | Complete |
| Report signing for the Orchestrator (`strae_sign_requests`) | #42 | Complete |
| Signing certificate validity and trust list | #49 | Complete |

## Latest changes (10/11/2026 - 20/11/2026)

### Signing certificate validity and trust list (#49)

- STRAE refuses to sign with an expired or not-yet-valid certificate, or with a key
  that is not in the trust list (`trusted-keys.json`, the public keys STRAE signs or
  has signed with). `/api/sign` and `/api/generate` return `500`, and the worker
  drops the request.
- Verification looks up the signer's key in the trust list. Retired keys stay
  trusted, so documents signed before a key rotation still verify.
- `/api/validation` returns `signed_by_coevolution`: whether the AIMBOM and all its
  reports were signed with a key in the trust list.
- Generation rejects reports and previous AIMBOMs signed by other keys (`422`).
- New rotation script, `app.scripts.rotate_signing_cert`: renews the certificate for
  the same key, or rotates the key and updates the trust list. It writes files
  atomically and keeps backups.
- The example certificate was reissued with a 100-year validity, and the test
  fixtures were re-signed with the example key.

### Deployment

- The stack runs a third container, `strae-cert-renewer`, which renews the signing
  certificate when it expires within 30 days. It replaces a cron job, and doesn't
  need the Docker socket.
- The key, certificate and trust list are prepared locally and copied to the server.
  After that, the server's copy is the one in use.
- The deployment docs describe the stack with the API and the Kafka worker, key
  rotation, and replaying dropped signing requests.

### AIMBOM generation and validation

- The reports and the previous AIMBOM are downloaded concurrently (#62).
- AIMBOM validation fetches the AIMBOM from the Orchestrator's
  `/models/{uuid}/versions/{version}/aimbom` endpoint, which returns the completed
  AIMBOM and the exact reports it was generated from.
- The report models accept the RAGRE tool metadata (`metadata.tools`,
  `metadata.component`, `manufacturer`).
- Duplicate log lines during validation were removed.

### Development

- Development dependencies moved to `requirements-dev.txt`.

## Earlier changes (02/06/2026 - 10/11/2026)

### AIMBOM generation

- A single AIMBOM is generated and uploaded per model version, instead of three tiers.
- AIMBOM deprecation: when a previous AIMBOM is given, STRAE creates a new, incremented
  version of it from the changed reports, instead of generating a new AIMBOM. The
  changed reports must be either the assessment and risk reports, the gadgets report
  alone, or all three.
- The generation API responds with the AIMBOM version.
- The generate endpoint takes the same parameters in the dev and prod environments.
- Report validation is unified, and the generation flow is simplified.

### AIMBOM validation (#25)

`GET /api/validation/{uuid}/{version}` checks the AIMBOM of a model version and the
reports it references.

- The AIMBOM and its reports are fetched from the Orchestrator or from MinIO.
- The AIMBOM and each report are validated against the CycloneDX schema and their
  models, and their signatures are verified.
- The AIMBOM's external references must point at the BOM-Links of exactly its reports.
- Validation stops at the first problem. The response has `status` `VALID` or
  `INVALID`, with the problem in `detail`.
- Report validation moved from the generator to `services/validator.py`, and is shared
  by generation and validation. Generation now also verifies report signatures, and
  rejects invalid reports with `422`.

### Report signing (#42)

Every report uploaded to the CoEvolution Hub is signed by STRAE before it reaches its
final bucket.

- The Kafka worker consumes the `strae_sign_requests` topic, with one consumer per
  topic and consumer group.
- STRAE downloads each file of a signing request, signs it and uploads the signed copy
  with `original_file_id`. Already signed files are skipped.
- `/api/sign` accepts the same signing requests as the Kafka topic, and signing
  requests can contain several files.
- The model UUID and version of `/api/generate` moved into the request body.
- Tested against the Orchestrator: download, signing, upload and the already-signed
  case work.

### Signing

- The signing key and certificate are stored as files in a secrets folder, and are
  reloaded automatically when their files change, so they can be rotated without a
  restart.
- Signatures follow the JSON Signature Format (JSF): `certificatePath` is encoded as
  base64url (unpadded only), and the JSF specification's `ES256` example is verified in
  the tests. The test reports and AIMBOM were re-signed accordingly.
- Errors caused by mismatched signing material are distinguished from errors caused by
  bad payloads.

### Kafka worker

- The worker processes `updated-aimbom-requested` events for AIMBOM deprecation.
- Every Kafka message is committed on its own partition, and failures are logged
  without being retried.
- Malformed payloads are committed and skipped instead of blocking the queue.

### API and security

- `/api/sign` and `/api/generate` require a Keycloak access token, validated locally
  against the realm's public keys (`AUTH_ENABLED`, optional `KEYCLOAK_AUDIENCE`).
  `/api/status` and `/api/validation` stay public, like the Orchestrator's read
  endpoints.
- API error status codes are consistent, and documented in the Swagger definition.
- The rate limiting, concurrency limiting and request size limiting middleware can be
  enabled independently of the environment (`SECURITY_MIDDLEWARE_ENABLED`).
- Fixed the periodic cleanup of client IPs in rate limiting.
- Removed the CORS middleware: STRAE is only called by other services, not from
  browsers.

### Project structure, tests and CI

- Restructured the project, and moved the storage abstraction into the clients.
- Replaced the mock MinIO client with a general mock storage client for tests.
- Added tests for the generator's error paths and AIMBOM building logic, that generated
  AIMBOMs reach storage, and that API errors return the right status codes. Removed
  redundant tests.
- GitHub Actions build the Docker image and push it to the registry, and run the tests
  on pull requests.

### Documentation

- Added deployment docs, and updated the README, architecture and Docker docs and the
  Swagger definition.
