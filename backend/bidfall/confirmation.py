import datetime
import os
from typing import List

from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

from .auctions import AuctionStrategyFactory
from .models import ConfirmationFlow, PaymentTransaction
from .payment import cancel_payment, capture_payment


@transaction.atomic
def update_confirmation_flow(confirmation: ConfirmationFlow):
    confirmation = ConfirmationFlow.objects.select_for_update().get(pk=confirmation.pk)
    if confirmation.status != ConfirmationFlow.Status.PENDING:
        return

    auction = confirmation.auction
    current_winner_bid = auction.winner_bid

    creator_payment = PaymentTransaction.objects.get(
        auction=auction,
        type=PaymentTransaction.Type.AUCTION_CREATION_HOLD,
        status=PaymentTransaction.Status.HELD
    )

    def get_winner_payments_for_bids(bids: List) -> QuerySet:
        return PaymentTransaction.objects.filter(
            bid__in=bids,
            type=PaymentTransaction.Type.BID_PLACEMENT_HOLD,
            status=PaymentTransaction.Status.HELD
        )

    if confirmation.creator_signed_at and confirmation.winner_signed_at:
        cancel_payment(creator_payment.payment_id)
        PaymentTransaction.objects.create(
            user=creator_payment.user,
            auction=auction,
            type=PaymentTransaction.Type.AUCTION_SIGNED_RELEASE,
            payment_id=creator_payment.payment_id,
        )

        winner_payment = PaymentTransaction.objects.get(
            bid=current_winner_bid,
            type=PaymentTransaction.Type.BID_PLACEMENT_HOLD,
            status=PaymentTransaction.Status.HELD
        )
        cancel_payment(winner_payment.payment_id)
        PaymentTransaction.objects.create(
            user=winner_payment.user,
            bid=winner_payment.bid,
            type=PaymentTransaction.Type.BID_WIN_SIGNED_RELEASE,
            payment_id=winner_payment.payment_id,
        )

        confirmation.status = ConfirmationFlow.Status.SUCCESS
        confirmation.save(update_fields=['status'])
        return

    if timezone.now() < confirmation.signing_deadline:
        return

    strategy = AuctionStrategyFactory.get_strategy(auction)
    all_winners = strategy.determine_winners(auction)

    if not confirmation.creator_signed_at:
        capture_payment(creator_payment.payment_id)
        PaymentTransaction.objects.create(
            user=creator_payment.user,
            auction=auction,
            type=PaymentTransaction.Type.AUCTION_FORFEIT_CHARGE,
            payment_id=creator_payment.payment_id,
        )

        winner_payments = get_winner_payments_for_bids(all_winners)
        assert winner_payments.count() == len(all_winners)

        for wp in winner_payments:
            cancel_payment(wp.payment_id)
            PaymentTransaction.objects.create(
                user=wp.user,
                bid=wp.bid,
                type=PaymentTransaction.Type.BID_WIN_SIGNED_RELEASE,
                payment_id=wp.payment_id,
            )

        confirmation.status = ConfirmationFlow.Status.FAILED
        confirmation.save(update_fields=['status'])
        return

    if not confirmation.winner_signed_at:
        current_winner_payment = PaymentTransaction.objects.get(
            bid=current_winner_bid,
            type=PaymentTransaction.Type.BID_PLACEMENT_HOLD,
            status=PaymentTransaction.Status.HELD
        )
        capture_payment(current_winner_payment.payment_id)
        PaymentTransaction.objects.create(
            user=current_winner_payment.user,
            bid=current_winner_payment.bid,
            type=PaymentTransaction.Type.BID_WIN_FORFEIT_CHARGE,
            payment_id=current_winner_payment.payment_id,
        )

        remaining_winners = [b for b in all_winners if b != current_winner_bid]

        if not remaining_winners:
            cancel_payment(creator_payment.payment_id)
            PaymentTransaction.objects.create(
                user=creator_payment.user,
                auction=auction,
                type=PaymentTransaction.Type.AUCTION_SIGNED_RELEASE,
                payment_id=creator_payment.payment_id,
            )
            confirmation.status = ConfirmationFlow.Status.FAILED
            confirmation.save(update_fields=['status'])
        else:
            next_winner = remaining_winners[0]
            auction.winner_bid = next_winner
            auction.winner_determined_at = timezone.now()
            auction.save(update_fields=['winner_bid', 'winner_determined_at'])

            time_to_sign = int(os.getenv("TIME_TO_SIGN", 60 * 60 * 24))
            confirmation.signing_deadline = timezone.now() + datetime.timedelta(seconds=time_to_sign)
            confirmation.creator_signed_at = None
            confirmation.winner_signed_at = None
            confirmation.save(update_fields=['signing_deadline', 'creator_signed_at', 'winner_signed_at'])
        return
