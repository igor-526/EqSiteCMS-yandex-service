import pytest

from core.exceptions import AlreadyExistsError, AppError, ClientError, RepositoryError, YandexClientException


@pytest.mark.parametrize("error_class,status", [(AppError, 500), (ClientError, 400), (AlreadyExistsError, 409)])
def test_application_error_message_and_status(error_class: type[AppError], status: int) -> None:
    error = error_class("failure message")
    assert error.message == str(error) == "failure message"
    assert error.args == ("failure message",)
    assert error.status_code == status
    assert isinstance(error, AppError)


def test_repository_error_preserves_standard_exception_message() -> None:
    error = RepositoryError("repository failure")
    assert str(error) == "repository failure"
    assert error.args == ("repository failure",)
    assert issubclass(AlreadyExistsError, ClientError)


@pytest.mark.parametrize("error", [None, "", "invalid_token"])
@pytest.mark.parametrize("description", [None, "", "provider explanation"])
def test_yandex_error_optional_message_fields(error: str | None, description: str | None) -> None:
    exception = YandexClientException(401, error, description)
    expected = "Yandex Client exception \nStatus code: 401"
    if error:
        expected += f"\nError: {error}"
    if description:
        expected += f"\nError description: {description}"
    assert exception.message == str(exception) == expected
    assert exception.args == (expected,)


def test_yandex_error_defaults() -> None:
    assert str(YandexClientException(503)) == "Yandex Client exception \nStatus code: 503"
