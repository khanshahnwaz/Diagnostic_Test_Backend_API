import logging

from app.models import BookingStatus, Payment, PaymentStatus

logger = logging.getLogger(__name__)


def apply_payment_result(payment: Payment, result: PaymentStatus) -> bool:
    # only a PENDING payment can move, anything already settled stays as it is
    if payment.status != PaymentStatus.PENDING:
        return False

    payment.status = result
    booking = payment.booking

    if result == PaymentStatus.SUCCESS:
        if booking.status in (BookingStatus.PENDING, BookingStatus.FAILED):
            booking.status = BookingStatus.CONFIRMED
        else:
            # paid for a booking that was cancelled (or already confirmed), needs a refund in real life
            logger.warning(
                "payment succeeded but booking not confirmable",
                extra={"payment_id": payment.id, "booking_id": booking.id, "booking_status": booking.status.value},
            )
    elif booking.status == BookingStatus.PENDING:
        booking.status = BookingStatus.FAILED

    return True
