"""Request and response shapes for products and price books."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.core.validation import Reason, Text100

ProductType = Literal["product", "service", "subscription"]
Sku = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._\-]+$"
    ),
]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Unit = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20)]
LongText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=5000)]
TaxRate = Annotated[Decimal, Field(ge=0, le=100, decimal_places=2)]
Price = Annotated[Decimal, Field(ge=0, le=1_000_000_000, decimal_places=2)]
Currency = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProductCreate(_Input):
    sku: Sku = Field(
        description="Product code, unique in your organisation (letters, digits, . _ -)."
    )
    name: Name
    description: LongText | None = None
    product_type: ProductType = "product"
    unit: Unit = "each"
    tax_rate: TaxRate = Decimal("0")


class ProductUpdate(_Input):
    version: int = Field(ge=1)
    sku: Sku | None = None
    name: Name | None = None
    description: LongText | None = None
    product_type: ProductType | None = None
    unit: Unit | None = None
    tax_rate: TaxRate | None = None
    is_active: bool | None = Field(default=None, description="Inactive products can't be quoted.")

    @model_validator(mode="after")
    def _check(self) -> "ProductUpdate":
        if not self.model_fields_set - {"version"}:
            raise ValueError("send at least one field to change")
        for required in ("sku", "name", "product_type", "unit", "tax_rate", "is_active"):
            if required in self.model_fields_set and getattr(self, required) is None:
                raise ValueError(f"{required} cannot be removed")
        return self

    def changes(self) -> dict[str, object]:
        return {k: getattr(self, k) for k in self.model_fields_set if k != "version"}


class ProductRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    sku: str
    name: str
    description: str | None
    product_type: str
    unit: str
    tax_rate: Decimal
    is_active: bool
    created_at: datetime
    updated_at: datetime
    version: int


class ProductPage(BaseModel):
    items: list[ProductRead]
    total: int
    limit: int
    offset: int


class PriceBookCreate(_Input):
    name: Text100
    currency: Currency
    description: Reason | None = None
    is_default: bool = Field(default=False, description="The default book for this currency.")


class PriceBookUpdate(_Input):
    version: int = Field(ge=1)
    name: Text100 | None = None
    description: Reason | None = None
    is_default: bool | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def _check(self) -> "PriceBookUpdate":
        if not self.model_fields_set - {"version"}:
            raise ValueError("send at least one field to change")
        for required in ("name", "is_default", "is_active"):
            if required in self.model_fields_set and getattr(self, required) is None:
                raise ValueError(f"{required} cannot be removed")
        return self

    def changes(self) -> dict[str, object]:
        return {k: getattr(self, k) for k in self.model_fields_set if k != "version"}


class PriceBookRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    currency: str
    description: str | None
    is_default: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime
    version: int


class PriceSet(_Input):
    unit_price: Price


class PriceRead(BaseModel):
    product_id: uuid.UUID
    sku: str
    name: str
    unit: str
    tax_rate: Decimal
    product_active: bool
    unit_price: Decimal
    currency: str
    updated_at: datetime
