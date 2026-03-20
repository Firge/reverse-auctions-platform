from abc import ABC, abstractmethod

from django.db import transaction

from .models import Auction, ReverseEnglishAuction, Bid


class AuctionStrategy(ABC):
    @abstractmethod
    def validate_bid(self, auction: Auction, bid_amount):
        pass

    @abstractmethod
    def process_bid(self, auction, bid_amount, user, comment):
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

    def process_bid(self, auction, bid_amount, user, comment):
        with transaction.atomic():
            auction.current_price = bid_amount
            auction.save(update_fields=['current_price'])
            Bid.objects.create(auction=auction, owner=user, bid=bid_amount, comment=comment)

    def determine_winner(self, auction):
        return auction.bids.order_by('bid').first()

    def calculate_current_price(self, auction):
        return auction.current_price
