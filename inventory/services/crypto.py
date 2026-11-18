from cryptography.fernet import Fernet
from django.conf import settings


def get_fernet():
    return Fernet(settings.CREDENTIAL_ENCRYPTION_KEY.encode())


def encrypt_password(password: str) -> str:
    return get_fernet().encrypt(password.encode()).decode()


def decrypt_password(encrypted: str) -> str:
    return get_fernet().decrypt(encrypted.encode()).decode()
