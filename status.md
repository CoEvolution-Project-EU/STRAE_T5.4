# STR Assurance Engine - Status

## Status

Status: In Progress

Last Updated: 02/11/2026

Comments: AIMBOM generation, AIMBOM deprecation and signing are complete. Report signing for the Orchestrator's `strae_sign_requests` topic is in progress (#42).

## Changes since 02/06/2026

### AIMBOM generation

- A single AIMBOM is generated and uploaded per model version, instead of three tiers.
- AIMBOM deprecation: when a previous AIMBOM is given, STRAE creates a new, incremented version of it from the changed reports, instead of generating a new AIMBOM. The assessment and risk reports are required, and an updated gadgets report is optional.
- The generation API responds with the AIMBOM version.
- The generate endpoint takes the same parameters in the dev and prod environments.
- Report validation is unified, and the generation flow is simplified.

### Signing

- The signing key and certificate are stored as files in a secrets folder.
- Signature encoding is fixed, and signatures are validated against the certificate path in tests.
- The signing key and certificate are reloaded automatically when their files change, so they can be rotated without a restart.
- Errors caused by mismatched signing material are distinguished from errors caused by bad payloads.

### Kafka worker

- The worker processes `updated-aimbom-requested` events for AIMBOM deprecation.
- Malformed payloads are committed and skipped instead of blocking the queue.

### API and security

- The rate limiting, concurrency limiting and request size limiting middleware can be enabled independently of the environment (`SECURITY_MIDDLEWARE_ENABLED`).
- Fixed the periodic cleanup of client IPs in rate limiting.

### Project structure, tests and CI

- Restructured the project, and moved the storage abstraction into the clients.
- Replaced the mock MinIO client with a general mock storage client for tests.
- Added tests for the generator's error paths and AIMBOM building logic.
- GitHub Actions build the Docker image and push it to the registry, and run the tests on pull requests.

### Documentation

- Added deployment docs, and updated the README, architecture and Docker docs and the Swagger definition.

## In progress (#42)

Report signing for the Orchestrator: every report uploaded to the CoEvolution Hub is signed by STRAE before it reaches its final bucket.

- The Kafka worker consumes the `strae_sign_requests` topic, with one consumer per topic and consumer group.
- STRAE downloads each file of a signing request, signs it and uploads the signed copy with `original_file_id`. Already signed files are skipped.
- `/api/sign` accepts the same signing requests as the Kafka topic, and signing requests can contain several files.
- The model UUID and version of `/api/generate` moved into the request body.
- Every Kafka message is committed on its own partition, and failures are logged without being retried.
- Tested against the Orchestrator: download, signing, upload and the already-signed case work.
