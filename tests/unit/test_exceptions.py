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


@pytest.mark.parametrize("status", [None, 401, 503])
@pytest.mark.parametrize("error", [None, "", "secret-marker"])
@pytest.mark.parametrize("description", [None, "", "secret-marker"])
def test_yandex_error_legacy_arguments_are_safe(status, error, description) -> None:
    """UT-C-09: preserve numeric positional calls/.message without reflecting secrets."""
    exception = YandexClientException(status, error, description)
    assert exception.status == status
    assert exception.category == "client"
    assert exception.message == str(exception)
    assert exception.args == (exception.message,)
    assert "secret-marker" not in repr(exception)


@pytest.mark.parametrize("category", ["client", "timeout", "transport", "http", "response", "secret-marker"])
def test_yandex_error_safe_category(category: str) -> None:
    exception = YandexClientException(None, category=category)
    assert exception.category == ("client" if category == "secret-marker" else category)
    assert "secret-marker" not in exception.message
