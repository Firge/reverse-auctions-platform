import os
import uuid
import logging
from decimal import Decimal

from yookassa import Configuration, Payment

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

Configuration.configure(account_id=os.getenv('YOOKASSA_ACCOUNT_ID'), secret_key=os.getenv('YOOKASSA_SECRET_KEY'))


def freeze_funds(participant_id: str, auction_id: str, amount: Decimal = 5000.00, description: str = "No data") -> dict:
    idempotence_key = str(uuid.uuid4())

    payment_data = {
        "amount": {
            "value": f"{amount:.2f}",
            "currency": "RUB"
        },
        "capture": False,
        "description": description,
        "metadata": {
            "auction_id": auction_id,
            "participant_id": participant_id,
            "purpose": "auction_participation"
        },
        "confirmation": {
            "type": "redirect",
            "return_url": f"http://localhost:5173/auction/{auction_id}"
        },
    }

    try:
        payment = Payment.create(payment_data, idempotence_key)
        logger.info(f"Payment created: {payment.id}, status: {payment.status}")

        return {
            "payment_id": payment.id,
            "confirmation_url": payment.confirmation.confirmation_url
        }

    except Exception as e:
        logger.error(f"Error during payment creating: {e}")
        raise


def check_payment_status(payment_id: str) -> dict:
    try:
        payment = Payment.find_one(payment_id)
        logger.info(f"Payment {payment_id}: status = {payment.status}")
        return {
            "id": payment.id,
            "status": payment.status,
            "paid": payment.paid,
            "amount": payment.amount.value,
            "metadata": payment.metadata
        }
    except Exception as e:
        logger.error(f"Error during payment fetching: {e}")
        raise


def cancel_payment(payment_id: str) -> dict:
    try:
        payment = Payment.cancel(payment_id)
        logger.info(f"Payment {payment_id} canceled. Status: {payment.status}")
        return {
            "id": payment.id,
            "status": payment.status,
            "paid": payment.paid,
            "amount": payment.amount.value,
            "metadata": payment.metadata
        }
    except Exception as e:
        logger.error(f"Error during payment canceling: {e}")
        raise
