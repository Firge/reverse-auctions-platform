import datetime
import os
from abc import ABC, abstractmethod
from typing import List

from django.db import transaction
from django.utils import timezone

from .models import Auction, ReverseEnglishAuction, Bid, PaymentTransaction, ConfirmationFlow
from .payment import cancel_payment


class AuctionStrategy(ABC):
    @abstractmethod
    def validate_bid(self, auction: Auction, bid_amount):
        pass

    @abstractmethod
    def process_bid(self, auction: Auction, bid: Bid):
        pass

    @abstractmethod
    def determine_winners(self, auction, num_winners = 3) -> List[Bid]:
        pass

    @abstractmethod
    def calculate_current_price(self, auction):
        pass


class AuctionStrategyFactory:
    _strategies = {}

    @classmethod
    def register(cls, model_class):
        def decorator(strategy_class):
            cls._strategies[model_class._meta.model_name] = strategy_class
            return strategy_class

        return decorator

    @classmethod
    def get_strategy(cls, auction: Auction) -> AuctionStrategy:
        strategy_class = cls._strategies.get(auction.auction_type.model)
        if not strategy_class:
            raise ValueError(f"No strategy registered for {auction.auction_type.name}")
        return strategy_class()


@AuctionStrategyFactory.register(ReverseEnglishAuction)
class ReverseEnglishAuctionStrategy(AuctionStrategy):
    def validate_bid(self, auction, bid_amount):
        if bid_amount is None:
            raise ValueError("Bid cannot be None")
        if bid_amount > auction.start_price:
            raise ValueError("Bid can not be higher than starting price")
        if auction.current_price is None:
            return
        specific = auction.specific_auction
        if auction.current_price - bid_amount < specific.min_bid_decrement:
            raise ValueError(f"Bid decrement must be at least {specific.min_bid_decrement}")

    def process_bid(self, auction: Auction, bid: Bid):
        auction.current_price = bid.bid
        auction.save(update_fields=['current_price'])

    def determine_winners(self, auction, num_winners = 3):
        bids = auction.bids.filter(status__in=[Bid.Status.HELD, Bid.Status.WON]).order_by('bid', 'id')
        winners = []
        seen_users = set()
        for bid in bids:
            if bid.owner_id not in seen_users:
                seen_users.add(bid.owner_id)
                winners.append(bid)
                if len(winners) == num_winners:
                    break
        return winners

    def calculate_current_price(self, auction):
        return auction.current_price


def finalize_auction_with_winner(auction: Auction, num_winners: int = 3):
    assert transaction.get_connection().in_atomic_block, "Must be called within transaction"

    strategy = AuctionStrategyFactory.get_strategy(auction)
    winner_bids = strategy.determine_winners(auction, num_winners)

    auction.winner_determined_at = timezone.now()
    if winner_bids:
        auction.winner_bid = winner_bids[0]
    else:
        auction.winner_bid = None
    auction.save(update_fields=['winner_bid', 'winner_determined_at'])

    all_held_bids = auction.bids.filter(status=Bid.Status.HELD)

    winner_ids = [bid.id for bid in winner_bids]
    if winner_ids:
        all_held_bids.filter(id__in=winner_ids).update(status=Bid.Status.WON)

    time_to_sign = int(os.getenv("TIME_TO_SIGN", 60 * 60 * 24))
    ConfirmationFlow.objects.create(
        auction=auction,
        signing_deadline=timezone.now() + datetime.timedelta(seconds=time_to_sign),
    )

    for bid in all_held_bids.exclude(id__in=winner_ids):
        original_payment = PaymentTransaction.objects.get(
            bid=bid,
            type=PaymentTransaction.Type.BID_PLACEMENT_HOLD,
            status=PaymentTransaction.Status.HELD
        )
        cancel_payment(original_payment.payment_id)
        PaymentTransaction.objects.create(
            user=original_payment.user,
            bid=bid,
            type=PaymentTransaction.Type.BID_LOSS_RELEASE,
            payment_id=original_payment.payment_id,
        )
