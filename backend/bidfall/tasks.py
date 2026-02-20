from celery import shared_task
from django.utils import timezone
from django.db import transaction
from django.db.models import Q
import logging

from .models import Auction


logger = logging.getLogger(__name__)


@shared_task(ignore_result=True)
def close_expired_auctions_concurrent():
    now = timezone.now()

    expired_auctions = Auction.objects.filter(
        Q(status=Auction.Status.ACTIVE),
        end_date__lte=now
    )

    with transaction.atomic():
        for auction in expired_auctions:
            try:
                auction.status = Auction.Status.FINISHED
                auction.save(update_fields=['status'])
                logger.info(f"Auction #{auction.id} finished")
            except Exception as e:
                logger.error(f"Error during auction processing #{auction.id}: {str(e)}")
                continue
