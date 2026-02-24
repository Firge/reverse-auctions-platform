from decimal import Decimal
from abc import ABC, abstractmethod

from django.db import transaction
from django.utils import timezone

from .models import Auction, ReverseEnglishAuction, Bid


class AuctionStrategy(ABC):
    @abstractmethod
    def validate_bid(self, auction: Auction, bid_amount):
        pass

    @abstractmethod
    def process_bid(self, auction, bid_amount, user):
        pass

    @abstractmethod
    def determine_winner(self, auction):
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


def determine_and_persist_winner(auction: Auction):
    if auction.status not in (Auction.Status.FINISHED, Auction.Status.CLOSED):
        return None

    strategy = AuctionStrategyFactory.get_strategy(auction)
    winner_bid = strategy.determine_winner(auction)

    winner_id = winner_bid.id if winner_bid else None
    update_fields = []
    if auction.winner_bid_id != winner_id:
        auction.winner_bid = winner_bid
        update_fields.append("winner_bid")
    if auction.winner_determined_at is None or "winner_bid" in update_fields:
        auction.winner_determined_at = timezone.now()
        update_fields.append("winner_determined_at")
    if update_fields:
        auction.save(update_fields=update_fields)
    return winner_bid


@AuctionStrategyFactory.register(ReverseEnglishAuction)
class ReverseEnglishAuctionStrategy(AuctionStrategy):
    def validate_bid(self, auction, bid_amount):
        if bid_amount is None:
            raise ValueError("Bid cannot be None")
        if bid_amount > auction.start_price:
            raise ValueError("Bid can not be higher than starting price")
        if auction.current_price is None:
            return
        if bid_amount >= auction.current_price:
            raise ValueError("Bid must be lower than current price")
        specific = auction.specific_auction
        if specific and (auction.current_price - bid_amount) < specific.min_bid_decrement:
            raise ValueError(
                f"Bid decrement must be at least {specific.min_bid_decrement}"
            )

    def process_bid(self, auction, bid_amount, user, comment=""):
        with transaction.atomic():
            amount = Decimal(str(bid_amount))
            auction.current_price = amount
            auction.save(update_fields=['current_price'])
            Bid.objects.create(
                auction=auction,
                owner=user,
                bid=amount,
                comment=comment or "",
            )

    def determine_winner(self, auction):
        return auction.bids.order_by('bid', 'id').first()

    def calculate_current_price(self, auction):
        return auction.current_price
