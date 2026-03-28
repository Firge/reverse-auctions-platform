from celery import shared_task
from django.utils import timezone
from django.db import transaction
from django.db.models import Q
import logging

from .auctions import finalize_auction_with_winner
from .confirmation import update_confirmation_flow
from .models import Auction, PaymentTransaction, ConfirmationFlow
from .payment import check_payment_status
from .payment_transaction import PaymentTransactionService

logger = logging.getLogger(__name__)


@shared_task(ignore_result=True)
def start_published_auctions():
    now = timezone.now()

    with transaction.atomic():
        expired_auctions = Auction.objects.select_for_update(skip_locked=True).filter(
            Q(status=Auction.Status.PUBLISHED),
            start_date__lte=now
        )
        for auction in expired_auctions:
            try:
                auction.status = Auction.Status.ACTIVE
                auction.save(update_fields=['status'])
                logger.info(f"Auction #{auction.id} started")
            except Exception as e:
                logger.exception(f"Error during auction processing(start) #{auction.id}: {str(e)}")
                continue


@shared_task(ignore_result=True)
def finish_expired_auctions():
    now = timezone.now()

    with transaction.atomic():
        expired_auctions = Auction.objects.select_for_update(skip_locked=True).filter(
            Q(status=Auction.Status.ACTIVE),
            end_date__lte=now
        )
        for auction in expired_auctions:
            try:
                finalize_auction_with_winner(auction)
                auction.status = Auction.Status.FINISHED
                auction.save(update_fields=['status'])
                logger.info(f"Auction #{auction.id} finished")
            except Exception as e:
                logger.exception(f"Error during auction processing(finish) #{auction.id}: {str(e)}")
                continue


@shared_task(ignore_result=True)
def process_pending_payments():
    with transaction.atomic():
        pending_payments = PaymentTransaction.objects.select_for_update(skip_locked=True).filter(
            status=PaymentTransaction.Status.PENDING,
        )
        payment: PaymentTransaction
        for payment in pending_payments:
            try:
                status = check_payment_status(payment.payment_id)["status"]
                if status == "canceled":
                    PaymentTransactionService.set_canceled(payment)
                elif status == "waiting_for_capture":
                    PaymentTransactionService.set_held(payment)
                elif status == "succeeded":
                    PaymentTransactionService.set_charged(payment)
            except Exception as e:
                logger.exception(f"Error during payment processing #{payment.id}: {str(e)}")
                continue


@shared_task(ignore_result=True)
def process_finished_confirmations():
    now = timezone.now()

    expired_confirmation = ConfirmationFlow.objects.filter(
        status=ConfirmationFlow.Status.PENDING,
        signing_deadline__lte=now
    )
    for expired_confirmation in expired_confirmation:
        try:
            update_confirmation_flow(expired_confirmation)
        except Exception as e:
            logger.exception(f"Error during confirmation processing #{expired_confirmation}: {str(e)}")
            continue
