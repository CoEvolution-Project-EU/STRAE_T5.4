# STR Assurance Engine - Architecture

## Architecture

![STRAE Architecture](graphics/strae_arch.png)

## AIMBOM Generation

The AIMBOM generation process is responsible for transforming validated reports into structured AIMBOMs. When a request is made for a specific AI model, STRAE retrieves all relevant reports from the Report Pool and passes them through a report validation stage, where their format, integrity, and completeness are checked. Finally, the engine consolidates these reports, using the AIMBOM Generator, to create the final security report. This process aligns the collected data with trustworthiness, fairness and ethical guidelines (as defined in T1.5 and D1.4 respectively) and ensures that security, robustness, and context-awareness findings are fully represented. The finalized AIMBOM is stored in the Security Assurance Pool and made available to the CoEvolution Hub. This ensures that every assessed AI model is accompanied by a transparent, standardized, and trustworthy record of its development, evaluation, and assurance processes.

### AIMBOM Generation Flow

![AIMBOM Generation Flow](graphics/AIMBOM_Generation.png)

### AIMBOM Deprecation Flow

When a model UUID and version already has an AIMBOM associated with it, STRAE does not generate a new AIMBOM from scratch. Instead, the generation metadata carries a `previous_aimbom` reference alongside the updated reports:

1. If `previous_aimbom` is present in the generation metadata, the generator downloads the previous AIMBOM instead of re-fetching every report.
2. Only the changed reports (currently the assessment report and the risk report) are downloaded and validated.
3. The generator copies the previous AIMBOM, increments its version, and updates the external references that point to the changed report(s). The AIMBOM keeps the same serial number as the previous version, so it is identifiable as an update rather than a new artifact.
4. The updated AIMBOM is re-signed and re-validated against the CycloneDX schema before being stored.
5. If `previous_aimbom` is absent, STRAE falls back to the standard generation flow, retrieving and validating all required reports to build a new AIMBOM.

This allows the CoEvolution Hub to keep a single AIMBOM lineage per model, with each update producing a new version rather than a disconnected artifact.

## System Overview

STRAE is organized as a modular FastAPI application with a clear separation between HTTP entrypoints, background processing, external integrations, and domain services. The API layer accepts generation and signing requests, while a dedicated worker handles asynchronous generation jobs from a message broker. Shared services are responsible for validation, generation, signing, authentication, storage access, and orchestration with external systems.

## Core Components

- API layer: Exposes the public HTTP endpoints and coordinates request validation, business logic, and response formatting.
- AIMBOM Generator: Consolidates validated report payloads into the structured AIMBOM schema used by STRAE and ensures the final artifact follows the expected format.
- Report Gathering: Retrieves report payloads from the orchestrator/storage backend, resolves download URLs, and ensures all required source documents are available before generation.
- Signing: Applies digital signing to reports and generated AIMBOMs as needed, ensuring integrity and provenance for downstream consumers.
- Worker process: Consumes generation tasks from Kafka, decouples asynchronous execution from the API, and retries or skips work based on failure type.

## Request and Processing Flow

1. A client submits a generation request through the API with a model UUID, model version, and generation metadata (a set of report references and, optionally, a reference to a previous AIMBOM for that model).
2. The application downloads the referenced reports (and the previous AIMBOM, if provided) from the configured storage/orchestrator source.
3. Each report is validated for schema compliance, completeness, and integrity before being used in AIMBOM generation.
4. The generator either builds a new AIMBOM from the validated reports, or, if a previous AIMBOM was supplied, produces an updated version of it that reflects the changed reports. The output is signed in both cases.
5. The resulting AIMBOM is stored in the Security Assurance Pool.

## API Endpoints

| Endpoint | Method | Description | Input | Output |
|----------|--------|-------------|-------|--------|
| `/api/status` | GET | Health check endpoint for the STRAE API | - | Health status and version information |
| `/api/sign` | POST | Signs a provided report payload | Report payload (JSON) | Signed report |
| `/api/generate` | POST | Generates an AIMBOM for a given model UUID and version by aggregating reports from the configured storage backend, or produces an updated version of an existing AIMBOM when `previous_aimbom` is provided in the `generation_metadata` | `model_uuid`, `model_version`, `generation_metadata` | Confirmation message, AIMBOM identifier and version |

## Kafka Worker

The Kafka worker enables asynchronous AIMBOM generation by decoupling request submission from processing. It consumes generation tasks from a configured Kafka topic and executes them independently of the API layer.

For each message, the worker validates the payload, retrieves the required reports through the orchestrator integration layer, triggers the AIMBOM generation pipeline, and persists the resulting artifact in the Security Assurance Pool. Successful processing commits the Kafka offset, while recoverable errors can defer commitment to support retry behavior. Invalid or malformed messages are discarded to avoid blocking the queue.

The worker branches on the event's `event` field:

- For a new AIMBOM request, the reports to use are read from the event's `reports` field.
- For an `updated-aimbom-requested` event, an existing AIMBOM should be deprecated/updated instead. The event's `changedReports` contains a reference to the previous AIMBOM (`aimbom_report`) plus the reports that changed; the worker extracts `aimbom_report` as `previous_aimbom` and passes the remaining changed reports to the generator, which produces a new, incremented version of the AIMBOM.

### Kafka Worker Processing Flow
1. Consume message from Kafka topic
2. Validate payload (`model_uuid`, `version`)
3. Determine event type and derive `previous_aimbom`/`reports` from `reports` (new AIMBOM) or `changedReports` (AIMBOM update)
4. Retrieve the required reports (and previous AIMBOM, if any) via the orchestrator API
5. Execute AIMBOM generation or update
6. Store the generated/updated AIMBOM in the security assurance pool
7. Commit Kafka offset on success or controlled failure