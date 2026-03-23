from celery import shared_task
from django.utils import timezone
from django.db import transaction
from django.db.models import Q
import logging

from .models import Auction
from .auctions import determine_and_persist_winner

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
                logger.error(f"Error during auction processing(start) #{auction.id}: {str(e)}")
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
                determine_and_persist_winner(auction)
                auction.status = Auction.Status.FINISHED
                auction.save(update_fields=['status'])
                logger.info(f"Auction #{auction.id} finished")
            except Exception as e:
                logger.error(f"Error during auction processing(finish) #{auction.id}: {str(e)}")
                continue
