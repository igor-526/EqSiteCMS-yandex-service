import re
from datetime import datetime
from typing import Final, Literal, Self
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

CLEANUP_REQUESTED_SUBJECT: Final = "events.yandex.metrica.cleanup.requested"
CLEANUP_COMPLETED_SUBJECT: Final = "events.metrica.cleanup.completed"


class CleanupRequested(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    message_id: UUID
    operation_id: UUID
    equestrian_id: UUID
    occurred_at: AwareDatetime
    cleanup_seq: int = Field(gt=0, le=9223372036854775807)
    binding_generation: int = Field(ge=0, le=9223372036854775807)
    reason: Literal["counter_unlinked", "account_deleted"]

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        expected = uuid5(
            NAMESPACE_URL, f"eqcms:maintenance:v1:{CLEANUP_REQUESTED_SUBJECT}:{self.operation_id}:requested"
        )
        offset = self.occurred_at.utcoffset()
        if self.message_id != expected or offset is None:
            raise ValueError("Invalid cleanup envelope identity")
        if offset.total_seconds() != 0:
            raise ValueError("Cleanup timestamp must be UTC")
        return self


class CleanupOutboxClaim(BaseModel):
    model_config = ConfigDict(frozen=True)

    message_id: UUID
    claim_token: UUID
    claim_expires_at: datetime
    attempts: int = Field(gt=0)
    subject: Literal["events.yandex.metrica.cleanup.requested"]
    payload: CleanupRequested

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        if self.message_id != self.payload.message_id:
            raise ValueError("Outbox identity mismatch")
        return self


class CleanupCompleted(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    message_id: UUID
    operation_id: UUID
    equestrian_id: UUID
    occurred_at: AwareDatetime
    cleanup_seq: int = Field(strict=True, gt=0, le=9223372036854775807)
    status: Literal["completed"]

    @field_validator("occurred_at", mode="before")
    @classmethod
    def validate_timestamp_format(cls, value: object) -> object:
        if isinstance(value, datetime):
            return value
        if not isinstance(value, str):
            raise ValueError("Cleanup timestamp must be UTC RFC3339")
        pattern = r"\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[Zz]|\+00:00)"
        if re.fullmatch(pattern, value) is None:
            raise ValueError("Cleanup timestamp must be UTC RFC3339")
        return value

    @field_validator("schema_version", mode="before")
    @classmethod
    def validate_version_type(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("Invalid cleanup schema version")
        return value

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        expected = uuid5(
            NAMESPACE_URL, f"eqcms:maintenance:v1:{CLEANUP_COMPLETED_SUBJECT}:{self.operation_id}:completed"
        )
        offset = self.occurred_at.utcoffset()
        if self.message_id != expected or offset is None or offset.total_seconds() != 0:
            raise ValueError("Invalid cleanup result identity")
        return self


class InvalidCleanupResult(ValueError):
    """Permanent correlation/hash conflict; never acknowledge as applied."""
