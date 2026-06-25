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

### 3. Start the services

This project uses **Docker Compose profiles** to distinguish between different deployment scenarios.

* **`dev` profile**

  * Live code reloading (FastAPI `--reload`)
  * Includes a local **MinIO Server** for storage
  * Includes the **dev router**, enabling endpoints for uploading security reports to MinIO
  * Recommended for local development

* **`prod` profile**

  * No hot reloading
  * Uses an external **MinIO Server** for storage
  * Enables security-focused middleware
  * Suitable for production-like deployments

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

### 4. Dev Profile

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

### 5. Prod Profile

#### FastAPI Server

The production API runs without hot reloading and is intended to connect to external infrastructure such as:

* External MinIO storage
* CoEvolution Knowledge Base services

### 6. Kafka Profile

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
