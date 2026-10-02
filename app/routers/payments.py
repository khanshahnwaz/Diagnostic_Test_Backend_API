import logging
import random
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.deps import get_current_user
from app.models import BookingStatus, Payment, PaymentStatus, User, WebhookEvent
from app.routers.bookings import get_own_booking
from app.schemas import PaymentCreate, PaymentOut, WebhookIn, WebhookOut
from app.security import verify_webhook_signature
from app.services.payments import apply_payment_result

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/payments", tags=["payments"])


@router.post("/", response_model=PaymentOut, status_code=status.HTTP_201_CREATED)
def create_payment(
    data: PaymentCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # lock the booking row so two parallel pay calls can't both go through
    booking = get_own_booking(db, data.booking_id, user, lock=True)

    if booking.status not in (BookingStatus.PENDING, BookingStatus.FAILED):
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Booking is {booking.status.value} and cannot be paid"
        )
    if any(p.status == PaymentStatus.PENDING for p in booking.payments):
        raise HTTPException(status.HTTP_409_CONFLICT, "A payment for this booking is already in progress")

    payment = Payment(
        booking_id=booking.id,
        amount=booking.amount,
        status=PaymentStatus.PENDING,
        reference=f"pay_{uuid.uuid4().hex}",
    )
    db.add(payment)
    db.flush()

    if not data.async_mode:
        if data.outcome:
            result = PaymentStatus(data.outcome)
        else:
            ok = random.random() < settings.payment_success_rate
            result = PaymentStatus.SUCCESS if ok else PaymentStatus.FAILED
        apply_payment_result(payment, result)

    db.commit()
    logger.info(
        "payment created",
        extra={"payment_id": payment.id, "booking_id": booking.id, "payment_status": payment.status.value},
    )
    return payment


@router.post("/webhook/", response_model=WebhookOut)
async def payment_webhook(request: Request, db: Session = Depends(get_db)):
    # signature is computed over the raw bytes so read them before any parsing
    raw = await request.body()
    if not verify_webhook_signature(raw, request.headers.get("X-Signature")):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid webhook signature")

    try:
        event = WebhookIn.model_validate_json(raw)
    except ValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, exc.errors(include_url=False, include_context=False))

    # seen this event before? ack it and do nothing
    if db.scalar(select(WebhookEvent.id).where(WebhookEvent.event_id == event.event_id)):
        logger.info("duplicate webhook", extra={"event_id": event.event_id})
        return WebhookOut(status="duplicate")

    payment = db.scalar(
        select(Payment).where(Payment.reference == event.payment_reference).with_for_update()
    )
    if payment is None:
        # not recorded as processed, so the provider's retry can succeed later
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown payment reference")

    applied = apply_payment_result(payment, PaymentStatus(event.status))
    outcome = "processed" if applied else "ignored"
    db.add(
        WebhookEvent(
            event_id=event.event_id,
            payment_reference=event.payment_reference,
            payload=event.model_dump(),
            outcome=outcome,
        )
    )
    try:
        # event row and payment update land in one transaction
        db.commit()
    except IntegrityError:
        # same event_id slipped in between our check and the insert
        db.rollback()
        return WebhookOut(status="duplicate")

    logger.info(
        "webhook handled",
        extra={"event_id": event.event_id, "payment_id": payment.id, "outcome": outcome},
    )
    return WebhookOut(status=outcome)
