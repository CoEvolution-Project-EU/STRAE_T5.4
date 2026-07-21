# STR Assurance Engine

The Security, Trust, Robustness Assurance Engine (STRAE) serves as the orchestrating element of the CoEvolution Hub with respect to Risk Analysis, Security Assurance, Robustness and context awareness. The purpose of this engine is to ensure the alignment with AI trustworthiness and fairness guidelines and standards reported from T1.5, collect the security reports from the rest of the CoEvolution components and generate based on those reports the AIMBOM for a given assessed/secured/robust AI model.

[![Python](https://img.shields.io/badge/Python-3.12%2B-blue)](https://python.org) 
[![FastAPI](https://img.shields.io/badge/FastAPI-0.116.0-teal)](https://fastapi.tiangolo.com) 
[![Pydantic](https://img.shields.io/badge/Pydantic-2.11.7-orange)](https://pydantic-docs.helpmanual.io) 
[![MinIO](https://img.shields.io/badge/MinIO-7.2.20-red)](https://min.io) 
[![Kafka](https://img.shields.io/badge/Kafka-aiokafka%20%280.14.0%29-purple)](https://github.com/aio-libs/aiokafka) 
[![Docker Compose](https://img.shields.io/badge/Docker%20Compose-latest-blue)](https://docs.docker.com/compose/)
[![HTTPX](https://img.shields.io/badge/HTTPX-0.28.1-lightgrey)](https://www.python-httpx.org) 
[![pytest](https://img.shields.io/badge/pytest-9.0.2-9cf)](https://pytest.org) 

## Key Functionalities

- **Report Signing**: Digitally sign reports and AIMBOM artifacts so downstream consumers can verify integrity and detect unauthorized modifications.

- **AIMBOM Generation**: Collect validated security reports from CoEvolution components and produce a single, standardized AIMBOM for each assessed AI model.

## Project Structure

```text
STRAE_T5.4/
├── code/
│   ├── app/
│   │   ├── main.py                    ← FastAPI application entrypoint
│   │   ├── worker.py                  ← Kafka consumer entrypoint
│   │   ├── clients/
│   │   │   ├── storage_client.py      ← storage client base class
│   │   │   ├── minio_client.py        ← MinIO storage integration
│   │   │   └── orchestrator_client.py ← orchestrator / report retrieval client
│   │   ├── core/
│   │   │   ├── auth.py                ← authentication and authorization helpers
│   │   │   ├── config.py              ← app configuration and settings
│   │   │   ├── logging.py             ← logging configuration
│   │   │   └── middleware.py          ← API middleware
│   │   ├── models/                    ← AIMBOM and request / response schema models
│   │   ├── routers/
│   │   │   ├── api.py                 ← public API routes
│   │   │   └── dev.py                 ← development / debug routes
│   │   ├── services/
│   │   │   ├── generator.py           ← AIMBOM generation logic
│   │   │   ├── signing.py             ← digital signing services
│   │   │   └── validation.py          ← report / AIMBOM schema validation
│   │   └── utils/
│   │       └── utils.py               ← shared helper utilities
│   ├── tests/                         ← tests folder
│   ├── data/                          ← data folder with example reports and AIMBOM
|   ├── requirements.txt               ← app requirements
|   └── tests.md                       ← tests docs
├── docker/
│   ├── secrets/                       ← folder to store signing key and certificate
│   ├── Dockerfile
│   ├── docker-compose.yml
│   └── docker.md                      ← deployment and service setup docs
├── docs/
│   ├── architecture.md                ← system architecture and design docs
│   └── strae_swagger.json             ← API schema / Swagger definition
├── LICENSE
├── README.md
└── status.md                          ← project status / notes
```

## Documentation Links

- [Architecture](docs/architecture.md)
- [Docker / Deployment](docker/docker.md)
- [Tests](code/tests.md)
- [Status](status.md)

## Tech Stack

| Technology | Version | Purpose |
|-----------|---------|---------|
| Python | 3.12+ | Runtime |
| FastAPI | 0.116.0 | HTTP API framework |
| Pydantic | 2.11.7 | Data validation and settings |
| MinIO | 7.2.20 | S3-compatible object storage |
| Kafka / aiokafka | 0.14.0 | Asynchronous message processing |
| HTTPX | 0.28.1 | Async HTTP client |
| pytest | 9.0.2 | Automated testing |

## License

This project is licensed under the terms of the [Apache License 2.0](LICENSE).

## Technical Contact Person

Name: Orestis Tsirakis

Partner: CBRL

E-mail: o.tsirakis@cyberalytics.com
