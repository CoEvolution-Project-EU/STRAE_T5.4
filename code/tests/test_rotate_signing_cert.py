import json
import os
import stat
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from app.models.trusted_keys import TrustedKeys
from app.scripts.rotate_signing_cert import (
    CERT_FILE,
    KEY_FILE,
    TRUST_LIST_FILE,
    main,
)
from app.services.signing import (
    is_strae_key,
    public_key_fingerprint,
    validate_signing_material,
)
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from tests.signing_utils import make_certificate

NOW = datetime(2030, 1, 1, tzinfo=timezone.utc)


def _write_material(directory, cert_expires_in=timedelta(days=365), listed=True):
    key = ec.generate_private_key(ec.SECP256R1())
    cert = make_certificate(
        key,
        not_valid_before=NOW - timedelta(days=365),
        not_valid_after=NOW + cert_expires_in,
    )

    (directory / KEY_FILE).write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    (directory / CERT_FILE).write_bytes(cert.public_bytes(serialization.Encoding.PEM))

    entries = []
    if listed:
        entries.append(
            {
                "sha256": public_key_fingerprint(cert),
                "in_use_from": "2029-01-01T00:00:00Z",
            }
        )
    (directory / TRUST_LIST_FILE).write_text(json.dumps({"keys": entries}))

    return key, cert


def _load(directory):
    key = serialization.load_pem_private_key(
        (directory / KEY_FILE).read_bytes(), password=None
    )
    cert = x509.load_pem_x509_certificate((directory / CERT_FILE).read_bytes())
    trusted = TrustedKeys.model_validate_json((directory / TRUST_LIST_FILE).read_text())
    return key, cert, trusted


def _trusted(trusted_keys):
    return {key.sha256: key for key in trusted_keys.keys}


def _snapshot(directory):
    return {path.name: path.read_bytes() for path in directory.iterdir()}


def _run(directory, *args):
    return main(["--dir", str(directory), *args], now=NOW)


def test_renews_certificate_for_same_key(tmp_path):
    old_key, old_cert = _write_material(tmp_path)
    old_trust_list = (tmp_path / TRUST_LIST_FILE).read_bytes()

    assert _run(tmp_path) == 0

    key, cert, trusted = _load(tmp_path)
    assert key.private_numbers() == old_key.private_numbers()
    validate_signing_material(key=key, cert=cert)
    assert cert != old_cert
    assert cert.not_valid_after_utc == NOW + timedelta(days=3650)
    # Valid from slightly before now, for containers whose clock is behind.
    assert NOW - timedelta(minutes=10) < cert.not_valid_before_utc < NOW
    # The trust list lists keys, so a new certificate doesn't change it.
    assert (tmp_path / TRUST_LIST_FILE).read_bytes() == old_trust_list
    assert is_strae_key(old_cert, trusted=_trusted(trusted))
    assert is_strae_key(cert, trusted=_trusted(trusted))


def test_days_sets_validity(tmp_path):
    _write_material(tmp_path)

    _run(tmp_path, "--days", "30")

    _, cert, _ = _load(tmp_path)
    assert cert.not_valid_after_utc == NOW + timedelta(days=30)


def test_new_key_adds_key_and_retires_old_one(tmp_path):
    old_key, old_cert = _write_material(tmp_path)

    assert _run(tmp_path, "--new-key") == 0

    key, cert, trusted = _load(tmp_path)
    assert key.private_numbers() != old_key.private_numbers()
    validate_signing_material(key=key, cert=cert)

    entries = {entry.sha256: entry for entry in trusted.keys}
    old_entry = entries[public_key_fingerprint(old_cert)]
    new_entry = entries[public_key_fingerprint(cert)]
    assert old_entry.retired_at == NOW
    assert new_entry.in_use_from == NOW
    assert new_entry.retired_at is None
    # Retired keys stay trusted.
    assert is_strae_key(old_cert, trusted=_trusted(trusted))


@pytest.mark.parametrize(
    "expires_in, rotated",
    [
        (timedelta(days=365), False),
        (timedelta(days=10), True),
        (timedelta(days=-10), True),  # Already expired
    ],
)
def test_if_expiring_within(tmp_path, expires_in, rotated):
    _write_material(tmp_path, cert_expires_in=expires_in)
    before = _snapshot(tmp_path)

    assert _run(tmp_path, "--if-expiring-within", "30") == 0

    assert (_snapshot(tmp_path) != before) is rotated


def test_refuses_when_current_key_is_not_listed(tmp_path, capsys):
    _write_material(tmp_path, listed=False)
    before = _snapshot(tmp_path)

    assert _run(tmp_path) == 1

    assert "not in the trust list" in capsys.readouterr().err
    assert _snapshot(tmp_path) == before


def test_refuses_when_key_and_certificate_do_not_match(tmp_path, capsys):
    _write_material(tmp_path)
    other_key = ec.generate_private_key(ec.SECP256R1())
    other_cert = make_certificate(other_key)
    (tmp_path / CERT_FILE).write_bytes(
        other_cert.public_bytes(serialization.Encoding.PEM)
    )
    before = _snapshot(tmp_path)

    assert _run(tmp_path) == 1

    assert "do not match" in capsys.readouterr().err
    assert _snapshot(tmp_path) == before


def test_refuses_when_trust_list_is_missing(tmp_path, capsys):
    _write_material(tmp_path)
    (tmp_path / TRUST_LIST_FILE).unlink()

    assert _run(tmp_path) == 1

    assert "trust list" in capsys.readouterr().err


def test_init_creates_trust_list_with_current_key(tmp_path):
    _, cert = _write_material(tmp_path)
    (tmp_path / TRUST_LIST_FILE).unlink()

    assert _run(tmp_path, "--init") == 0

    _, _, trusted = _load(tmp_path)
    assert [entry.sha256 for entry in trusted.keys] == [public_key_fingerprint(cert)]
    assert stat.S_IMODE(os.stat(tmp_path / TRUST_LIST_FILE).st_mode) == 0o644


def test_init_refuses_existing_trust_list(tmp_path, capsys):
    _write_material(tmp_path)

    assert _run(tmp_path, "--init") == 1

    assert "already exists" in capsys.readouterr().err


def test_dry_run_writes_nothing(tmp_path):
    _write_material(tmp_path)
    before = _snapshot(tmp_path)

    assert _run(tmp_path, "--dry-run", "--new-key") == 0

    assert _snapshot(tmp_path) == before


def test_permissions_and_backups(tmp_path):
    _write_material(tmp_path)
    before = _snapshot(tmp_path)

    _run(tmp_path, "--new-key")

    def mode(name):
        return stat.S_IMODE(os.stat(tmp_path / name).st_mode)

    assert mode(KEY_FILE) == 0o600
    assert mode(CERT_FILE) == 0o644
    assert mode(TRUST_LIST_FILE) == 0o644

    stamp = NOW.strftime("%Y%m%dT%H%M%SZ")
    for name in (KEY_FILE, CERT_FILE, TRUST_LIST_FILE):
        assert (tmp_path / f"{name}.{stamp}.bak").read_bytes() == before[name]

    assert not list(tmp_path.glob("*.new"))


def test_failure_while_writing_leaves_files_in_use_unchanged(tmp_path, capsys):
    _write_material(tmp_path)
    before = _snapshot(tmp_path)

    real_fsync = os.fsync
    calls = []

    def failing_fsync(fd):
        calls.append(fd)
        if len(calls) == 2:
            raise OSError("disk full")
        real_fsync(fd)

    with patch("app.scripts.rotate_signing_cert.os.fsync", failing_fsync):
        assert _run(tmp_path, "--new-key") == 1

    assert "disk full" in capsys.readouterr().err
    assert _snapshot(tmp_path) == before
    assert not list(tmp_path.glob("*.new"))


def test_failure_while_generating_leaves_files_in_use_unchanged(tmp_path):
    _write_material(tmp_path)
    before = _snapshot(tmp_path)

    with patch(
        "app.scripts.rotate_signing_cert.build_certificate",
        side_effect=RuntimeError("boom"),
    ):
        with pytest.raises(RuntimeError):
            _run(tmp_path, "--new-key")

    assert _snapshot(tmp_path) == before


@pytest.mark.parametrize(
    "args",
    [
        ("--init", "--new-key"),
        ("--init", "--if-expiring-within", "30"),
        ("--new-key", "--if-expiring-within", "30"),
        ("--days", "0"),
    ],
)
def test_rejects_invalid_option_combinations(tmp_path, args):
    with pytest.raises(SystemExit):
        _run(tmp_path, *args)
