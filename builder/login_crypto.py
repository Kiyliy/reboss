"""Observed public login-value encoding, not authentication or CAPTCHA bypass."""
import base64
import secrets

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

# Public constant shipped in user-login.5398946e.js, not a user credential.
PUBLIC_LOGIN_KEY_B64 = "clRwXUJBK1VKK0k0IWFbbQ=="


def encode_login_value(value, *, iv=None):
    if not isinstance(value, str):
        raise TypeError("Login values must be explicit strings")
    iv = secrets.token_bytes(16) if iv is None else iv
    if not isinstance(iv, bytes) or len(iv) != 16:
        raise ValueError("AES-CBC IV must contain exactly 16 bytes")
    key = base64.b64decode(PUBLIC_LOGIN_KEY_B64, validate=True)
    padder = padding.PKCS7(128).padder()
    padded = padder.update(value.encode("utf-8")) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    ciphertext = encryptor.update(padded) + encryptor.finalize()
    return base64.b64encode(iv + ciphertext).decode("ascii")
