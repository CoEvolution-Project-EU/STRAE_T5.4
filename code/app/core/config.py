from enum import Enum

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(str, Enum):
    dev = "dev"
    prod = "prod"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_ignore_empty=True,
        extra="ignore",
    )

    # Signing configuration (from .env)
    SIGNING_PRIVATE_KEY_PATH: str = "/run/secrets/signing-key.pem"
    SIGNING_CERTIFICATE_PATH: str = "/run/secrets/signing-cert.pem"

    # Kafka configuration (from .env)
    KAFKA_TOPIC: str = "strae"
    KAFKA_BOOTSTRAP_SERVERS: str = "localhost:9092"
    KAFKA_GROUP_ID: str = "strae"

    ORCHESTRATOR_API_BASE_URL: str = "https://aegis.coevolution-project.eu/api/v1/"

    KEYCLOAK_BASE_URL: str = "https://aegis.coevolution-project.eu/"
    KEYCLOAK_REALM: str = "coevolution"
    KEYCLOAK_CLIENT_ID: str = "strae"
    ORCHESTRATOR_USERNAME: str = "strae-orchestrator"
    ORCHESTRATOR_PASSWORD: str = "strae-orchestrator-password"

    POOL_NAME: str = "SAP"
    BUCKET_NAME: str = "ai-mbom"

    # MinIO configuration (from .env)
    MINIO_ENDPOINT: str = "minio:9000"
    MINIO_ROOT_USER: str = "minioadmin"
    MINIO_ROOT_PASSWORD: str = "minioadmin"
    MINIO_SECURE: bool = False

    # Hardcoded in the docker-compose file, based on docker profile.
    # Default to "dev" when running without docker, for tests.
    ENVIRONMENT: Environment = Environment.dev

    # Enables/disables the rate limiting, concurrency limiting and request
    # size limiting middleware, independently of ENVIRONMENT. Defaults to
    # enabled so it isn't accidentally left off in a production deployment;
    # set to False to disable (e.g. for local development against a
    # non-"dev" profile, or load testing). See docker/docker.md for the
    # single-instance assumption these middleware make.
    SECURITY_MIDDLEWARE_ENABLED: bool = True

    # Logging
    LOG_LEVEL: str = "INFO"

    @field_validator("LOG_LEVEL")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Validate and normalize the `LOG_LEVEL` environment value.

        Args:
            v: The provided log level string.

        Returns:
            Normalized uppercase log level string.

        Raises:
            ValueError: If `v` is not a recognised logging level.
        """

        level = v.upper()
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if level not in valid_levels:
            raise ValueError(f"Invalid LOG_LEVEL: {v}. Must be one of {valid_levels}")
        return level

    # STRAE details
    NAME: str = "Assurance Engine"
    VERSION: str = "1.0.0"
    PROVIDER_NAME: str = "CoEvolution Project"

    # Bucket names for MinIO
    REPORTS_BUCKET: str = "reports"
    AIMBOMS_BUCKET: str = "aimboms"


settings = Settings()
