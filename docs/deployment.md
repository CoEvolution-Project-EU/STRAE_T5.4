# STR Assurance Engine - Deployment

This document describes the steps required to deploy STRAE on a Docker host using a Portainer stack. The stack runs two containers from the same image:

- `strae-api`: the REST API (`/api/sign`, `/api/generate`, `/api/validation`, `/api/status`).
- `strae-kafka-worker`: the Kafka worker, which processes AIMBOM generation and report signing requests.

## Prerequisites

The deployment requires:

- The docker image pushed to the github registry (`ghcr.io/coevolution-project-eu/strae_t5.4:latest`)
- signing-key.pem
- signing-cert.pem
- trusted-keys.json, the trust list (created in step 1 below)
- An Orchestrator account (`ORCHESTRATOR_USERNAME` / `ORCHESTRATOR_PASSWORD`) with the Keycloak realm role `report-signer`. Only this role can upload signed reports to the final report buckets; without it, uploads of signed reports are rejected with `403`.

The private key is used to sign AIMBOMs and reports and must be protected.

## Deploy STRAE

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

Create the trust list, `trusted-keys.json`. It lists the public keys STRAE signs, or
has signed, with, identified by the SHA-256 of the public key. STRAE refuses to sign
with a key that is not in it, and reports documents signed with any other key as
`signed_by_coevolution: false` in `/api/validation`. Create it with the current key
using the rotation script in the STRAE image:

```bash
docker run --rm \
  --user "$(id -u):$(id -g)" \
  -v /home/strae/docker/secrets:/secrets \
  ghcr.io/coevolution-project-eu/strae_t5.4:latest \
  python -m app.scripts.rotate_signing_cert --dir /secrets --init
```

Or by hand, with the fingerprint of the certificate's public key:

```bash
openssl x509 -in /home/strae/docker/secrets/signing-cert.pem -noout -pubkey \
  | openssl pkey -pubin -outform DER | sha256sum | cut -d' ' -f1
```

```json
{
  "keys": [
    {
      "sha256": "<fingerprint>",
      "in_use_from": "<date the key went into use, e.g. 2026-03-01T00:00:00Z>",
      "retired_at": null,
      "note": "Current"
    }
  ]
}
```

```bash
chmod 644 /home/strae/docker/secrets/trusted-keys.json
```

The file is not secret (fingerprints of public keys are public), but keep a master
copy next to the backup of the signing key, and update both together. If it is lost,
signing stops and every past document returns `signed_by_coevolution: false` until it
is restored.

**Before enabling this on an existing deployment**, add the keys of every certificate
that has signed AIMBOMs and reports in storage (`signature.certificatePath[0]`) to the
list, if they are STRAE's. Otherwise existing AIMBOMs return
`signed_by_coevolution: false`, and generating a new version of them fails. Also check
that the certificate in use has not expired (see
[Checking the certificate's expiry date](#checking-the-certificates-expiry-date)):
signing stops as soon as this is deployed if it has.

### 2. Deploy the STRAE stack

1. Open Portainer.

2. Navigate to:

```text
Stacks → Add Stack
```

3. Provide the STRAE deployment docker-compose.yml, filling in the empty values:

```yaml
version: "3.8"

x-common-env: &common-env
  ENVIRONMENT: "prod"
  LOG_LEVEL: "INFO"
  ORCHESTRATOR_API_BASE_URL: ""
  KEYCLOAK_BASE_URL: ""
  KEYCLOAK_REALM: ""
  KEYCLOAK_CLIENT_ID: ""
  ORCHESTRATOR_USERNAME: ${ORCHESTRATOR_USERNAME}
  ORCHESTRATOR_PASSWORD: ${ORCHESTRATOR_PASSWORD}
  SIGNING_PRIVATE_KEY_PATH: "/run/secrets/signing-key.pem"
  SIGNING_CERTIFICATE_PATH: "/run/secrets/signing-cert.pem"
  TRUSTED_KEYS_PATH: "/run/secrets/trusted-keys.json"

services:
  strae-api:
    image: ghcr.io/coevolution-project-eu/strae_t5.4:latest
    container_name: strae-api
    environment:
      <<: *common-env
      SECURITY_MIDDLEWARE_ENABLED: "false"
      AUTH_ENABLED: "true"
    command: fastapi run app/main.py --proxy-headers --port 8000
    ports:
      - "9000:8000"
    volumes:
      - /home/strae/docker/secrets:/run/secrets:ro
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/status')"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 15s
    restart: unless-stopped

  strae-kafka-worker:
    image: ghcr.io/coevolution-project-eu/strae_t5.4:latest
    container_name: strae-kafka-worker
    environment:
      <<: *common-env
      KAFKA_BOOTSTRAP_SERVERS: ""
      KAFKA_TOPIC: ""
      KAFKA_GROUP_ID: ""
      KAFKA_AUTO_OFFSET_RESET: "latest"
      KAFKA_SIGNING_TOPIC: ""
      KAFKA_SIGNING_GROUP_ID: ""
      KAFKA_SIGNING_AUTO_OFFSET_RESET: "latest"
    command: python -m app.worker
    volumes:
      - /home/strae/docker/secrets:/run/secrets:ro
    restart: unless-stopped
```

The settings shared by both services are defined once in `x-common-env` and merged into each service with `<<: *common-env`. Set every value explicitly: a variable left empty falls back to the default in `code/app/core/config.py`.

4. Set the Orchestrator credentials in the stack's **Environment variables** section in Portainer, not in the compose file:

| Variable | Description |
|----------|-------------|
| `ORCHESTRATOR_USERNAME` | Orchestrator account with the `report-signer` realm role |
| `ORCHESTRATOR_PASSWORD` | Password of that account |

Portainer substitutes them for `${ORCHESTRATOR_USERNAME}` and `${ORCHESTRATOR_PASSWORD}` when it deploys the stack.

5. Ensure the secret volume is configured on both services:

```yaml
volumes:
  - /home/strae/docker/secrets:/run/secrets:ro
```

This mounts the host secrets directory into each container as:

```text
/run/secrets/
├── signing-key.pem
├── signing-cert.pem
└── trusted-keys.json
```

Both services sign (the API through `/api/sign` and `/api/generate`, the worker through Kafka requests), so both need the key, the certificate and the trust list. The mount is read-only: STRAE never changes these files, only the operator does.

6. Review the API settings:

| Variable | Description |
|----------|-------------|
| `AUTH_ENABLED` | Require a Keycloak access token on `/api/sign` and `/api/generate` (see [Reverse proxy config](#reverse-proxy-config)) |
| `SECURITY_MIDDLEWARE_ENABLED` | Rate limiting, concurrency limiting and request size limiting middleware (see [docker.md](../docker/docker.md)) |

The API listens on port `8000` in the container, published on port `9000` on the host. The healthcheck calls `/api/status` every 30 seconds.

7. Configure the Kafka topics and consumer groups. The worker runs one consumer per topic:

| Variable | Description |
|----------|-------------|
| `KAFKA_BOOTSTRAP_SERVERS` | Kafka brokers |
| `KAFKA_TOPIC` | Topic of AIMBOM generation requests |
| `KAFKA_GROUP_ID` | Consumer group of the AIMBOM generation consumer |
| `KAFKA_AUTO_OFFSET_RESET` | Where the AIMBOM generation consumer starts when its group has no committed offset (`earliest` or `latest`) |
| `KAFKA_SIGNING_TOPIC` | Topic of report signing requests |
| `KAFKA_SIGNING_GROUP_ID` | Consumer group of the report signing consumer |
| `KAFKA_SIGNING_AUTO_OFFSET_RESET` | Where the report signing consumer starts when its group has no committed offset (`earliest` or `latest`) |

Keep the consumer group names stable between deployments. A new group starts at the end of its topic and skips the requests already in it. See [Architecture](architecture.md#kafka-worker) for when a group has no committed offset.

8. Deploy the stack.

9. Check that both containers are running and that `strae-api` is `healthy`:

```bash
docker ps --filter name=strae
curl http://localhost:9000/api/status
```

### Updating to a new image

The stack uses the `latest` tag. To deploy a new image, open the stack in Portainer and select **Update the stack** with **Re-pull image and redeploy** enabled.

## Reverse proxy config

TODO: describe the reverse proxy configuration.

STRAE has no CORS middleware, since it is only called by other services (the Orchestrator and the SRME) and not from browsers. It is reached through a reverse proxy that runs on a separate VM and terminates HTTPS. The proxy forwards requests to port `9000` of the STRAE VM.

There is no IP allowlist. `/api/sign` and `/api/generate` require a Keycloak access token of the realm set by `KEYCLOAK_BASE_URL` and `KEYCLOAK_REALM` (see [Architecture](architecture.md#api-endpoints)). `/api/status`, `/api/validation` and the API documentation (`/docs`) are public:

| Variable | Default | Description |
|----------|---------|-------------|
| `AUTH_ENABLED` | `true` | Require an access token on `/api/sign` and `/api/generate` |
| `KEYCLOAK_AUDIENCE` | unset | Required `aud` claim of the token. Unset, the audience is not checked. Only set it once the calling clients have an audience mapper for STRAE in Keycloak |

## Replaying dropped signing requests

The worker doesn't retry failed requests. When a request fails for a reason not caused by the request itself (e.g. the Orchestrator is unreachable), the worker logs it as `request dropped` together with the full event.

Signing requests are safe to process again, because already signed files are skipped. Replay them in the same way when signing requests were skipped because the signing group had no committed offset (e.g. on the first deployment, after changing `KAFKA_SIGNING_GROUP_ID`, or after the worker was stopped for longer than the offset retention). To replay them, either ask the Orchestrator team to send the events again, or move the signing consumer group back to the beginning of the topic:

1. Stop the Kafka worker (`strae-kafka-worker`), so the consumer group has no active members.

2. Reset the group's offset:

```bash
kafka-consumer-groups.sh --bootstrap-server <KAFKA_BOOTSTRAP_SERVERS> \
  --group <KAFKA_SIGNING_GROUP_ID> --topic <KAFKA_SIGNING_TOPIC> \
  --reset-offsets --to-earliest --execute
```

3. Start the Kafka worker again. It processes every signing request still in the topic.

Don't do this for the AIMBOM generation group: processing generation requests again creates duplicate AIMBOM versions.

## Rotating the signing key/certificate

STRAE reloads the signing key, the certificate and the trust list automatically
whenever their files change, so rotation does not require restarting the API or the
Kafka worker.

The trust list identifies keys, not certificates:

- **Renewing the certificate** for the same key (e.g. before it expires) does not
  change the trust list. This is routine, and can be scheduled.
- **Rotating the key** adds the new key to the trust list and marks the old one as
  retired. Retired keys stay trusted, so documents signed before the rotation still
  verify. This changes what is trusted, so it is never scheduled.

Both are done with the rotation script, `app.scripts.rotate_signing_cert`, shipped in
the STRAE image. It is run as a one-off container, with the secrets directory mounted
read-write for that run only. Use the image of the running stack, so the script
writes a trust list that the running services can load:

```bash
docker run --rm \
  --user "$(id -u):$(id -g)" \
  -v /home/strae/docker/secrets:/secrets \
  "$(docker inspect --format '{{.Image}}' strae-api)" \
  python -m app.scripts.rotate_signing_cert --dir /secrets [options]
```

| Option | Effect |
|--------|--------|
| *(none)* | Issue a new certificate for the current key. The trust list is not changed. |
| `--new-key` | Generate a new key and a new certificate for it, add the key to the trust list, and mark the old key as retired. |
| `--days N` | Validity of the new certificate, in days. Defaults to 3650. |
| `--if-expiring-within N` | Do nothing unless the current certificate expires within N days. Used by the scheduled renewal. Can't be combined with `--new-key`. |
| `--init` | Create the trust list with the current key, without rotating. |
| `--dry-run` | Print what would change, and write nothing. |

The script:

1. Stops if the key and certificate don't match, or if the current key is not in the
   trust list (the list is out of sync, and must be checked by hand first). An expired
   certificate is not a reason to stop: renewing it is the fix.
2. Generates the new certificate (and key), valid from 5 minutes ago, so a container
   whose clock is slightly behind doesn't reject it.
3. Writes every file as `<name>.new`, then moves them into place with atomic renames:
   the trust list first, so the new key is trusted before it is used, then the key and
   the certificate back to back. Permissions are `600` for the key and `644` for the
   certificate and the trust list.
4. Keeps the replaced files as `<name>.<timestamp>.bak`. It never deletes anything.
5. Prints the old and new certificates and key fingerprints.

If it fails before the renames, nothing in use has changed and the `.new` files are
removed. If it fails between the renames, the key and certificate may not match:
signing then fails with a "Signing material error" (nothing invalid is signed), and
running the script again, or renaming the `.bak` files back, fixes it.

After a key rotation, copy the new trust list and the new key to the backup of the
signing material.

### Checking the certificate's expiry date

```bash
openssl x509 -in /home/strae/docker/secrets/signing-cert.pem -noout -enddate
```

When the certificate expires, STRAE stops signing: `/api/sign` and `/api/generate`
return `500` with "Signing certificate expired on ...", and the worker logs
`Signing material error ... request dropped` with the event. Renew the certificate,
then replay the dropped requests (see
[Replaying dropped signing requests](#replaying-dropped-signing-requests); ask the
Orchestrator team to send dropped generation requests again). Documents signed before
the expiry still verify.

### Scheduled certificate renewal

Renewing the certificate is routine and does not touch the trust list, so it can be
automated with a cron job (or a systemd timer) on the host:

```cron
# Daily: renew the certificate if it expires within 30 days.
0 3 * * * docker run --rm --user 1000:1000 -v /home/strae/docker/secrets:/secrets "$(docker inspect --format '{{.Image}}' strae-api)" python -m app.scripts.rotate_signing_cert --dir /secrets --if-expiring-within 30 >> /var/log/strae-rotate.log 2>&1
```

Replace `1000:1000` with the deployment user's UID and GID. Nothing warns before
expiry if the job stops running, so check the log from time to time.

### Rotating the key and certificate

Rotate the key if it may have been exposed, or to replace it as a precaution:

```bash
docker run --rm \
  --user "$(id -u):$(id -g)" \
  -v /home/strae/docker/secrets:/secrets \
  "$(docker inspect --format '{{.Image}}' strae-api)" \
  python -m app.scripts.rotate_signing_cert --dir /secrets --new-key
```

The new key is generated on the server, so it never travels over the network. Copy
it, and the new trust list, to the backup.

Removing a key from the trust list makes the documents it signed return
`signed_by_coevolution: false`. They still validate. Revoking a key is not supported
yet.

### Manual rotation

The script is the recommended way. Without it, the files can be replaced by hand.

**Renewing only the certificate.** Issue a new certificate for the existing key:

```bash
cd docker/secrets
openssl req \
  -new \
  -x509 \
  -key signing-key.pem \
  -out signing-cert.pem \
  -days 3650 \
  -sha256 \
  -subj "/C=GR/O=STRAE/CN=STRAE Signing Certificate"
```

Then upload it under a temporary name, set its permissions and move it into place:

```bash
scp signing-cert.pem <server-username>@<server-ip>:/home/strae/docker/secrets/signing-cert.pem.new
```

```bash
chmod 644 /home/strae/docker/secrets/signing-cert.pem.new
mv /home/strae/docker/secrets/signing-cert.pem.new /home/strae/docker/secrets/signing-cert.pem
```

Since the key does not change, the new certificate always matches it, it is already in
the trust list, and signing never fails during the switch.

**Rotating the key and certificate.** The key and certificate are reloaded
independently, each tracked by its own file's modification time. If the two files are
overwritten one at a time in place, there is a narrow window where a sign operation
could load the new key paired with the old certificate (or vice versa). STRAE detects
this and fails the sign operation with an error rather than producing an invalid
signature, but the window is avoided by moving both files into place with atomic
renames. In this order:

1. Add the new key to the trust list, **before** the swap, or signing fails in
   between. Get its fingerprint with
   `openssl x509 -in signing-cert.pem -noout -pubkey | openssl pkey -pubin -outform DER | sha256sum`,
   add an entry to a copy of the list, upload it as `trusted-keys.json.new`, and move it
   into place:

```bash
chmod 644 /home/strae/docker/secrets/trusted-keys.json.new
mv /home/strae/docker/secrets/trusted-keys.json.new /home/strae/docker/secrets/trusted-keys.json
```

2. Upload the new key and certificate under temporary names, alongside the existing
   ones:

```bash
cd docker/secrets
scp signing-key.pem <server-username>@<server-ip>:/home/strae/docker/secrets/signing-key.pem.new
scp signing-cert.pem <server-username>@<server-ip>:/home/strae/docker/secrets/signing-cert.pem.new
```

3. Set permissions on the new files:

```bash
chmod 600 /home/strae/docker/secrets/signing-key.pem.new
chmod 644 /home/strae/docker/secrets/signing-cert.pem.new
```

4. Move both into place with a single command, back-to-back with no pause in between:

```bash
mv /home/strae/docker/secrets/signing-key.pem.new /home/strae/docker/secrets/signing-key.pem && \
mv /home/strae/docker/secrets/signing-cert.pem.new /home/strae/docker/secrets/signing-cert.pem
```

5. Set `retired_at` on the old key's entry in the trust list (same `.new` + `mv`
   pattern). Retired keys stay trusted.

`mv` within the same directory is an atomic rename, so each file switches over
instantly with no partially-written content in between -- unlike overwriting an
existing file in place, which a concurrent sign operation could read mid-write.
