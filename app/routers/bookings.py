import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.deps import get_current_user
from app.models import Booking, BookingStatus, CentreTest, DiagnosticCentre, User
from app.schemas import BookingCreate, BookingDetailOut, BookingOut, Page

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/bookings", tags=["bookings"])


def get_own_booking(db: Session, booking_id: int, user: User, lock: bool = False) -> Booking:
    query = select(Booking).where(Booking.id == booking_id, Booking.user_id == user.id)
    if lock:
        query = query.with_for_update()
    booking = db.scalar(query)
    # someone else's booking gets the same 404 as one that doesn't exist, no id probing
    if booking is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Booking not found")
    return booking


@router.post("", response_model=BookingOut, status_code=status.HTTP_201_CREATED)
def create_booking(
    data: BookingCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    offering = db.scalar(
        select(CentreTest).where(CentreTest.centre_id == data.centre_id, CentreTest.test_id == data.test_id)
    )
    if offering is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This centre does not offer that test")

    duplicate = db.scalar(
        select(Booking.id).where(
            Booking.user_id == user.id,
            Booking.centre_id == data.centre_id,
            Booking.test_id == data.test_id,
            Booking.appointment_at == data.appointment_at,
            Booking.status.in_([BookingStatus.PENDING, BookingStatus.CONFIRMED]),
        )
    )
    if duplicate:
        raise HTTPException(status.HTTP_409_CONFLICT, "You already have this booking")

    booking = Booking(
        user_id=user.id,
        centre_id=data.centre_id,
        test_id=data.test_id,
        appointment_at=data.appointment_at,
        amount=offering.price,
        status=BookingStatus.PENDING,
    )
    db.add(booking)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "You already have this booking")

    logger.info("booking created", extra={"booking_id": booking.id, "user_id": user.id})
    return booking


@router.get("", response_model=Page[BookingOut])
def list_my_bookings(
    status_filter: BookingStatus | None = Query(default=None, alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = select(Booking).where(Booking.user_id == user.id)
    if status_filter:
        query = query.where(Booking.status == status_filter)

    total = db.scalar(select(func.count()).select_from(query.subquery()))
    bookings = db.scalars(
        query.order_by(Booking.id.desc()).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return Page(items=bookings, total=total, page=page, page_size=page_size)


@router.get("/{booking_id}", response_model=BookingDetailOut)
def get_booking(
    booking_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    booking = db.scalar(
        select(Booking)
        .where(Booking.id == booking_id, Booking.user_id == user.id)
        .options(
            selectinload(Booking.payments),
            selectinload(Booking.test),
            selectinload(Booking.centre).selectinload(DiagnosticCentre.offerings).selectinload(CentreTest.test),
        )
    )
    if booking is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Booking not found")
    return booking


@router.post("/{booking_id}/cancel", response_model=BookingOut)
def cancel_booking(
    booking_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    booking = get_own_booking(db, booking_id, user, lock=True)
    if booking.status == BookingStatus.CANCELLED:
        raise HTTPException(status.HTTP_409_CONFLICT, "Booking is already cancelled")

    booking.status = BookingStatus.CANCELLED
    db.commit()
    logger.info("booking cancelled", extra={"booking_id": booking.id, "user_id": user.id})
    return booking
