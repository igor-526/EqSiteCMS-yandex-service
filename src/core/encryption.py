"""Encryption utilities for sensitive data (tokens, client secrets)."""

from cryptography.fernet import Fernet, InvalidToken


class FernetEncryption:
    """Symmetric encryption using Fernet (AES-128 CBC + HMAC-SHA256).

    Provides authenticated encryption for sensitive data storage.
    """

    def __init__(self, key: str) -> None:
        """Initialize encryptor with Fernet key.

        Args:
            key: Base64-encoded Fernet key (32 bytes).

        Raises:
            ValueError: If key is invalid or malformed.
        """
        try:
            self._fernet = Fernet(key.encode())
        except Exception as e:
            raise ValueError(f"Invalid Fernet key: {e}") from e

    def encrypt(self, plaintext: str) -> str:
        """Encrypt plaintext string.

        Args:
            plaintext: String to encrypt.

        Returns:
            Base64-encoded ciphertext.

        Example:
            >>> encryptor = FernetEncryption(key)
            >>> ciphertext = encryptor.encrypt("sensitive_token")
        """
        encrypted_bytes = self._fernet.encrypt(plaintext.encode())
        return encrypted_bytes.decode()

    def decrypt(self, ciphertext: str) -> str:
        """Decrypt ciphertext string.

        Args:
            ciphertext: Base64-encoded ciphertext.

        Returns:
            Decrypted plaintext string.

        Raises:
            cryptography.fernet.InvalidToken: If decryption fails
                (wrong key, corrupted data, or expired token).

        Example:
            >>> encryptor = FernetEncryption(key)
            >>> plaintext = encryptor.decrypt(ciphertext)
        """
        try:
            decrypted_bytes = self._fernet.decrypt(ciphertext.encode())
            return decrypted_bytes.decode()
        except InvalidToken:
            # Re-raise as-is for caller to handle
            raise
