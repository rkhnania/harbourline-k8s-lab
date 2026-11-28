-- Plimsoll WMS - schema.
--
-- ONE DEFINITION, TWO CONSUMERS: the db-init Job applies this file in the
-- cluster, and the pytest fixtures apply the same file. A schema that exists
-- twice drifts; the tests then pass against a database no deployment has.
--
-- THE INVARIANTS LIVE IN THE DATABASE, NOT IN THE APPLICATION.
-- A warehouse system's cardinal sin is negative stock. It is not prevented by
-- being careful in Python - it is prevented by CHECK (qty >= 0), which refuses
-- the write no matter which service, script or hotfix issued it. Every
-- constraint below is there because an application bug would otherwise produce
-- a warehouse state that cannot exist in the physical world.

-- ---------------------------------------------------------------- reference

CREATE TABLE IF NOT EXISTS skus (
    sku          text PRIMARY KEY,
    description  text        NOT NULL,
    uom          text        NOT NULL DEFAULT 'EA',
    -- Dangerous goods class. Null means non-hazardous. Kept because segregation
    -- rules are the most common reason a putaway is rejected in a real WMS.
    hazard_class text
);

-- Location codes are AISLE-BAY-LEVEL, the convention every warehouse operator
-- already reads off a rack label. Zones drive what a location may be used for.
CREATE TABLE IF NOT EXISTS locations (
    code     text PRIMARY KEY,
    zone     text    NOT NULL CHECK (zone IN ('RECV', 'BULK', 'PICK', 'DISP')),
    capacity integer NOT NULL DEFAULT 500 CHECK (capacity > 0)
);

-- ------------------------------------------------------------------ balance

-- Stock on hand: one row per SKU per location.
CREATE TABLE IF NOT EXISTS stock (
    sku      text    NOT NULL REFERENCES skus(sku),
    location text    NOT NULL REFERENCES locations(code),
    qty      integer NOT NULL,
    PRIMARY KEY (sku, location),
    -- The single most important line in this file.
    CONSTRAINT stock_qty_non_negative CHECK (qty >= 0)
);

-- ------------------------------------------------------------------- ledger

-- Append-only. Every change to stock writes here in the same transaction, so
-- the balance can always be re-derived and every movement has an actor.
-- A balance table alone answers "how much"; only a ledger answers "who, when
-- and why", which is the question asked after a stock discrepancy.
CREATE TABLE IF NOT EXISTS movements (
    id            bigserial   PRIMARY KEY,
    occurred_at   timestamptz NOT NULL DEFAULT now(),
    sku           text        NOT NULL REFERENCES skus(sku),
    from_location text        REFERENCES locations(code),
    to_location   text        REFERENCES locations(code),
    qty           integer     NOT NULL CHECK (qty > 0),
    reason        text        NOT NULL CHECK (reason IN
                      ('RECEIPT', 'PUTAWAY', 'PICK', 'DISPATCH', 'ADJUST')),
    -- Which Deck pod or user did it. Deck holds session state in memory, so
    -- this is the only durable record of which gun performed a scan.
    actor         text        NOT NULL,
    -- Stock must come from somewhere or go somewhere.
    CONSTRAINT movement_has_an_end CHECK (from_location IS NOT NULL OR to_location IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS movements_sku_time ON movements (sku, occurred_at DESC);

-- ------------------------------------------------------------------ inbound

CREATE TABLE IF NOT EXISTS receipts (
    id         text PRIMARY KEY,
    carrier    text        NOT NULL,
    status     text        NOT NULL DEFAULT 'EXPECTED'
                   CHECK (status IN ('EXPECTED', 'ARRIVED', 'CLOSED')),
    arrived_at timestamptz
);

CREATE TABLE IF NOT EXISTS receipt_lines (
    receipt_id   text    NOT NULL REFERENCES receipts(id) ON DELETE CASCADE,
    line_no      integer NOT NULL,
    sku          text    NOT NULL REFERENCES skus(sku),
    qty_expected integer NOT NULL CHECK (qty_expected > 0),
    qty_received integer NOT NULL DEFAULT 0 CHECK (qty_received >= 0),
    PRIMARY KEY (receipt_id, line_no),
    -- Over-receipt is a real event, but it is a decision, not an accident.
    CONSTRAINT no_silent_over_receipt CHECK (qty_received <= qty_expected)
);

-- ----------------------------------------------------------------- outbound

CREATE TABLE IF NOT EXISTS orders (
    id         text PRIMARY KEY,
    customer   text        NOT NULL,
    status     text        NOT NULL DEFAULT 'NEW'
                   CHECK (status IN ('NEW', 'PICKING', 'PICKED', 'DISPATCHED')),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS order_lines (
    order_id   text    NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    line_no    integer NOT NULL,
    sku        text    NOT NULL REFERENCES skus(sku),
    qty        integer NOT NULL CHECK (qty > 0),
    qty_picked integer NOT NULL DEFAULT 0 CHECK (qty_picked >= 0),
    PRIMARY KEY (order_id, line_no),
    CONSTRAINT no_over_pick CHECK (qty_picked <= qty)
);

-- ---------------------------------------------------------------- shipments

-- Predates the WMS model and is deliberately kept: a dispatched order becomes a
-- shipment, and the post-deployment smoke test has asserted this endpoint since
-- October. Changing a contract and the thing that verifies it in the same
-- commit means the verification proves nothing.
CREATE TABLE IF NOT EXISTS shipments (
    id      text PRIMARY KEY,
    status  text,
    carrier text
);
