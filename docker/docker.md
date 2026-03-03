# STR Assurance Engine - Docker

## Run with Docker

The application requires Docker Compose to run properly.

### Prerequisites:
- Docker
- Docker Compose

## Quickstart

### 1. Clone the repository
```bash
git clone git@github.com:CyberAlytics/strae.git
cd strae/docker
```

### 2. Configure environment
```bash
cp .env.example .env
# edit .env with your preferred settings
```

### 3. Start the services

This project uses **Docker Compose profiles** to distinguish between **development** and **production** environments.

- **`dev` profile**  
  - Live code reloading (FastAPI `--reload`)
  - Includes a local **MinIO Server** for storage
  - Includes the **dev router**, enabling endpoints for uploading security reports to **MinIO Server**
  - Recommended for local development

- **`prod` profile**
  - No hot reloading
  - Uses an external **MinIO Server** for storage
  - Enables security-focused middleware
  - Suitable for production-like deployments

The `prod` profile is planned to work with the **CoEvolution Knowledge Base**.

#### Option A: Select profile via `.env` (recommended)

Set the desired profile in your `.env` file:

```env
COMPOSE_PROFILES=dev
```

Then start the services:
```bash
docker compose up --build
```

To switch to production, update the `.env` file:

```env
COMPOSE_PROFILES=prod
```

and restart the services:
```bash
docker compose up --build
```

#### Option B: Select profile via command line

You can explicitly select a profile when starting the services:

```bash
docker compose --profile dev up --build
```

or for production:

```bash
docker compose --profile prod up --build
```

### 4. Dev Profile

#### FastAPI server
The FastAPI server runs at  [http://127.0.0.1:8000](http://127.0.0.1:8000)

You can see the automatic interactive API documentation at [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

#### MinIO server
The MinIO server runs at  [http://127.0.0.1:9000](http://127.0.0.1:9000)

You can access the MinIO Console (WebUI) at [http://127.0.0.1:9001](http://127.0.0.1:9001)

### 5. Prod Profile

(Update this after integration with the CoEvolution Hub)