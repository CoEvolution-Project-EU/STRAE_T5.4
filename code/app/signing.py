import base64
import copy
from typing import Dict

import jcs  # RFC8785 canonicalization
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

PRIVATE_KEY_PEM = b"""-----BEGIN EC PRIVATE KEY-----
MHcCAQEEIIWW3PLDoBQ/GctT30iqcsvbvN6wbrfMP9tsi68cHuCAoAoGCCqGSM49
AwEHoUQDQgAE2euo5Cc5lYhUVSi/1BOs6oaJxHhGzpKI9omB2LjndL0Y61jSp5oH
YAItP6NmmWEc36QEF1cRuBywN0KH0N/ZMg==
-----END EC PRIVATE KEY-----"""

CERT_PEM = b"""-----BEGIN CERTIFICATE-----
MIICiTCCAi+gAwIBAgIUJIdxOwYrvRpVHmrKH3sXqjkt7nIwCgYIKoZIzj0EAwIw
gZkxCzAJBgNVBAYTAkdSMRIwEAYDVQQIDAlNYWNlZG9uaWExFTATBgNVBAcMDFRo
ZXNzYWxvbmlraTENMAsGA1UECgwEQ0JSTDEXMBUGA1UECwwOVGVjaG5pY2FsIFRl
YW0xEDAOBgNVBAMMB09yZXN0aXMxJTAjBgkqhkiG9w0BCQEWFm9yZXN0aXN0c2ly
YUBnbWFpbC5jb20wHhcNMjYwNDAxMTYwNzIxWhcNMjcwNDAxMTYwNzIxWjCBmTEL
MAkGA1UEBhMCR1IxEjAQBgNVBAgMCU1hY2Vkb25pYTEVMBMGA1UEBwwMVGhlc3Nh
bG9uaWtpMQ0wCwYDVQQKDARDQlJMMRcwFQYDVQQLDA5UZWNobmljYWwgVGVhbTEQ
MA4GA1UEAwwHT3Jlc3RpczElMCMGCSqGSIb3DQEJARYWb3Jlc3Rpc3RzaXJhQGdt
YWlsLmNvbTBZMBMGByqGSM49AgEGCCqGSM49AwEHA0IABNnrqOQnOZWIVFUov9QT
rOqGicR4Rs6SiPaJgdi453S9GOtY0qeaB2ACLT+jZplhHN+kBBdXEbgcsDdCh9Df
2TKjUzBRMB0GA1UdDgQWBBQM/4jioq6PukBOWwaZIs34WI5AvDAfBgNVHSMEGDAW
gBQM/4jioq6PukBOWwaZIs34WI5AvDAPBgNVHRMBAf8EBTADAQH/MAoGCCqGSM49
BAMCA0gAMEUCIQDidgF61S2MuorME3JHsMD/mRGqr1xfZyldatqM8QzbVQIgDDdd
w6FRV5qdpdACzsLGYh9cOxjP6IlXW7tAXg9GJ7g=
-----END CERTIFICATE-----"""


def load_private_key() -> ec.EllipticCurvePrivateKey:
    return serialization.load_pem_private_key(
        PRIVATE_KEY_PEM,
        password=None,
    )


def load_certificate_chain() -> list:
    cert = x509.load_pem_x509_certificate(CERT_PEM)

    der_bytes = cert.public_bytes(serialization.Encoding.DER)
    return [base64.b64encode(der_bytes).decode()]


def canonicalize_json(data: dict) -> bytes:
    """
    RFC8785 JSON Canonicalization Scheme
    """
    return jcs.canonicalize(data)


def sign_data(private_key: ec.EllipticCurvePrivateKey, data: bytes) -> str:
    signature = private_key.sign(data, ec.ECDSA(hashes.SHA256()))

    # Convert DER signature to raw r|s format
    r, s = decode_dss_signature(signature)
    raw_signature = r.to_bytes(32, "big") + s.to_bytes(32, "big")

    return base64.b64encode(raw_signature).decode()


def sign_report(report: Dict) -> Dict:
    """
    Sign the given CycloneDX report using ES256.
    """
    report = copy.deepcopy(report)

    private_key = load_private_key()
    cert_chain = load_certificate_chain()

    # Remove existing signature if present
    report.pop("signature", None)

    # Create signature object WITHOUT value
    report["signature"] = {"algorithm": "ES256", "certificatePath": cert_chain}

    # Canonicalize JSON (RFC8785)
    canonical_json = canonicalize_json(report)

    # Sign canonical JSON
    signature_value = sign_data(private_key, canonical_json)

    # Add signature value
    report["signature"]["value"] = signature_value

    return report
