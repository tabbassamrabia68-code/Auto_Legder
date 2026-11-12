from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class CommerceModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SupplierCreate(CommerceModel):
    supplier_name: str = Field(min_length=1, max_length=150)
    phone: str | None = Field(default=None, max_length=30)
    email: str | None = Field(default=None, max_length=150, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

    @field_validator("supplier_name", mode="before")
    @classmethod
    def strip_name(cls, value):
        return value.strip() if isinstance(value, str) else value


class SupplierPatch(CommerceModel):
    supplier_name: str | None = Field(default=None, min_length=1, max_length=150)
    phone: str | None = Field(default=None, max_length=30)
    email: str | None = Field(default=None, max_length=150, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

    @field_validator("supplier_name", mode="before")
    @classmethod
    def strip_name(cls, value):
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def require_changes(self):
        if not self.model_fields_set:
            raise ValueError("Provide at least one supplier field to update.")
        if "supplier_name" in self.model_fields_set and self.supplier_name is None:
            raise ValueError("supplier_name cannot be null.")
        return self


class CustomerCreate(CommerceModel):
    customer_name: str = Field(min_length=1, max_length=150)
    phone: str | None = Field(default=None, max_length=30)
    email: str | None = Field(default=None, max_length=150, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

    @field_validator("customer_name", mode="before")
    @classmethod
    def strip_name(cls, value):
        return value.strip() if isinstance(value, str) else value


class CustomerPatch(CommerceModel):
    customer_name: str | None = Field(default=None, min_length=1, max_length=150)
    phone: str | None = Field(default=None, max_length=30)
    email: str | None = Field(default=None, max_length=150, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

    @field_validator("customer_name", mode="before")
    @classmethod
    def strip_name(cls, value):
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def require_changes(self):
        if not self.model_fields_set:
            raise ValueError("Provide at least one customer field to update.")
        if "customer_name" in self.model_fields_set and self.customer_name is None:
            raise ValueError("customer_name cannot be null.")
        return self


class PartnerStatusUpdate(CommerceModel):
    is_active: bool


class PurchaseItemInput(CommerceModel):
    vehicle_id: int = Field(gt=0)
    purchase_price: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    condition_at_purchase: Literal[
        "UNKNOWN", "NEW", "EXCELLENT", "GOOD", "FAIR", "POOR", "DAMAGED"
    ] = "UNKNOWN"


class InitialPaymentInput(CommerceModel):
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    payment_method: Literal[
        "CASH", "BANK_TRANSFER", "CARD", "CHEQUE", "MOBILE_WALLET", "OTHER"
    ]
    payment_status: Literal["COMPLETED", "PENDING"] = "COMPLETED"


class PurchaseCreate(CommerceModel):
    supplier_id: int = Field(gt=0)
    purchase_date: date
    purchase_reference: str | None = Field(default=None, min_length=1, max_length=50)
    items: list[PurchaseItemInput] = Field(min_length=1, max_length=100)
    initial_payment: InitialPaymentInput | None = None

    @field_validator("purchase_reference", mode="before")
    @classmethod
    def strip_reference(cls, value):
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def ensure_unique_vehicles(self):
        vehicle_ids = [item.vehicle_id for item in self.items]
        if len(vehicle_ids) != len(set(vehicle_ids)):
            raise ValueError("A vehicle may appear only once in a purchase.")
        return self


class SaleItemInput(CommerceModel):
    vehicle_id: int = Field(gt=0)
    selling_price: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    discount_amount: Decimal = Field(default=Decimal("0.00"), ge=0, max_digits=12, decimal_places=2)
    tax_amount: Decimal = Field(default=Decimal("0.00"), ge=0, max_digits=12, decimal_places=2)

    @model_validator(mode="after")
    def validate_line(self):
        if self.discount_amount > self.selling_price:
            raise ValueError("discount_amount cannot exceed selling_price.")
        if self.tax_amount != Decimal("0.00"):
            raise ValueError("Tax is disabled; tax_amount must be 0.00.")
        return self


class SaleCreate(CommerceModel):
    customer_id: int = Field(gt=0)
    sale_date: date
    sale_reference: str | None = Field(default=None, min_length=1, max_length=50)
    items: list[SaleItemInput] = Field(min_length=1, max_length=100)
    initial_payment: InitialPaymentInput | None = None

    @field_validator("sale_reference", mode="before")
    @classmethod
    def strip_reference(cls, value):
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def ensure_unique_vehicles(self):
        vehicle_ids = [item.vehicle_id for item in self.items]
        if len(vehicle_ids) != len(set(vehicle_ids)):
            raise ValueError("A vehicle may appear only once in a sale.")
        return self


class PaymentCreate(CommerceModel):
    purchase_id: int | None = Field(default=None, gt=0)
    sale_id: int | None = Field(default=None, gt=0)
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    payment_method: Literal[
        "CASH", "BANK_TRANSFER", "CARD", "CHEQUE", "MOBILE_WALLET", "OTHER"
    ]
    payment_status: Literal["COMPLETED", "PENDING", "FAILED"] = "COMPLETED"
    external_reference: str | None = Field(default=None, max_length=120)
    idempotency_key: str = Field(min_length=1, max_length=120)

    @model_validator(mode="after")
    def exactly_one_parent(self):
        if (self.purchase_id is None) == (self.sale_id is None):
            raise ValueError("Provide exactly one of purchase_id or sale_id.")
        return self

    @field_validator("idempotency_key", mode="before")
    @classmethod
    def strip_idempotency_key(cls, value):
        if isinstance(value, str):
            value = value.strip()
            if not value:
                raise ValueError("idempotency_key cannot be blank.")
        return value


class PaymentStatusUpdate(CommerceModel):
    payment_status: Literal["COMPLETED", "FAILED", "VOIDED"]


class InventoryOnboard(CommerceModel):
    source_note: str = Field(min_length=1, max_length=500)
    source_reference: str | None = Field(default=None, max_length=120)
    vehicle_condition: Literal[
        "UNKNOWN", "NEW", "EXCELLENT", "GOOD", "FAIR", "POOR", "DAMAGED"
    ] = "UNKNOWN"
    asking_price: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)

    @field_validator("source_note", mode="before")
    @classmethod
    def strip_source_note(cls, value):
        return value.strip() if isinstance(value, str) else value


class InventoryStatusUpdate(CommerceModel):
    stock_status: Literal["AVAILABLE", "UNDER_MAINTENANCE"]


class SupplierResponse(BaseModel):
    supplier_id: int
    supplier_name: str
    phone: str | None = None
    email: str | None = None
    is_active: bool = True


class CustomerResponse(BaseModel):
    customer_id: int
    customer_name: str
    phone: str | None = None
    email: str | None = None
    is_active: bool = True


class PurchaseItemResponse(BaseModel):
    purchase_item_id: int
    vehicle_id: int
    vin: str
    registration_no: str
    purchase_price: Decimal
    condition_at_purchase: str


class SaleItemResponse(BaseModel):
    sale_item_id: int
    vehicle_id: int
    vin: str
    registration_no: str
    selling_price: Decimal
    discount_amount: Decimal
    tax_amount: Decimal
    line_total: Decimal


class PurchaseResponse(BaseModel):
    purchase_id: int
    supplier_id: int | None
    supplier_name: str | None = None
    purchase_date: date
    purchase_reference: str | None = None
    purchase_status: str | None = None
    received_at: datetime | None = None
    total_amount: Decimal | None = None
    paid_amount: Decimal
    balance_due: Decimal
    currency: Literal["PKR"] = "PKR"
    items: list[PurchaseItemResponse] = Field(default_factory=list)


class SaleResponse(BaseModel):
    sale_id: int
    customer_id: int | None
    customer_name: str | None = None
    sale_date: date
    sale_reference: str | None = None
    sale_status: str | None = None
    total_amount: Decimal | None = None
    paid_amount: Decimal
    balance_due: Decimal
    currency: Literal["PKR"] = "PKR"
    items: list[SaleItemResponse] = Field(default_factory=list)


class PaymentResponse(BaseModel):
    payment_id: int
    payment_reference: str
    purchase_id: int | None
    sale_id: int | None
    amount: Decimal
    currency: Literal["PKR"] = "PKR"
    payment_kind: str
    payment_status: str
    payment_method: str
    payment_date: datetime
    external_reference: str | None = None


class InventoryResponse(BaseModel):
    vehicle_id: int
    vin: str
    registration_no: str
    brand: str
    model: str
    model_year: int
    stock_status: str
    vehicle_condition: str
    asking_price: Decimal | None = None
    acquisition_cost: Decimal | None = None
    reserved_for_sale_id: int | None = None
    sold_sale_id: int | None = None
    source_note: str | None = None
    source_reference: str | None = None


class SupplierListResponse(BaseModel):
    suppliers: list[SupplierResponse]


class CustomerListResponse(BaseModel):
    customers: list[CustomerResponse]


class PurchaseListResponse(BaseModel):
    purchases: list[PurchaseResponse]


class SaleListResponse(BaseModel):
    sales: list[SaleResponse]


class PaymentListResponse(BaseModel):
    payments: list[PaymentResponse]


class InventoryListResponse(BaseModel):
    vehicles: list[InventoryResponse]
    total: int
    acquisition_valuation: Decimal
    asking_valuation: Decimal
