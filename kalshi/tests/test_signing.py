import base64

import pytest
from cli_tools_shared.exceptions import ClientError
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding

from kalshi_cli.signing import Signer, decode_private_key


def test_ed25519_signature_verifies(ed_key, ed_pem):
    headers = Signer("key-1", ed_pem).headers("GET", "/trade-api/v2/portfolio/balance")
    message = f"{headers['KALSHI-ACCESS-TIMESTAMP']}GET/trade-api/v2/portfolio/balance".encode()
    ed_key.public_key().verify(base64.b64decode(headers["KALSHI-ACCESS-SIGNATURE"]), message)
    assert headers["KALSHI-ACCESS-KEY"] == "key-1"


def test_rsa_pss_signature_verifies(rsa_key, rsa_pem):
    headers = Signer("key-2", rsa_pem).headers("POST", "/trade-api/v2/portfolio/events/orders")
    message = f"{headers['KALSHI-ACCESS-TIMESTAMP']}POST/trade-api/v2/portfolio/events/orders".encode()
    pss = padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH)
    rsa_key.public_key().verify(base64.b64decode(headers["KALSHI-ACCESS-SIGNATURE"]), message, pss, hashes.SHA256())


def test_timestamp_is_milliseconds(ed_pem):
    timestamp = Signer("k", ed_pem).headers("GET", "/p")["KALSHI-ACCESS-TIMESTAMP"]
    assert len(timestamp) == 13 and timestamp.isdigit()


def test_invalid_pem_fails_explicitly():
    with pytest.raises(ClientError, match="not a valid unencrypted PEM key"):
        Signer("k", "not a key")


def test_unsupported_key_type_fails_explicitly():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    pem = ec.generate_private_key(ec.SECP256R1()).private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    with pytest.raises(ClientError, match="Ed25519 or RSA"):
        Signer("k", pem)


def test_stored_key_round_trips_through_base64(ed_pem):
    stored = base64.b64encode(ed_pem.encode()).decode()
    assert "\n" not in stored
    assert decode_private_key(stored + "\n") == ed_pem


def test_stored_key_that_is_not_base64_fails_explicitly(ed_pem):
    with pytest.raises(ClientError, match="base64 of the PEM file"):
        decode_private_key(ed_pem)


@pytest.mark.parametrize("key_id", ["", "bad\nid", "has space", "ключ"])
def test_key_id_must_be_printable_ascii(ed_pem, key_id):
    with pytest.raises(ClientError, match="printable ASCII"):
        Signer(key_id, ed_pem)
