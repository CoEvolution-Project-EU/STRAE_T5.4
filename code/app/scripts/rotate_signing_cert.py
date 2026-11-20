"""Rotate STRAE's signing certificate, or key and certificate, and keep the
trust list in sync.

Run by the operator as a one-off container with the secrets directory mounted
read-write (see docs/deployment.md):

    python -m app.scripts.rotate_signing_cert --dir /secrets [options]

- No option: issue a new certificate for the current key. The trust list,
  which lists keys, does not change.
- `--new-key`: generate a new key and certificate, add the key to the trust
  list and mark the current one as retired.
- `--if-expiring-within N`: do nothing unless the current certificate expires
  within N days. For the scheduled renewal.
- `--init`: create the trust list with the current key, without rotating.
- `--dry-run`: print what would change, and write nothing.

Files are written as `<name>.new`, then moved into place with an atomic
rename, the trust list first, so the services never see a new key that is not
listed yet. Replaced files are kept as `<name>.<timestamp>.bak`.
"""

import argparse
import json
import os
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from pydantic import ValidationError

from app.models.trusted_keys import TrustedKey, TrustedKeys
from app.services.signing import (
    SigningError,
    public_key_fingerprint,
    validate_signing_material,
)

KEY_FILE = "signing-key.pem"
CERT_FILE = "signing-cert.pem"
TRUST_LIST_FILE = "trusted-keys.json"

DEFAULT_DAYS = 3650

# The new certificate is valid from a little before now, so a container whose
# clock is slightly behind the host's doesn't reject it right after a rotation.
CLOCK_SKEW = timedelta(minutes=5)

# Same subject as the `openssl req` command in docs/deployment.md.
SUBJECT = x509.Name(
    [
        x509.NameAttribute(NameOID.COUNTRY_NAME, "GR"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "STRAE"),
        x509.NameAttribute(NameOID.COMMON_NAME, "STRAE Signing Certificate"),
    ]
)


class RotationError(Exception):
    """Raised when the rotation can't be done. Nothing in use was changed."""


@dataclass
class OutputFile:
    """A file to write into the secrets directory."""

    name: str
    content: bytes
    mode: int


def load_key(path: Path) -> ec.EllipticCurvePrivateKey:
    """Load the signing key.

    Args:
        path: Path of the PEM key.

    Returns:
        The key.

    Raises:
        RotationError: If the key can't be read or is not a P-256 key.
    """

    try:
        key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    except (OSError, ValueError, TypeError) as e:
        raise RotationError(f"Can't load the signing key {path}: {e}") from e

    if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(
        key.curve, ec.SECP256R1
    ):
        raise RotationError(f"Signing key {path} is not a P-256 key")

    return key


def load_certificate(path: Path) -> x509.Certificate:
    """Load the signing certificate.

    Args:
        path: Path of the PEM certificate.

    Returns:
        The certificate.

    Raises:
        RotationError: If the certificate can't be read.
    """

    try:
        return x509.load_pem_x509_certificate(path.read_bytes())
    except (OSError, ValueError) as e:
        raise RotationError(f"Can't load the signing certificate {path}: {e}") from e


def load_trust_list(path: Path) -> TrustedKeys:
    """Load and validate the trust list.

    Args:
        path: Path of the trust list.

    Returns:
        The trust list.

    Raises:
        RotationError: If the trust list can't be read or is invalid.
    """

    try:
        return TrustedKeys.model_validate(json.loads(path.read_bytes()))
    except OSError as e:
        raise RotationError(f"Can't read the trust list {path}: {e}") from e
    except (ValueError, ValidationError) as e:
        raise RotationError(f"Trust list {path} is invalid: {e}") from e


def build_certificate(
    key: ec.EllipticCurvePrivateKey, days: int, now: datetime
) -> x509.Certificate:
    """Issue a self-signed certificate for the key.

    Args:
        key: The signing key.
        days: How many days the certificate is valid for, from `now`.
        now: The current time.

    Returns:
        The certificate.
    """

    return (
        x509.CertificateBuilder()
        .subject_name(SUBJECT)
        .issuer_name(SUBJECT)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - CLOCK_SKEW)
        .not_valid_after(now + timedelta(days=days))
        .sign(key, hashes.SHA256())
    )


def key_bytes(key: ec.EllipticCurvePrivateKey) -> bytes:
    """PEM encode a private key, unencrypted, as `openssl genpkey` does."""

    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )


def cert_bytes(cert: x509.Certificate) -> bytes:
    """PEM encode a certificate."""

    return cert.public_bytes(serialization.Encoding.PEM)


def trust_list_bytes(trust_list: TrustedKeys) -> bytes:
    """Serialize the trust list, validating it first so the script never
    writes a list that STRAE can't load."""

    validated = TrustedKeys.model_validate(trust_list.model_dump())
    return (json.dumps(validated.model_dump(mode="json"), indent=2) + "\n").encode()


def write_files(directory: Path, files: list[OutputFile], now: datetime) -> None:
    """Write the files into place, in order.

    Every file is first written as `<name>.new` and synced. Only then are they
    moved into place with `os.replace`, an atomic rename, back to back. The
    files they replace are kept as `<name>.<timestamp>.bak`.

    Args:
        directory: The secrets directory.
        files: The files to write, in the order to move them into place.
        now: The current time, for the backup names.

    Raises:
        RotationError: If a file can't be written. If this happens before the
            renames, the `.new` files are removed and nothing in use changed.
    """

    new_paths: list[Path] = []
    stamp = now.strftime("%Y%m%dT%H%M%SZ")

    try:
        for file in files:
            new_path = directory / f"{file.name}.new"
            new_paths.append(new_path)

            fd = os.open(new_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, file.mode)
            try:
                os.write(fd, file.content)
                os.fsync(fd)
            finally:
                os.close(fd)
            # `os.open` applies the umask, so set the mode explicitly.
            os.chmod(new_path, file.mode)

        # Back up before renaming, so the renames run back to back, keeping
        # the window where the key and certificate don't match short.
        for file in files:
            path = directory / file.name
            if path.exists():
                shutil.copy2(path, directory / f"{file.name}.{stamp}.bak")
    except OSError as e:
        for new_path in new_paths:
            new_path.unlink(missing_ok=True)
        raise RotationError(f"Can't write the new files in {directory}: {e}") from e

    for file in files:
        os.replace(directory / f"{file.name}.new", directory / file.name)


def describe(cert: x509.Certificate) -> str:
    """One line about a certificate, for the output."""

    return (
        f"key {public_key_fingerprint(cert)}, "
        f"valid {cert.not_valid_before_utc.isoformat()} to "
        f"{cert.not_valid_after_utc.isoformat()}"
    )


def init(directory: Path, dry_run: bool, now: datetime) -> list[str]:
    """Create the trust list with the current key.

    Args:
        directory: The secrets directory.
        dry_run: Print what would change, and write nothing.
        now: The current time.

    Returns:
        The lines to print.

    Raises:
        RotationError: If the trust list already exists, or the key and
            certificate can't be loaded or don't match.
    """

    trust_list_path = directory / TRUST_LIST_FILE
    if trust_list_path.exists():
        raise RotationError(f"Trust list {trust_list_path} already exists")

    key = load_key(directory / KEY_FILE)
    cert = load_certificate(directory / CERT_FILE)
    check_match(key, cert)

    trust_list = TrustedKeys(
        keys=[
            TrustedKey(
                sha256=public_key_fingerprint(cert),
                # The key may be older than its current certificate, but this
                # is the best estimate available. Audit only.
                in_use_from=cert.not_valid_before_utc,
                note="Added by --init",
            )
        ]
    )

    lines = [f"Trust list with the current key: {describe(cert)}"]

    if dry_run:
        return ["Dry run, nothing written."] + lines

    write_files(
        directory,
        [OutputFile(TRUST_LIST_FILE, trust_list_bytes(trust_list), 0o644)],
        now,
    )

    return lines + [
        f"Created {trust_list_path}. Copy it to the backup of the signing material."
    ]


def check_match(key: ec.EllipticCurvePrivateKey, cert: x509.Certificate) -> None:
    """Raise `RotationError` if the key and certificate don't match."""

    try:
        validate_signing_material(key=key, cert=cert)
    except SigningError as e:
        raise RotationError(str(e)) from e


def rotate(
    directory: Path,
    new_key: bool,
    days: int,
    if_expiring_within: int | None,
    dry_run: bool,
    now: datetime,
) -> list[str]:
    """Issue a new certificate, for the current key or a new one.

    Args:
        directory: The secrets directory.
        new_key: Generate a new key too, and add it to the trust list.
        days: Validity of the new certificate, in days.
        if_expiring_within: Do nothing unless the current certificate expires
            within this many days.
        dry_run: Print what would change, and write nothing.
        now: The current time.

    Returns:
        The lines to print.

    Raises:
        RotationError: If the current material can't be loaded, the key and
            certificate don't match, or the current key is not in the trust
            list.
    """

    key = load_key(directory / KEY_FILE)
    cert = load_certificate(directory / CERT_FILE)
    trust_list = load_trust_list(directory / TRUST_LIST_FILE)

    # An expired certificate is not a reason to stop: renewing it is the fix.
    check_match(key, cert)

    fingerprint = public_key_fingerprint(cert)
    current_entries = [k for k in trust_list.keys if k.sha256 == fingerprint]
    if not current_entries:
        raise RotationError(
            f"The current key {fingerprint} is not in the trust list. The list "
            "is out of sync with the signing material: check it by hand first."
        )

    lines = [f"Current certificate: {describe(cert)}"]

    if if_expiring_within is not None:
        expires_in = cert.not_valid_after_utc - now
        if expires_in > timedelta(days=if_expiring_within):
            return lines + [
                f"Expires in {expires_in.days} days, more than "
                f"{if_expiring_within}: nothing to do."
            ]

    files: list[OutputFile] = []

    if new_key:
        key = ec.generate_private_key(ec.SECP256R1())
        new_cert = build_certificate(key, days, now)
        check_match(key, new_cert)

        current_entries[0].retired_at = current_entries[0].retired_at or now
        trust_list.keys.append(
            TrustedKey(
                sha256=public_key_fingerprint(new_cert),
                in_use_from=now,
                note="Rotated by script",
            )
        )

        # The trust list first, so the new key is listed before it is used.
        files.append(OutputFile(TRUST_LIST_FILE, trust_list_bytes(trust_list), 0o644))
        files.append(OutputFile(KEY_FILE, key_bytes(key), 0o600))
    else:
        new_cert = build_certificate(key, days, now)
        check_match(key, new_cert)

    files.append(OutputFile(CERT_FILE, cert_bytes(new_cert), 0o644))

    lines.append(f"New certificate:     {describe(new_cert)}")
    if new_key:
        lines.append(
            f"New key {public_key_fingerprint(new_cert)} added to the trust list"
        )
        lines.append(f"Old key {fingerprint} marked as retired (still trusted)")
    else:
        lines.append("Same key: the trust list is unchanged.")

    if dry_run:
        return ["Dry run, nothing written."] + lines

    write_files(directory, files, now)

    lines.append(f"Wrote {', '.join(file.name for file in files)} in {directory}")
    if new_key:
        lines.append(
            "Copy the new trust list and the new key to the backup of the "
            "signing material."
        )

    return lines


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Parse the command line."""

    parser = argparse.ArgumentParser(
        prog="python -m app.scripts.rotate_signing_cert",
        description=(
            "Rotate STRAE's signing certificate, or key and certificate, and "
            "keep the trust list in sync."
        ),
    )
    parser.add_argument(
        "--dir",
        required=True,
        type=Path,
        help=f"Secrets directory with {KEY_FILE}, {CERT_FILE} and {TRUST_LIST_FILE}",
    )
    parser.add_argument(
        "--new-key",
        action="store_true",
        help="Generate a new key and certificate, and add the key to the trust list",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=DEFAULT_DAYS,
        help=f"Validity of the new certificate in days (default {DEFAULT_DAYS})",
    )
    parser.add_argument(
        "--if-expiring-within",
        type=int,
        metavar="N",
        help="Do nothing unless the current certificate expires within N days",
    )
    parser.add_argument(
        "--init",
        action="store_true",
        help="Create the trust list with the current key, without rotating",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Print what would change only"
    )

    args = parser.parse_args(argv)

    if args.days <= 0:
        parser.error("--days must be positive")
    if args.init and (args.new_key or args.if_expiring_within is not None):
        parser.error("--init can't be combined with --new-key or --if-expiring-within")
    if args.new_key and args.if_expiring_within is not None:
        parser.error(
            "--new-key can't be combined with --if-expiring-within: key rotation "
            "changes what is trusted, so it is never scheduled"
        )

    return args


def main(argv: list[str] | None = None, now: datetime | None = None) -> int:
    """Run the script.

    Args:
        argv: The arguments, without the program name. Defaults to `sys.argv`.
        now: The current time. Defaults to the current UTC time.

    Returns:
        The exit code.
    """

    args = parse_args(argv)
    now = now or datetime.now(timezone.utc).replace(microsecond=0)

    try:
        if args.init:
            lines = init(args.dir, args.dry_run, now)
        else:
            lines = rotate(
                args.dir,
                args.new_key,
                args.days,
                args.if_expiring_within,
                args.dry_run,
                now,
            )
    except RotationError as e:
        print(f"[{now.isoformat()}] Error: {e}", file=sys.stderr)
        return 1

    for line in lines:
        print(f"[{now.isoformat()}] {line}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
