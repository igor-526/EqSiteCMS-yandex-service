from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from core.entities import YandexMetricaCounter


class MetricaTenantLifecycle(BaseModel):
    equestrian_id: UUID
    binding_generation: int = Field(default=0, ge=0)
    cleanup_requested_seq: int = Field(default=0, ge=0)
    cleanup_completed_seq: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_watermarks(self) -> MetricaTenantLifecycle:
        if self.cleanup_completed_seq > self.cleanup_requested_seq:
            raise ValueError("Completed cleanup exceeds requested cleanup")
        return self


class MetricaBindingSnapshot(BaseModel):
    lifecycle: MetricaTenantLifecycle
    counter: YandexMetricaCounter | None = None
