class YandexClientException(Exception):
    """Safe client failure; raw provider details belong only in the cause."""

    def __init__(
        self,
        status: int | None,
        error: str | None = None,
        error_description: str | None = None,
        *,
        category: str = "client",
    ) -> None:
        # Keep legacy positional arguments, but never reflect untrusted text.
        self.status = status
        self.category = category if category in {"client", "timeout", "transport", "http", "response"} else "client"
        self.message = f"Yandex Client exception \nStatus code: {status}\nCategory: {self.category}"
        super().__init__(self.message)
