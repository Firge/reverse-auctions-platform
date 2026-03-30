import logging
from typing import Dict, Type

from django.db import transaction

from .auctions import AuctionStrategyFactory
from .models import Auction, Bid, PaymentTransaction
from .payment import cancel_payment


logger = logging.getLogger(__name__)


class BasePaymentTransactionHandler:
    def __init__(self, payment: PaymentTransaction):
        self.payment = payment
        self.bid = payment.bid
        self.auction = payment.auction

    def handle_canceled(self):
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement handle_canceled()"
        )

    def handle_held(self):
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement handle_held()"
        )

    def handle_charged(self):
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement handle_charged()"
        )


class PaymentTransactionService:
    _handlers: Dict[str, Type[type[BasePaymentTransactionHandler]]] = {}

    @classmethod
    def register_handler(cls, payment_type: str):
        def decorator(handler_class: Type[type[BasePaymentTransactionHandler]]):
            cls._handlers[payment_type] = handler_class
            return handler_class

        return decorator

    @classmethod
    @transaction.atomic
    def set_canceled(cls, payment: PaymentTransaction):
        handler = cls._handlers[payment.type](payment)
        handler.handle_canceled()

    @classmethod
    @transaction.atomic
    def set_held(cls, payment: PaymentTransaction):
        handler = cls._handlers[payment.type](payment)
        handler.handle_held()

    @classmethod
    @transaction.atomic
    def set_charged(cls, payment: PaymentTransaction):
        handler = cls._handlers[payment.type](payment)
        handler.handle_charged()


@PaymentTransactionService.register_handler(PaymentTransaction.Type.BID_PLACEMENT_HOLD)
class BidPlacementHoldHandler(BasePaymentTransactionHandler):
    def handle_canceled(self):
        self.bid.status = Bid.Status.CANCELED
        self.bid.save()
        logger.info(f"Bid #{self.bid.id} payment canceled")
        self.payment.status = PaymentTransaction.Status.CANCELED
        self.payment.save()

    def handle_held(self):
        logger.info(f"Bid #{self.bid.id} held")

        auction = self.bid.auction
        strategy = AuctionStrategyFactory.get_strategy(auction)
        try:
            strategy.validate_bid(auction, self.bid.bid)
        except Exception as e:
            try:
                cancel_payment(self.payment.payment_id)
                PaymentTransaction.objects.create(
                    user=self.payment.user,
                    bid=self.bid,
                    type=PaymentTransaction.Type.BID_CONCURRENT_RELEASE,
                    payment_id=self.payment.payment_id,
                )
                self.payment.status = PaymentTransaction.Status.HELD
                self.payment.save()
            finally:
                return

        strategy.process_bid(auction, self.bid)
        self.bid.status = Bid.Status.HELD
        self.bid.save()

        self.payment.status = PaymentTransaction.Status.HELD
        self.payment.save()


@PaymentTransactionService.register_handler(PaymentTransaction.Type.BID_CONCURRENT_RELEASE)
class BidConcurrentReleaseHandler(BasePaymentTransactionHandler):
    def handle_canceled(self):
        self.bid.status = Bid.Status.CANCELED
        self.bid.save()
        logger.info(f"Bid #{self.bid.id} canceled because of concurrent changes")
        self.payment.status = PaymentTransaction.Status.CANCELED
        self.payment.save()


@PaymentTransactionService.register_handler(PaymentTransaction.Type.BID_LOSS_RELEASE)
class BidLossReleaseHandler(BasePaymentTransactionHandler):
    def handle_canceled(self):
        self.bid.status = Bid.Status.LOSE
        self.bid.save()
        logger.info(f"Bid #{self.bid.id} canceled because of loss")
        self.payment.status = PaymentTransaction.Status.CANCELED
        self.payment.save()


@PaymentTransactionService.register_handler(PaymentTransaction.Type.BID_WIN_SIGNED_RELEASE)
class BidWinSignedReleaseHandler(BasePaymentTransactionHandler):
    def handle_canceled(self):
        self.bid.status = Bid.Status.RELEASED
        self.bid.save()
        logger.info(f"Bid #{self.bid.id} canceled because of successful signing")
        self.payment.status = PaymentTransaction.Status.CANCELED
        self.payment.save()


@PaymentTransactionService.register_handler(PaymentTransaction.Type.BID_WIN_FORFEIT_CHARGE)
class BidForfeitChargeHandler(BasePaymentTransactionHandler):
    def handle_charged(self):
        self.bid.status = Bid.Status.FORFEIT
        self.bid.save()
        logger.info(f"Bid #{self.bid.id} charged")
        self.payment.status = PaymentTransaction.Status.CHARGED
        self.payment.save()


@PaymentTransactionService.register_handler(PaymentTransaction.Type.AUCTION_CREATION_HOLD)
class AuctionCreationHoldHandler(BasePaymentTransactionHandler):
    def handle_canceled(self):
        self.auction.status = Auction.Status.DRAFT
        self.auction.save()
        logger.info(f"Auction #{self.auction.id} payment canceled")
        self.payment.status = PaymentTransaction.Status.CANCELED
        self.payment.save()

    def handle_held(self):
        self.auction.status = Auction.Status.PUBLISHED
        self.auction.save()
        logger.info(f"Auction #{self.auction.id} payment held")
        self.payment.status = PaymentTransaction.Status.HELD
        self.payment.save()


@PaymentTransactionService.register_handler(PaymentTransaction.Type.AUCTION_SIGNED_RELEASE)
class AuctionSignedReleaseHandler(BasePaymentTransactionHandler):
    def handle_canceled(self):
        self.auction.status = Auction.Status.COMPLETED
        self.auction.save()
        logger.info(f"Auction #{self.auction.id} canceled because of successful signing")
        self.payment.status = PaymentTransaction.Status.CANCELED
        self.payment.save()


@PaymentTransactionService.register_handler(PaymentTransaction.Type.AUCTION_FORFEIT_CHARGE)
class AuctionForfeitChargeHandler(BasePaymentTransactionHandler):
    def handle_charged(self):
        self.auction.status = Auction.Status.CANCELED
        self.auction.save()
        logger.info(f"Auction #{self.auction.id} charged")
        self.payment.status = PaymentTransaction.Status.CHARGED
        self.payment.save()

