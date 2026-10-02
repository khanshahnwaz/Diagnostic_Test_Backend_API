from datetime import datetime, timezone
from decimal import Decimal
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models import BookingStatus, PaymentStatus

T = TypeVar("T")


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


# auth
class SignupIn(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=8, max_length=64)

    @field_validator("full_name")
    @classmethod
    def strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("full_name cannot be blank")
        return v


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=64)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(ORMModel):
    id: int
    email: EmailStr
    full_name: str
    is_admin: bool


# centres and tests
class DiagnosticTestOut(ORMModel):
    id: int
    name: str
    description: str | None


class OfferingOut(ORMModel):
    test: DiagnosticTestOut
    price: Decimal


class CentreCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    location: str = Field(min_length=1, max_length=120)
    address: str | None = Field(default=None, max_length=255)


class CentreOut(ORMModel):
    id: int
    name: str
    location: str
    address: str | None
    offerings: list[OfferingOut]


class OfferingCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=500)
    price: Decimal = Field(gt=0, max_digits=10, decimal_places=2)


# bookings
class BookingCreate(BaseModel):
    centre_id: int
    test_id: int
    appointment_at: datetime

    @field_validator("appointment_at")
    @classmethod
    def must_be_future(cls, v: datetime) -> datetime:
        # naive datetimes are treated as UTC
        if v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)
        v = v.astimezone(timezone.utc)
        if v <= datetime.now(timezone.utc):
            raise ValueError("appointment_at must be in the future")
        return v


class PaymentOut(ORMModel):
    id: int
    booking_id: int
    amount: Decimal
    status: PaymentStatus
    reference: str
    created_at: datetime


class BookingOut(ORMModel):
    id: int
    user_id: int
    centre_id: int
    test_id: int
    appointment_at: datetime
    amount: Decimal
    status: BookingStatus
    created_at: datetime


class BookingDetailOut(BookingOut):
    centre: CentreOut
    test: DiagnosticTestOut
    payments: list[PaymentOut]


# payments
class PaymentCreate(BaseModel):
    booking_id: int
    # force a result for demos and tests, leave empty for a random one
    outcome: Literal["SUCCESS", "FAILED"] | None = None
    # leaves the payment PENDING so the result has to arrive through the webhook
    async_mode: bool = False


class WebhookIn(BaseModel):
    event_id: str = Field(min_length=1, max_length=128)
    payment_reference: str = Field(min_length=1, max_length=64)
    status: Literal["SUCCESS", "FAILED"]


class WebhookOut(BaseModel):
    status: Literal["processed", "duplicate", "ignored"]
