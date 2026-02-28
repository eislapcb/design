-- Migration 0003: Manufacturing orders table
--
-- Run in Supabase dashboard SQL editor for project htinhlmybmkacfhjhvck.
--
-- Stores manufacturing orders placed after customer pays via Stripe.
-- Status flow: pending → placed/pending_manual → shipped → delivered | failed

CREATE TABLE IF NOT EXISTS public.manufacturing_orders (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  design_id           uuid NOT NULL REFERENCES public.designs(id) ON DELETE CASCADE,
  customer_id         uuid REFERENCES public.customer_profiles(id) ON DELETE SET NULL,
  fab                 text NOT NULL,        -- 'JLCPCB' | 'PCBTrain' | 'PCBWay' | 'Eurocircuits'
  quantity            integer NOT NULL,
  customer_price_gbp  numeric(10,2),        -- what customer paid (incl. margin), GBP
  raw_fab_price_gbp   numeric(10,2),        -- internal cost (never exposed via API)
  status              text NOT NULL DEFAULT 'pending',
                        -- pending | placed | pending_manual | shipped | delivered | failed
  stripe_session_id   text,                 -- idempotency key
  fab_order_ref       text,                 -- fab's order reference / ID
  batch_number        text,                 -- JLCPCB batch number
  tracking_ref        text,                 -- shipping tracking number
  shipping_address    text,                 -- formatted address from Stripe
  error_message       text,                 -- if status = failed
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now()
);

-- RLS: customers can read their own orders
ALTER TABLE public.manufacturing_orders ENABLE ROW LEVEL SECURITY;

CREATE POLICY "manufacturing_orders: own rows read"
  ON public.manufacturing_orders
  FOR SELECT
  USING (auth.uid() = customer_id);

-- Service role bypasses RLS for writes (worker/webhook)

-- Auto-update updated_at
DROP TRIGGER IF EXISTS set_manufacturing_orders_updated_at ON public.manufacturing_orders;
CREATE TRIGGER set_manufacturing_orders_updated_at
  BEFORE UPDATE ON public.manufacturing_orders
  FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();

-- Indexes
CREATE INDEX IF NOT EXISTS idx_mfg_orders_design    ON public.manufacturing_orders(design_id);
CREATE INDEX IF NOT EXISTS idx_mfg_orders_customer   ON public.manufacturing_orders(customer_id);
CREATE INDEX IF NOT EXISTS idx_mfg_orders_status     ON public.manufacturing_orders(status);
CREATE INDEX IF NOT EXISTS idx_mfg_orders_stripe_sid ON public.manufacturing_orders(stripe_session_id);

-- Add reorder_of column to designs table for linking reorders to originals
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'designs' AND column_name = 'reorder_of'
  ) THEN
    ALTER TABLE public.designs ADD COLUMN reorder_of uuid REFERENCES public.designs(id);
  END IF;
END$$;
