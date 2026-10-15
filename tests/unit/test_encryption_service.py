import pytest
from cryptography.fernet import InvalidToken

from core.services import EncryptionService


@pytest.mark.parametrize("plaintext", ["", "Пароль 🐎 汉字", "a" * 10000])
def test_real_fernet_round_trip_and_random_ciphertext(plaintext: str) -> None:
    service = EncryptionService(secret_key="test-secret")
    first = service.encrypt(data=plaintext)
    second = service.encrypt(data=plaintext)
    assert first != second
    assert first != plaintext
    assert service.decrypt(data=first) == plaintext
    assert service.decrypt(data=second) == plaintext
    assert EncryptionService(secret_key="test-secret").decrypt(data=first) == plaintext


@pytest.mark.parametrize("invalid", ["foreign-key", "damaged", "not-fernet"])
def test_invalid_ciphertext_preserves_invalid_token_cause(invalid: str) -> None:
    service = EncryptionService(secret_key="test-secret")
    ciphertext = service.encrypt(data="token")
    if invalid == "foreign-key":
        ciphertext = EncryptionService(secret_key="other-secret").encrypt(data="token")
    elif invalid == "damaged":
        ciphertext = ciphertext[:20] + "!" + ciphertext[21:]
    else:
        ciphertext = "not a Fernet token"
    with pytest.raises(ValueError, match="Неверный ключ") as caught:
        service.decrypt(data=ciphertext)
    assert isinstance(caught.value.__cause__, InvalidToken)
