from abc import ABC, abstractmethod

from django.contrib.contenttypes.models import ContentType
from django.db import transaction

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
            content_type = ContentType.objects.get_for_model(model_class)
            cls._strategies[content_type.id] = strategy_class
            return strategy_class
        return decorator

    @classmethod
    def get_strategy(cls, auction: Auction) -> AuctionStrategy:
        strategy_class = cls._strategies.get(auction.auction_type.id)
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
        if bid_amount >= auction.current_price:
            raise ValueError("Bid must be lower than current price")

    def process_bid(self, auction, bid_amount, user):
        with transaction.atomic():
            auction.current_price = bid_amount
            auction.save()
            Bid.objects.create(auction=auction, owner=user, bid=bid_amount)

    def determine_winner(self, auction):
        return auction.bids.order_by('-bid').first()

    def calculate_current_price(self, auction):
        return auction.current_price



