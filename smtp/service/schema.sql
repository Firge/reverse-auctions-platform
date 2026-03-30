CREATE TABLE IF NOT EXISTS smtp_notifications (
    id BIGSERIAL PRIMARY KEY,
    auction_id INTEGER NOT NULL,
    winner_bid_id INTEGER NOT NULL,
    recipient_type TEXT NOT NULL CHECK (recipient_type IN ('initiator', 'winner')),
    recipient_email TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'failed', 'sent')),
    attempts INTEGER NOT NULL DEFAULT 0,
    next_retry_at TIMESTAMPTZ,
    last_error TEXT,
    message_id TEXT,
    sent_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT smtp_notifications_uniq UNIQUE (auction_id, winner_bid_id, recipient_type)
);

CREATE INDEX IF NOT EXISTS smtp_notifications_status_idx
    ON smtp_notifications (status, next_retry_at);

CREATE INDEX IF NOT EXISTS smtp_notifications_auction_idx
    ON smtp_notifications (auction_id, winner_bid_id);
