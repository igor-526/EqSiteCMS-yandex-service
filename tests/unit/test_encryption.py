"""Unit tests for encryption utilities."""

import pytest
from cryptography.fernet import Fernet, InvalidToken

from src.core.encryption import FernetEncryption


@pytest.fixture
def valid_fernet_key() -> str:
    """Generate a valid Fernet key for testing.
    
    Returns:
        Base64-encoded Fernet key (32 bytes).
    """
    return Fernet.generate_key().decode()


@pytest.fixture
def another_fernet_key() -> str:
    """Generate another valid Fernet key for testing wrong-key scenarios.
    
    Returns:
        Base64-encoded Fernet key (32 bytes).
    """
    return Fernet.generate_key().decode()


class TestFernetEncryption:
    """Tests for FernetEncryption class."""

    def test_encrypt_decrypt_roundtrip(self, valid_fernet_key: str) -> None:
        """Test that encrypt followed by decrypt returns original plaintext.
        
        Verifies basic encryption/decryption functionality with valid key.
        """
        encryption = FernetEncryption(valid_fernet_key)
        plaintext = "secret data"
        
        ciphertext = encryption.encrypt(plaintext)
        decrypted = encryption.decrypt(ciphertext)
        
        assert decrypted == plaintext
        assert ciphertext != plaintext  # Ensure it was actually encrypted

    @pytest.mark.parametrize("plaintext", [
        "simple text",
        "текст с unicode символами 🔒",
        "",  # Empty string
        "a" * 1000,  # Long text
        "special chars: !@#$%^&*()_+-={}[]|\\:;\"'<>,.?/~`",
    ])
    def test_encrypt_decrypt_various_plaintexts(
        self, valid_fernet_key: str, plaintext: str
    ) -> None:
        """Test encryption roundtrip with various plaintext inputs.
        
        Args:
            valid_fernet_key: Valid Fernet key fixture.
            plaintext: Various test strings (parameterized).
        """
        encryption = FernetEncryption(valid_fernet_key)
        
        ciphertext = encryption.encrypt(plaintext)
        decrypted = encryption.decrypt(ciphertext)
        
        assert decrypted == plaintext

    def test_decrypt_with_wrong_key_raises_error(
        self, valid_fernet_key: str, another_fernet_key: str
    ) -> None:
        """Test that decrypting with wrong key raises InvalidToken.
        
        Verifies that encryption is properly authenticated and tampering/wrong key
        is detected.
        """
        encryption1 = FernetEncryption(valid_fernet_key)
        encryption2 = FernetEncryption(another_fernet_key)
        
        plaintext = "secret"
        ciphertext = encryption1.encrypt(plaintext)
        
        # Attempting to decrypt with different key should raise InvalidToken
        with pytest.raises(InvalidToken):
            encryption2.decrypt(ciphertext)

    def test_invalid_fernet_key_raises_value_error(self) -> None:
        """Test that invalid key raises ValueError during initialization.
        
        Verifies proper error handling for malformed keys.
        """
        with pytest.raises(ValueError, match="Invalid Fernet key"):
            FernetEncryption("not_a_valid_base64_key")

    def test_encrypt_produces_different_ciphertexts(self, valid_fernet_key: str) -> None:
        """Test that encrypting same plaintext twice produces different ciphertexts.
        
        Fernet includes IV/timestamp, so same plaintext should produce different
        ciphertexts (IND-CPA security).
        """
        encryption = FernetEncryption(valid_fernet_key)
        plaintext = "secret data"
        
        ciphertext1 = encryption.encrypt(plaintext)
        ciphertext2 = encryption.encrypt(plaintext)
        
        # Different ciphertexts due to random IV
        assert ciphertext1 != ciphertext2
        
        # But both decrypt to same plaintext
        assert encryption.decrypt(ciphertext1) == plaintext
        assert encryption.decrypt(ciphertext2) == plaintext

    def test_decrypt_corrupted_ciphertext_raises_error(self, valid_fernet_key: str) -> None:
        """Test that decrypting corrupted ciphertext raises InvalidToken.
        
        Verifies authentication check catches tampering.
        """
        encryption = FernetEncryption(valid_fernet_key)
        
        plaintext = "secret data"
        ciphertext = encryption.encrypt(plaintext)
        
        # Corrupt the ciphertext (flip last character)
        corrupted = ciphertext[:-1] + ("A" if ciphertext[-1] != "A" else "B")
        
        with pytest.raises(InvalidToken):
            encryption.decrypt(corrupted)
