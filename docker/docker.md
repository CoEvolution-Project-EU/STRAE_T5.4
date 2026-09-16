# STR Assurance Engine - Docker

## Run with Docker

The application requires Docker Compose to run properly.

### Prerequisites

* Docker
* Docker Compose

## Quickstart

### 1. Clone the repository

```bash
git clone git@github.com:CoEvolution-Project-EU/STRAE_T5.4.git
cd STRAE_T5.4/docker
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env with your preferred settings. 
# Review and update the variables relevant to the profile you intend to run.
```

### 3. Configure signing key

Create a P-256 EC private key:

```bash
cd secrets
openssl ecparam \
  -name prime256v1 \
  -genkey \
  -noout \
  -out signing-key.pem
```

Generate a certificate using that key:

```bash
openssl req \
  -new \
  -x509 \
  -key signing-key.pem \
  -out signing-cert.pem \
  -days 365 \
  -sha256 \
  -subj "/C=GR/O=STRAE/CN=STRAE Signing Certificate"
```

Or copy the existing examples and replace them with your own key and certificate

```bash
cd secrets
cp signing-key.pem.example signing-key.pem
cp signing-cert.pem.example signing-cert.pem
# Edit signing-key.pem and signing-cert.pem with your own key and certificate.
```

### 4. Start the services

This project uses **Docker Compose profiles** to distinguish between different deployment scenarios.

* **`dev` profile**

  * Live code reloading (FastAPI `--reload`)
  * Includes a local **MinIO Server** for storage
  * Includes the **dev router**, enabling endpoints for uploading security reports to MinIO
  * Recommended for local development

* **`prod` profile**

  * No hot reloading
  * Uses an external **MinIO Server** for storage
  * Enables security-focused middleware (rate limiting, concurrency limiting, request size limiting)
  * Suitable for production-like deployments

  > **Enabling/disabling the middleware:** controlled by the
  > `SECURITY_MIDDLEWARE_ENABLED` environment variable (default `true`),
  > independently of the `dev`/`prod` profile. It's set explicitly per
  > service in `docker-compose.yml` (`true` for `api`, `false` for
  > `api-dev`) rather than in `.env`, so change it there to affect a
  > specific profile.
  >
  > **Single-instance assumption:** the rate limiting and concurrency limiting
  > middleware keep their state in the process's own memory. They only
  > enforce the configured limits correctly when exactly **one** API
  > container/replica is running. If the `prod` profile is ever scaled to
  > multiple replicas (e.g. behind a load balancer), each instance enforces
  > its own independent limit, so the effective limit becomes the configured
  > value multiplied by the replica count. Scaling out should either move
  > this enforcement to the reverse proxy in front of the deployment (e.g.
  > nginx `limit_req`/`limit_conn`/upstream `max_conns`) or back the
  > middleware with a shared store (e.g. Redis).

* **`kafka` profile**

  * Runs the background Kafka worker (`app.worker`)
  * Consumes and processes AIMBOM generation messages from configured Kafka topics
  * Can be used alongside the `prod` profile in deployments that require asynchronous processing of AIMBOM generation messages

The `kafka` and `prod` profiles are planned to work with the **CoEvolution Knowledge Base**.

#### Option A: Select profile via `.env` (recommended)

Set the desired profile in your `.env` file:

```env
COMPOSE_PROFILES=dev
```

Then start the services:

```bash
docker compose up --build
```

To switch to production:

```env
COMPOSE_PROFILES=prod
```

```bash
docker compose up --build
```

To run the Kafka worker:

```env
COMPOSE_PROFILES=kafka
```

```bash
docker compose up --build
```

#### Option B: Select profile via command line

Development environment:

```bash
docker compose --profile dev up --build
```

Production API only:

```bash
docker compose --profile prod up --build
```

Kafka worker only:

```bash
docker compose --profile kafka up --build
```

### 5. Dev Profile

#### FastAPI Server

The FastAPI server runs at:

* http://127.0.0.1:8000

Interactive API documentation:

* http://127.0.0.1:8000/docs

#### MinIO Server

The MinIO API endpoint runs at:

* http://127.0.0.1:9000

The MinIO Console (Web UI) is available at:

* http://127.0.0.1:9001

### 6. Prod Profile

#### FastAPI Server

The production API runs without hot reloading and is intended to connect to external infrastructure such as:

* External MinIO storage
* CoEvolution Knowledge Base services

### 7. Kafka Profile

#### Kafka Worker

The Kafka worker runs the background consumer process:

```bash
python -m app.worker
```

Responsibilities include:

* Consuming messages from configured Kafka topics
* Processing incoming security reports
* AIMBOM generation

The worker does not expose any HTTP endpoints and is intended to run alongside the API service when Kafka-based integrations are enabled.

#### Example: Full Deployment

Run both the production API and Kafka worker:

```bash
docker compose --profile prod --profile kafka up --build -d
```

Or via `.env`:

```env
COMPOSE_PROFILES=prod,kafka
```

```bash
docker compose up --build -d
```
