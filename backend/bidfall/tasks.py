from celery import shared_task
from django.utils import timezone
from django.db import transaction
from django.db.models import Q
import logging

from .auctions import finalize_auction_with_winner, AuctionStrategyFactory
from .models import Auction, Bid
from .payment import check_payment_status, cancel_payment

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
                finalize_auction_with_winner(auction)
                auction.status = Auction.Status.FINISHED
                auction.save(update_fields=['status'])
                logger.info(f"Auction #{auction.id} finished")
            except Exception as e:
                logger.error(f"Error during auction processing(finish) #{auction.id}: {str(e)}")
                continue


@shared_task(ignore_result=True)
def update_pending_bids():
    with transaction.atomic():
        pending_bids = Bid.objects.select_for_update(skip_locked=True).filter(
            Q(status=Bid.Status.PENDING),
        )
        for bid in pending_bids:
            try:
                status = check_payment_status(bid.payment_id)["status"]
                if status == "canceled":
                    bid.status = Bid.Status.CANCELED
                    bid.save(update_fields=['status'])
                    logger.info(f"Bid #{bid.id} canceled")
                if status == "waiting_for_capture":
                    bid.status = Bid.Status.HELD
                    bid.save(update_fields=['status'])
                    logger.info(f"Bid #{bid.id} held")

                    auction = bid.auction
                    strategy = AuctionStrategyFactory.get_strategy(auction)
                    try:
                        strategy.validate_bid(auction, bid.bid)
                    except Exception as e:
                        cancel_payment(bid.payment_id)
                        bid.status = Bid.Status.CANCELED
                        bid.save(update_fields=['status'])
                        logger.info(f"Bid #{bid.id} was canceled because of error: {str(e)}")
                        continue
                    strategy.process_bid(auction, bid)
            except Exception as e:
                logger.error(f"Error during pending bid processing #{bid.id}: {str(e)}")
                continue


@shared_task(ignore_result=True)
def process_pending_cancel_bids():
    with transaction.atomic():
        pending_bids = Bid.objects.select_for_update(skip_locked=True).filter(
            Q(status=Bid.Status.PENDING_LOSE),
        )
        for bid in pending_bids:
            try:
                status = cancel_payment(bid.payment_id)["status"]
                if status == "canceled":
                    bid.status = Bid.Status.LOSE
                    bid.save(update_fields=['status'])
                    logger.info(f"Bid #{bid.id} canceled because of lose")
            except Exception as e:
                logger.error(f"Error during pending bid canceling #{bid.id}: {str(e)}")
                continue
