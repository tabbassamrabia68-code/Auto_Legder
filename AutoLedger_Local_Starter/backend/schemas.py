from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


class RecordSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OwnerCreate(RecordSchema):
    full_name: str = Field(min_length=1, max_length=120)
    email: str | None = Field(default=None, max_length=254)
    phone: str | None = Field(default=None, max_length=40)


class ServiceCreate(RecordSchema):
    vehicle_id: int = Field(gt=0)
    service_date: date
    service_type: str = Field(min_length=1, max_length=80)
    mileage: int | None = Field(default=None, ge=0)
    workshop_name: str | None = Field(default=None, max_length=120)
    notes: str | None = None
    cost: Decimal | None = Field(default=None, ge=0)


class RepairCreate(RecordSchema):
    vehicle_id: int = Field(gt=0)
    repair_date: date
    repair_type: str = Field(min_length=1, max_length=80)
    description: str | None = None
    cost: Decimal | None = Field(default=None, ge=0)
    workshop_name: str | None = Field(default=None, max_length=120)


class MileageCreate(RecordSchema):
    vehicle_id: int = Field(gt=0)
    recorded_date: date
    mileage: int = Field(ge=0)
    source: Literal["OWNER", "SERVICE", "INSPECTION", "DEALER", "OTHER"]


class InspectionCreate(RecordSchema):
    vehicle_id: int = Field(gt=0)
    inspection_date: date
    result: Literal["PASS", "FAIL", "CONDITIONAL", "PENDING"]
    remarks: str | None = None


class DocumentCreate(RecordSchema):
    vehicle_id: int = Field(gt=0)
    document_type: str = Field(min_length=1, max_length=80)
    document_number: str | None = Field(default=None, max_length=80)
    issue_date: date | None = None
    expiry_date: date | None = None
    status: Literal["VALID", "PENDING", "EXPIRED", "CANCELLED"]

    @model_validator(mode="after")
    def validate_date_order(self):
        if self.issue_date and self.expiry_date and self.expiry_date < self.issue_date:
            raise ValueError("expiry_date cannot precede issue_date")
        return self


class VerificationCreate(RecordSchema):
    vehicle_id: int = Field(gt=0)
    verification_date: date
    result: Literal["VERIFIED", "REJECTED", "PENDING", "CONDITIONAL"]
    remarks: str | None = None


class RecordPatch(RecordSchema):
    @model_validator(mode="after")
    def require_fields(self):
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided")
        return self


class OwnerPatch(RecordPatch):
    full_name: str | None = Field(default=None, min_length=1, max_length=120)
    email: str | None = Field(default=None, max_length=254)
    phone: str | None = Field(default=None, max_length=40)


class ServicePatch(RecordPatch):
    service_date: date | None = None
    service_type: str | None = Field(default=None, min_length=1, max_length=80)
    mileage: int | None = Field(default=None, ge=0)
    workshop_name: str | None = Field(default=None, max_length=120)
    notes: str | None = None
    cost: Decimal | None = Field(default=None, ge=0)


class RepairPatch(RecordPatch):
    repair_date: date | None = None
    repair_type: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = None
    cost: Decimal | None = Field(default=None, ge=0)
    workshop_name: str | None = Field(default=None, max_length=120)


class MileagePatch(RecordPatch):
    recorded_date: date | None = None
    mileage: int | None = Field(default=None, ge=0)
    source: Literal["OWNER", "SERVICE", "INSPECTION", "DEALER", "OTHER"] | None = None


class InspectionPatch(RecordPatch):
    inspection_date: date | None = None
    result: Literal["PASS", "FAIL", "CONDITIONAL", "PENDING"] | None = None
    remarks: str | None = None


class DocumentPatch(RecordPatch):
    document_type: str | None = Field(default=None, min_length=1, max_length=80)
    document_number: str | None = Field(default=None, max_length=80)
    issue_date: date | None = None
    expiry_date: date | None = None
    status: Literal["VALID", "PENDING", "EXPIRED", "CANCELLED"] | None = None


class VerificationPatch(RecordPatch):
    verification_date: date | None = None
    result: Literal["VERIFIED", "REJECTED", "PENDING", "CONDITIONAL"] | None = None
    remarks: str | None = None


RECORD_SCHEMAS = {
    "owners": OwnerCreate,
    "services": ServiceCreate,
    "repairs": RepairCreate,
    "mileage": MileageCreate,
    "inspections": InspectionCreate,
    "documents": DocumentCreate,
    "verification": VerificationCreate,
}

RECORD_PATCH_SCHEMAS = {
    "owners": OwnerPatch,
    "services": ServicePatch,
    "repairs": RepairPatch,
    "mileage": MileagePatch,
    "inspections": InspectionPatch,
    "documents": DocumentPatch,
    "verification": VerificationPatch,
}


def validate_record(resource: str, payload: dict, partial: bool = False) -> dict:
    schema = RECORD_PATCH_SCHEMAS[resource] if partial else RECORD_SCHEMAS[resource]
    try:
        model = schema.model_validate(payload)
        if partial:
            return model.model_dump(exclude_unset=True)
        return model.model_dump(exclude_none=True)
    except ValidationError as exc:
        messages = [
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors()
        ]
        raise ValueError("; ".join(messages)) from exc