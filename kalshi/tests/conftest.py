import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, rsa


def _pem(key) -> str:
    return key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()


@pytest.fixture(scope="session")
def ed_key():
    return ed25519.Ed25519PrivateKey.generate()


@pytest.fixture(scope="session")
def ed_pem(ed_key):
    return _pem(ed_key)


@pytest.fixture(scope="session")
def rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="session")
def rsa_pem(rsa_key):
    return _pem(rsa_key)
