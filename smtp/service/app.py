import os
import signal
import smtplib
import sys
import time
from io import BytesIO
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import make_msgid
from typing import Dict, List

import psycopg
from psycopg.rows import dict_row
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

RUNNING = True
HEARTBEAT_PATH = "/tmp/email_worker_heartbeat"
PDF_FONT_NAME = "DejaVuSans"
PDF_FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
_PDF_FONT_READY = False


def _on_signal(_signum, _frame):
    global RUNNING
    RUNNING = False


signal.signal(signal.SIGINT, _on_signal)
signal.signal(signal.SIGTERM, _on_signal)


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    db_name: str = os.getenv("DB_NAME", "catalog")
    db_user: str = os.getenv("DB_USER", "catalog")
    db_password: str = os.getenv("DB_PASSWORD", "catalog")
    db_host: str = os.getenv("DB_HOST", "postgres")
    db_port: int = int(os.getenv("DB_PORT", "5432"))
    poll_interval_seconds: int = int(os.getenv("POLL_INTERVAL_SECONDS", "45"))
    max_retry_attempts: int = int(os.getenv("MAX_RETRY_ATTEMPTS", "6"))
    retry_base_seconds: int = int(os.getenv("RETRY_BASE_SECONDS", "60"))
    lookback_days: int = int(os.getenv("LOOKBACK_DAYS", "30"))

    smtp_host: str = os.getenv("SMTP_HOST", "postfix_relay")
    smtp_port: int = int(os.getenv("SMTP_PORT", "25"))
    smtp_user: str = os.getenv("SMTP_USERNAME", "")
    smtp_password: str = os.getenv("SMTP_PASSWORD", "")
    smtp_from: str = os.getenv("SMTP_FROM", "no-reply@bebra.works")
    smtp_use_starttls: bool = env_bool("SMTP_USE_STARTTLS", False)
    smtp_use_ssl: bool = env_bool("SMTP_USE_SSL", False)
    smtp_timeout: int = int(os.getenv("SMTP_TIMEOUT_SECONDS", "20"))

    frontend_auction_url: str = os.getenv(
        "FRONTEND_AUCTION_URL_TEMPLATE",
        "http://127.0.0.1:5173/auctions/{auction_id}",
    )

    @property
    def dsn(self) -> str:
        return (
            f"dbname={self.db_name} user={self.db_user} password={self.db_password} "
            f"host={self.db_host} port={self.db_port}"
        )


def log(level: str, message: str, **kwargs):
    payload = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "level": level,
        "message": message,
        **kwargs,
    }
    print(payload, flush=True)


def read_schema() -> str:
    path = os.path.join(os.path.dirname(__file__), "schema.sql")
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def ensure_schema(conn: psycopg.Connection):
    conn.execute(read_schema())
    conn.commit()


def next_retry_at_sql(base_seconds: int) -> str:
    return (
        "NOW() + make_interval(secs => LEAST(86400, %s * "
        "CAST(POWER(2, GREATEST(attempts, 0)) AS INTEGER)))"
    ) % base_seconds


def get_candidate_auctions(conn: psycopg.Connection, lookback_days: int) -> List[Dict]:
    sql = """
        SELECT
            a.id AS auction_id,
            a.title AS auction_title,
            a.winner_bid_id,
            a.winner_determined_at,
            a.owner_id AS initiator_user_id,
            initiator.email AS initiator_email,
            b.owner_id AS winner_user_id,
            winner.email AS winner_email,
            b.bid AS winner_bid_amount
        FROM bidfall_auction a
        JOIN bidfall_bid b ON b.id = a.winner_bid_id
        JOIN auth_user initiator ON initiator.id = a.owner_id
        JOIN auth_user winner ON winner.id = b.owner_id
        WHERE a.status = 'FINISHED'
          AND a.winner_bid_id IS NOT NULL
          AND a.winner_determined_at IS NOT NULL
          AND a.winner_determined_at >= NOW() - make_interval(days => %(lookback_days)s)
          AND initiator.email <> ''
          AND winner.email <> ''
        ORDER BY a.winner_determined_at ASC, a.id ASC;
    """
    return conn.execute(sql, {"lookback_days": lookback_days}).fetchall()


def get_auction_lots(conn: psycopg.Connection, auction_id: int) -> List[Dict]:
    sql = """
        SELECT
            ai.catalog_item_id AS item_id,
            ci.code AS item_code,
            ci.name AS item_name,
            ci.unit AS item_unit,
            ai.quantity AS item_quantity
        FROM auction_items ai
        JOIN catalog_items ci ON ci.id = ai.catalog_item_id
        WHERE ai.auction_id = %(auction_id)s
        ORDER BY ai.id ASC;
    """
    return conn.execute(sql, {"auction_id": auction_id}).fetchall()


def upsert_notification_pending(
    conn: psycopg.Connection,
    auction_id: int,
    winner_bid_id: int,
    recipient_type: str,
    recipient_email: str,
) -> None:
    sql = """
        INSERT INTO smtp_notifications
            (auction_id, winner_bid_id, recipient_type, recipient_email, status)
        VALUES
            (%(auction_id)s, %(winner_bid_id)s, %(recipient_type)s, %(recipient_email)s, 'pending')
        ON CONFLICT (auction_id, winner_bid_id, recipient_type)
        DO NOTHING;
    """
    conn.execute(
        sql,
        {
            "auction_id": auction_id,
            "winner_bid_id": winner_bid_id,
            "recipient_type": recipient_type,
            "recipient_email": recipient_email,
        },
    )


def get_notification_state(
    conn: psycopg.Connection,
    auction_id: int,
    winner_bid_id: int,
    recipient_type: str,
) -> Dict:
    sql = """
        SELECT id, status, attempts, next_retry_at
        FROM smtp_notifications
        WHERE auction_id = %(auction_id)s
          AND winner_bid_id = %(winner_bid_id)s
          AND recipient_type = %(recipient_type)s;
    """
    return conn.execute(
        sql,
        {
            "auction_id": auction_id,
            "winner_bid_id": winner_bid_id,
            "recipient_type": recipient_type,
        },
    ).fetchone()


def mark_failed(
    conn: psycopg.Connection,
    notification_id: int,
    error_text: str,
    retry_base_seconds: int,
):
    sql = f"""
        UPDATE smtp_notifications
        SET status = 'failed',
            attempts = attempts + 1,
            last_error = %(error)s,
            next_retry_at = {next_retry_at_sql(retry_base_seconds)},
            updated_at = NOW()
        WHERE id = %(id)s;
    """
    conn.execute(sql, {"id": notification_id, "error": error_text[:2000]})


def mark_sent(conn: psycopg.Connection, notification_id: int, message_id: str):
    sql = """
        UPDATE smtp_notifications
        SET status = 'sent',
            sent_at = NOW(),
            last_error = NULL,
            message_id = %(message_id)s,
            next_retry_at = NULL,
            updated_at = NOW()
        WHERE id = %(id)s;
    """
    conn.execute(sql, {"id": notification_id, "message_id": message_id})


def should_send(state: Dict, max_retry_attempts: int) -> bool:
    if state["status"] == "sent":
        return False
    if state["attempts"] >= max_retry_attempts:
        return False
    if state["next_retry_at"] is None:
        return True
    return state["next_retry_at"] <= datetime.now(timezone.utc)


def _ensure_pdf_font() -> str:
    global _PDF_FONT_READY
    if _PDF_FONT_READY:
        return PDF_FONT_NAME
    if os.path.exists(PDF_FONT_PATH):
        pdfmetrics.registerFont(TTFont(PDF_FONT_NAME, PDF_FONT_PATH))
        _PDF_FONT_READY = True
        return PDF_FONT_NAME
    return "Helvetica"


def _draw_wrapped_line(pdf: canvas.Canvas, text: str, x: float, y: float, max_width: float, line_height: float, font_name: str, font_size: int) -> float:
    words = (text or "").split()
    if not words:
        pdf.drawString(x, y, "-")
        return y - line_height

    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if pdf.stringWidth(candidate, font_name, font_size) <= max_width:
            current = candidate
            continue
        pdf.drawString(x, y, current)
        y -= line_height
        current = word
    if current:
        pdf.drawString(x, y, current)
        y -= line_height
    return y


def build_lots_pdf(auction_id: int, auction_title: str, lots: List[Dict]) -> bytes:
    font_name = _ensure_pdf_font()
    font_size = 10
    line_height = 14

    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    page_width, page_height = A4
    left = 40
    right = page_width - 40
    y = page_height - 50

    def new_page() -> float:
        pdf.showPage()
        pdf.setFont(font_name, font_size)
        return page_height - 50

    pdf.setFont(font_name, 14)
    pdf.drawString(left, y, f"Позиции аукциона #{auction_id}")
    y -= 22
    pdf.setFont(font_name, 11)
    y = _draw_wrapped_line(pdf, f"Название: {auction_title}", left, y, right - left, line_height, font_name, 11)
    y -= 4

    pdf.setFont(font_name, 10)
    if not lots:
        pdf.drawString(left, y, "Список позиций пуст.")
    else:
        for index, lot in enumerate(lots, start=1):
            if y < 90:
                y = new_page()
            code = lot.get("item_code") or "-"
            name = lot.get("item_name") or "Без названия"
            quantity = lot.get("item_quantity")
            unit = lot.get("item_unit") or "шт"
            quantity_text = f"{quantity}" if quantity is not None else "-"

            pdf.drawString(left, y, f"{index}. [{code}] {quantity_text} {unit}")
            y -= line_height
            y = _draw_wrapped_line(pdf, f"   {name}", left, y, right - left, line_height, font_name, font_size)
            y -= 2

    pdf.save()
    return buffer.getvalue()


def build_email(
    settings: Settings,
    auction_id: int,
    auction_title: str,
    winner_bid_amount,
    winner_determined_at,
    recipient_type: str,
    recipient_email: str,
    lots_pdf: bytes,
    lots_pdf_name: str,
) -> EmailMessage:
    auction_url = settings.frontend_auction_url.format(auction_id=auction_id)
    amount = f"{winner_bid_amount:.2f}" if winner_bid_amount is not None else "не указана"
    when = winner_determined_at.strftime("%d.%m.%Y %H:%M")

    if recipient_type == "winner":
        subject = f"Вы победили в аукционе #{auction_id}"
        plain = (
            f"Поздравляем! Вы победили в аукционе #{auction_id} ({auction_title}).\n"
            f"Победная ставка: {amount}\n"
            f"Время определения победителя: {when}\n"
            f"Ссылка: {auction_url}\n"
        )
        html = f"""
        <html><body style=\"font-family: Arial, sans-serif; color: #1f2937;\">
          <h2 style=\"margin-bottom: 8px;\">Вы победили в аукционе #{auction_id}</h2>
          <p>Поздравляем! Вы стали победителем аукциона <b>{auction_title}</b>.</p>
          <p><b>Победная ставка:</b> {amount}</p>
          <p><b>Время определения победителя:</b> {when}</p>
          <p><a href=\"{auction_url}\">Перейти к аукциону</a></p>
        </body></html>
        """
    else:
        subject = f"Определен победитель аукциона #{auction_id}"
        plain = (
            f"В аукционе #{auction_id} ({auction_title}) определен победитель.\n"
            f"Победная ставка: {amount}\n"
            f"Время определения победителя: {when}\n"
            f"Ссылка: {auction_url}\n"
        )
        html = f"""
        <html><body style=\"font-family: Arial, sans-serif; color: #1f2937;\">
          <h2 style=\"margin-bottom: 8px;\">Определен победитель аукциона #{auction_id}</h2>
          <p>По вашему аукциону <b>{auction_title}</b> определен победитель.</p>
          <p><b>Победная ставка:</b> {amount}</p>
          <p><b>Время определения победителя:</b> {when}</p>
          <p><a href=\"{auction_url}\">Открыть аукцион</a></p>
        </body></html>
        """

    msg = EmailMessage()
    msg["From"] = settings.smtp_from
    msg["To"] = recipient_email
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid(domain=settings.smtp_from.split("@")[-1])
    msg.set_content(plain)
    msg.add_alternative(html, subtype="html")
    msg.add_attachment(
        lots_pdf,
        maintype="application",
        subtype="pdf",
        filename=lots_pdf_name,
    )
    return msg


def smtp_send(settings: Settings, msg: EmailMessage):
    if settings.smtp_use_ssl:
        with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=settings.smtp_timeout) as client:
            if settings.smtp_user:
                client.login(settings.smtp_user, settings.smtp_password)
            client.send_message(msg)
        return

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=settings.smtp_timeout) as client:
        client.ehlo()
        if settings.smtp_use_starttls:
            client.starttls()
            client.ehlo()
        if settings.smtp_user:
            client.login(settings.smtp_user, settings.smtp_password)
        client.send_message(msg)


def write_heartbeat():
    with open(HEARTBEAT_PATH, "w", encoding="utf-8") as f:
        f.write(datetime.now(timezone.utc).isoformat())


def process_once(conn: psycopg.Connection, settings: Settings):
    rows = get_candidate_auctions(conn, settings.lookback_days)
    total_attempted = 0
    total_sent = 0

    for row in rows:
        lots = get_auction_lots(conn, row["auction_id"])
        lots_pdf = build_lots_pdf(
            auction_id=row["auction_id"],
            auction_title=row["auction_title"],
            lots=lots,
        )
        lots_pdf_name = f"auction_{row['auction_id']}_lots.pdf"

        recipients = [
            ("initiator", row["initiator_email"]),
            ("winner", row["winner_email"]),
        ]

        for recipient_type, recipient_email in recipients:
            upsert_notification_pending(
                conn,
                row["auction_id"],
                row["winner_bid_id"],
                recipient_type,
                recipient_email,
            )
            state = get_notification_state(
                conn,
                row["auction_id"],
                row["winner_bid_id"],
                recipient_type,
            )
            if not should_send(state, settings.max_retry_attempts):
                continue

            total_attempted += 1
            try:
                message = build_email(
                    settings=settings,
                    auction_id=row["auction_id"],
                    auction_title=row["auction_title"],
                    winner_bid_amount=row["winner_bid_amount"],
                    winner_determined_at=row["winner_determined_at"],
                    recipient_type=recipient_type,
                    recipient_email=recipient_email,
                    lots_pdf=lots_pdf,
                    lots_pdf_name=lots_pdf_name,
                )
                smtp_send(settings, message)
                mark_sent(conn, state["id"], message["Message-ID"])
                total_sent += 1
                log(
                    "info",
                    "email sent",
                    auction_id=row["auction_id"],
                    winner_bid_id=row["winner_bid_id"],
                    recipient_type=recipient_type,
                    recipient_email=recipient_email,
                )
            except Exception as exc:
                mark_failed(conn, state["id"], str(exc), settings.retry_base_seconds)
                log(
                    "error",
                    "email failed",
                    auction_id=row["auction_id"],
                    winner_bid_id=row["winner_bid_id"],
                    recipient_type=recipient_type,
                    recipient_email=recipient_email,
                    error=str(exc),
                )

    conn.commit()
    log("info", "poll cycle complete", candidates=len(rows), attempted=total_attempted, sent=total_sent)


def main():
    settings = Settings()
    log("info", "email worker starting", smtp_host=settings.smtp_host, smtp_port=settings.smtp_port)

    with psycopg.connect(settings.dsn, row_factory=dict_row) as conn:
        ensure_schema(conn)
        log("info", "schema ensured")

        while RUNNING:
            try:
                process_once(conn, settings)
                write_heartbeat()
            except Exception as exc:
                conn.rollback()
                log("error", "poll cycle crashed", error=str(exc))
            time.sleep(settings.poll_interval_seconds)

    log("info", "email worker stopped")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log("error", "fatal error", error=str(exc))
        sys.exit(1)
