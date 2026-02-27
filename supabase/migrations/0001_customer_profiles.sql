-- Eisla Design System — Customer Profiles
-- Extends Supabase auth.users for customer-facing accounts.
-- Internal staff (admin/engineer/auditor) are in the ops hub `users` table.
-- Run this migration against the shared Supabase project.

create table if not exists public.customer_profiles (
  id             uuid primary key references auth.users(id) on delete cascade,
  name           text not null,
  email          text not null,
  credits        integer not null default 0,
  referral_code  text unique not null,
  referral_source text,              -- UUID of the referring customer_profiles row
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);

-- RLS: customers can only read/write their own profile
alter table public.customer_profiles enable row level security;

create policy "customer_profiles: own row only"
  on public.customer_profiles
  for all
  using  (auth.uid() = id)
  with check (auth.uid() = id);

-- Service role bypasses RLS (used by design system server-side)

-- Auto-update updated_at
create or replace function public.update_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists set_updated_at on public.customer_profiles;
create trigger set_updated_at
  before update on public.customer_profiles
  for each row execute function public.update_updated_at();

-- Designs table: links a resolved design (pre-payment) to a customer
create table if not exists public.designs (
  id              uuid primary key default gen_random_uuid(),
  customer_id     uuid references public.customer_profiles(id) on delete set null,
  description     text,                -- original NL input
  capabilities    jsonb,               -- resolved capability list
  resolved        jsonb,               -- full resolver output
  tier            integer,             -- 1, 2, or 3
  service_level   text default 'standard', -- standard | priority | express
  design_fee_gbp  integer,             -- pence
  status          text not null default 'draft',
  -- draft → paid → processing → complete | failed
  stripe_session_id text,
  order_ref       text,                -- EISLA-YYYY-NNNN (set after ops hub creates the order)
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

alter table public.designs enable row level security;

create policy "designs: own rows only"
  on public.designs
  for all
  using  (auth.uid() = customer_id)
  with check (auth.uid() = customer_id);

drop trigger if exists set_designs_updated_at on public.designs;
create trigger set_designs_updated_at
  before update on public.designs
  for each row execute function public.update_updated_at();

-- Credits ledger
create table if not exists public.credit_ledger (
  id            uuid primary key default gen_random_uuid(),
  customer_id   uuid not null references public.customer_profiles(id) on delete cascade,
  delta         integer not null,   -- positive = credit, negative = debit
  reason        text not null,      -- 'referral' | 'purchase' | 'redemption' | 'promo'
  reference_id  uuid,               -- design_id or order_ref reference
  created_at    timestamptz not null default now()
);

alter table public.credit_ledger enable row level security;

create policy "credit_ledger: own rows only"
  on public.credit_ledger
  for all
  using (auth.uid() = customer_id);

-- Index for common queries
create index if not exists idx_designs_customer    on public.designs(customer_id);
create index if not exists idx_designs_status      on public.designs(status);
create index if not exists idx_credit_ledger_cust  on public.credit_ledger(customer_id);
