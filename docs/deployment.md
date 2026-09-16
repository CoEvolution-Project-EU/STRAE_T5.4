# STR Assurance Engine - Deployment

This document describes the steps required to deploy the STRAE container on a Docker host using Portainer/Docker Compose.

## Prerequisites

The deployment requires:

- The docker image pushed to the github registry
- signing-key.pem
- signing-cert.pem

The private key is used to sign AIMBOM reports and must be protected.

## Deploy kafka worker

### 1. Copy signing keys to the server

Create the secrets directory on the deployment server.

Example:

```bash
mkdir -p /home/strae/docker/secrets
```

Copy the signing key and certificate from your machine to the server:

```bash
cd docker/secrets
scp signing-key.pem <server-username>@<server-ip>:/home/strae/docker/secrets/
scp signing-cert.pem <server-username>@<server-ip>:/home/strae/docker/secrets/
```

Verify that the files exist in the server:

```bash
ls -l /home/strae/docker/secrets
```

Expected output:

```text
signing-key.pem
signing-cert.pem
```

Set appropriate permissions in the server:

```bash
chmod 600 /home/strae/docker/secrets/signing-key.pem
chmod 644 /home/strae/docker/secrets/signing-cert.pem
```

The private key should only be readable by the deployment user.

### 2. Deploy the STRAE stack

1. Open Portainer.

2. Navigate to:

```text
Stacks → Add Stack
```

3. Provide the STRAE deployment docker-compose.yml.

```yaml
version: "3.8"

services:
  strae-kafka-worker:
    image: ghcr.io/coevolution-project-eu/strae_t5.4:latest
    container_name: strae-kafka-worker
    environment:
      ENVIRONMENT: "prod"
      KAFKA_TOPIC: ""
      KAFKA_BOOTSTRAP_SERVERS: ""
      KAFKA_GROUP_ID: ""
      
      ORCHESTRATOR_API_BASE_URL: ""
      
      KEYCLOAK_BASE_URL: ""
      KEYCLOAK_REALM: ""
      KEYCLOAK_CLIENT_ID: ""
      ORCHESTRATOR_USERNAME: ""
      ORCHESTRATOR_PASSWORD: ""

      SIGNING_PRIVATE_KEY_PATH: "/run/secrets/signing-key.pem"
      SIGNING_CERTIFICATE_PATH: "/run/secrets/signing-cert.pem"
    command: python -m app.worker
    volumes:
      - /home/strae/docker/secrets:/run/secrets:ro
    restart: unless-stopped
```

4. Ensure the secret volume is configured:

```yaml
volumes:
  - /home/strae/docker/secrets:/run/secrets:ro
```

This mounts the host secrets directory into the container as:

```text
/run/secrets/
├── signing-key.pem
└── signing-cert.pem
```

5. Configure the required environment variables:

```yaml
SIGNING_PRIVATE_KEY_PATH=/run/secrets/signing-key.pem
SIGNING_CERTIFICATE_PATH=/run/secrets/signing-cert.pem
```

Deploy the stack.

## Rotating the signing key/certificate

STRAE reloads the signing key and certificate automatically whenever the files at
`SIGNING_PRIVATE_KEY_PATH`/`SIGNING_CERTIFICATE_PATH` change, so rotation does not
require restarting the API or the Kafka worker.

The key and certificate are reloaded independently, each tracked by its own file's
modification time. If the two files are overwritten one at a time in place, there is
a narrow window where a sign operation could load the new key paired with the old
certificate (or vice versa). STRAE detects this and fails the sign operation with an
error rather than producing an invalid signature, but the window is avoided
entirely by rotating both files atomically:

1. Upload the new files under temporary names, alongside the existing ones:

```bash
cd docker/secrets
scp signing-key.pem <server-username>@<server-ip>:/home/strae/docker/secrets/signing-key.pem.new
scp signing-cert.pem <server-username>@<server-ip>:/home/strae/docker/secrets/signing-cert.pem.new
```

2. Set permissions on the new files:

```bash
chmod 600 /home/strae/docker/secrets/signing-key.pem.new
chmod 644 /home/strae/docker/secrets/signing-cert.pem.new
```

3. Move both into place with a single command, back-to-back with no pause in between:

```bash
mv /home/strae/docker/secrets/signing-key.pem.new /home/strae/docker/secrets/signing-key.pem && \
mv /home/strae/docker/secrets/signing-cert.pem.new /home/strae/docker/secrets/signing-cert.pem
```

`mv` within the same directory is an atomic rename, so each file switches over
instantly with no partially-written content in between -- unlike overwriting an
existing file in place, which a concurrent sign operation could read mid-write.

The new key/certificate are picked up on the next sign operation. No restart or
redeploy of the stack is needed.