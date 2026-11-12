# STR Assurance Engine - Issues

## Issues

### Check certificate validity when signing

**Problem**

`sign_report` (`code/app/services/signing.py`) signs with the configured certificate without checking its validity dates. If the certificate expires, STRAE keeps signing AIMBOMs and reports with it and nobody notices. External verifiers may reject documents signed with an expired certificate.

**Proposal**

- Before signing, compare the current time with the certificate's `not_valid_before_utc` / `not_valid_after_utc` and raise `SigningError` if it is outside that range, with a message that says the certificate has expired or is not yet valid, and its validity dates.
- Report it through the existing signing material error path: the API returns `500` with that message, and the worker logs `Signing material error ... request dropped` with the event, so the request can be replayed after renewal. The log messages in `generator.py` and `report_signer.py` currently say "Signing material mismatch" and should be made generic.
- Log a warning when the certificate expires within 30 days, so it can be renewed in time.
- Add tests for an expired certificate, a not-yet-valid certificate, and one close to expiry.
- Add a "Renewing the certificate" section to `docker/docker.md`: check the expiry date, issue a new certificate for the same key, and copy it to the server.

**To be decided: check the document date when verifying**

`verify_report` could also reject a document whose `metadata.timestamp` is outside the signing certificate's validity period. This is only a sanity check, not proof of when the document was signed:

- The signer chooses the timestamp, so someone holding the key can backdate it.
- For partner reports signed by `report_signer`, the timestamp is when the report was created, not when it was signed.
- `metadata.timestamp` is optional in CycloneDX, so documents without it need a rule.

Decide whether this check is worth adding, and what to do when the timestamp is missing.

### Verify that STRAE signed a document

**Problem**

`verify_report` checks the signature against the certificate embedded in `signature.certificatePath`, but does not check who that certificate belongs to. Anyone can create their own key and certificate, sign an AIMBOM, and it passes verification.

**Proposal**

- Keep a list of STRAE's signing certificates, past and current. For each: SHA-256 fingerprint, when it went into use, when it was retired, and whether its key was compromised.
- In `verify_report`, after checking the signature, reject the document if `certificatePath[0]` is not in the list or its key is marked as compromised.
- Do not reject a certificate only because it has expired: documents signed before a rotation must still verify.
- Add tests for a known certificate (accepted), an unknown certificate (rejected), a retired or expired certificate (accepted), and a compromised one (rejected).

### Trust the reverse proxy's forwarded headers

**Problem**

The API runs with `--proxy-headers`, but Uvicorn only trusts `X-Forwarded-For` / `X-Forwarded-Proto` from the addresses in `FORWARDED_ALLOW_IPS`, which defaults to `127.0.0.1`. The reverse proxy runs on a separate VM, so its headers are ignored: the API logs the proxy's IP instead of the client's, and sees requests as `http` instead of `https`. The rate limiting and concurrency limiting middleware would also limit all clients together as one IP if enabled.

**Proposal**

- Set `FORWARDED_ALLOW_IPS` on `strae-api` to the reverse proxy VM's IP.
- Add it to the stack in `docs/deployment.md`, with an empty placeholder, and describe it in the "Reverse proxy config" section.
- Check that the logs show the client's IP for a request through the proxy.
