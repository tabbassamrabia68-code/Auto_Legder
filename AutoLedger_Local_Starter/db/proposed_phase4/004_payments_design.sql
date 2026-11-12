-- PROPOSED — NOT EXECUTED
-- Phase 5-compatible PKR payment design draft.
-- Adds payment events for purchase/sale installments and refunds.
-- Header payment status is derived from completed payment/refund events.

BEGIN;

CREATE TABLE IF NOT EXISTS public.payments (
    payment_id INTEGER GENERATED ALWAYS AS IDENTITY,
    payment_reference VARCHAR(80) NOT NULL,
    purchase_id INTEGER,
    sale_id INTEGER,
    amount NUMERIC(12, 2) NOT NULL,
    currency CHAR(3) NOT NULL DEFAULT 'PKR',
    payment_kind VARCHAR(10) NOT NULL DEFAULT 'PAYMENT',
    reversal_of_payment_id INTEGER,
    payment_date TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    payment_method VARCHAR(24) NOT NULL,
    payment_status VARCHAR(12) NOT NULL DEFAULT 'PENDING',
    external_reference VARCHAR(120),
    CONSTRAINT pk_payments_p4 PRIMARY KEY (payment_id),
    CONSTRAINT uq_payments_p4_reference UNIQUE (payment_reference)
);

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conrelid = 'public.payments'::regclass
                     AND conname = 'pk_payments_p4') THEN
        IF EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conrelid = 'public.payments'::regclass
                     AND contype = 'p') THEN
            RAISE EXCEPTION
                'payments has an unexpected primary key; review schema drift';
        END IF;
        ALTER TABLE public.payments
            ADD CONSTRAINT pk_payments_p4 PRIMARY KEY (payment_id);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conrelid = 'public.payments'::regclass
                     AND conname = 'uq_payments_p4_reference') THEN
        ALTER TABLE public.payments
            ADD CONSTRAINT uq_payments_p4_reference UNIQUE (payment_reference);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conrelid = 'public.payments'::regclass
                     AND conname = 'fk_payments_p4_purchase') THEN
        ALTER TABLE public.payments
            ADD CONSTRAINT fk_payments_p4_purchase
            FOREIGN KEY (purchase_id) REFERENCES public.purchases (purchase_id)
            ON DELETE RESTRICT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conrelid = 'public.payments'::regclass
                     AND conname = 'fk_payments_p4_sale') THEN
        ALTER TABLE public.payments
            ADD CONSTRAINT fk_payments_p4_sale
            FOREIGN KEY (sale_id) REFERENCES public.sales (sale_id)
            ON DELETE RESTRICT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conrelid = 'public.payments'::regclass
                     AND conname = 'fk_payments_p4_reversal') THEN
        ALTER TABLE public.payments
            ADD CONSTRAINT fk_payments_p4_reversal
            FOREIGN KEY (reversal_of_payment_id)
            REFERENCES public.payments (payment_id)
            ON DELETE RESTRICT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conrelid = 'public.payments'::regclass
                     AND conname = 'ck_payments_p4_reference') THEN
        ALTER TABLE public.payments
            ADD CONSTRAINT ck_payments_p4_reference
            CHECK (BTRIM(payment_reference) <> '');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conrelid = 'public.payments'::regclass
                     AND conname = 'ck_payments_p4_parent') THEN
        ALTER TABLE public.payments
            ADD CONSTRAINT ck_payments_p4_parent
            CHECK ((purchase_id IS NOT NULL AND sale_id IS NULL)
                OR (purchase_id IS NULL AND sale_id IS NOT NULL));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conrelid = 'public.payments'::regclass
                     AND conname = 'ck_payments_p4_currency') THEN
        ALTER TABLE public.payments
            ADD CONSTRAINT ck_payments_p4_currency
            CHECK (currency = 'PKR');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conrelid = 'public.payments'::regclass
                     AND conname = 'ck_payments_p4_amount') THEN
        ALTER TABLE public.payments
            ADD CONSTRAINT ck_payments_p4_amount
            CHECK (amount > 0);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conrelid = 'public.payments'::regclass
                     AND conname = 'ck_payments_p4_kind_reversal') THEN
        ALTER TABLE public.payments
            ADD CONSTRAINT ck_payments_p4_kind_reversal
            CHECK ((payment_kind = 'PAYMENT' AND reversal_of_payment_id IS NULL)
                OR (payment_kind = 'REFUND'
                    AND reversal_of_payment_id IS NOT NULL
                    AND reversal_of_payment_id <> payment_id));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conrelid = 'public.payments'::regclass
                     AND conname = 'ck_payments_p4_method') THEN
        ALTER TABLE public.payments
            ADD CONSTRAINT ck_payments_p4_method
            CHECK (payment_method IN
                ('CASH', 'BANK_TRANSFER', 'CARD', 'CHEQUE', 'MOBILE_WALLET', 'OTHER'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conrelid = 'public.payments'::regclass
                     AND conname = 'ck_payments_p4_status') THEN
        ALTER TABLE public.payments
            ADD CONSTRAINT ck_payments_p4_status
            CHECK (payment_status IN ('PENDING', 'COMPLETED', 'FAILED', 'VOIDED'));
    END IF;
END
$$;

CREATE INDEX IF NOT EXISTS ix_payments_p4_purchase_date
    ON public.payments (purchase_id, payment_date DESC)
    WHERE purchase_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_payments_p4_sale_date
    ON public.payments (sale_id, payment_date DESC)
    WHERE sale_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_payments_p4_reversal
    ON public.payments (reversal_of_payment_id)
    WHERE reversal_of_payment_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_payments_p4_date
    ON public.payments (payment_date DESC);

COMMENT ON TABLE public.payments IS
    'PROPOSED PHASE 4 design only; settled header balances are derived.';

COMMIT;

-- Rollback note: payment attempts and refunds are financial history; retain
-- them and disable new routes rather than dropping a populated table.
