-- Plimsoll WMS - seed data.
--
-- Idempotent on purpose: the db-init Job is an Argo CD PostSync hook and runs
-- again on every sync of the harbourline Application. A seed that is not
-- idempotent turns a routine sync into a duplicate-key failure, and the
-- Application goes Degraded for a reason that has nothing to do with the change
-- being deployed.
--
-- The data is small but shaped like a real warehouse: goods in a receiving
-- zone, bulk storage, a pick face, and a despatch lane. Enough that the picking
-- logic has to choose a location rather than being handed one.

INSERT INTO skus (sku, description, uom, hazard_class) VALUES
  ('HL-PAL-0001', 'Pallet wrap, 500mm clear',        'ROLL', NULL),
  ('HL-CRT-0002', 'Carton, double wall 600x400x400', 'EA',   NULL),
  ('HL-BAT-0003', 'Lithium-ion cell pack 18650',     'EA',   'UN3480'),
  ('HL-FLU-0004', 'Hydraulic fluid ISO 46, 20L',     'DRUM', 'UN1268'),
  ('HL-STR-0005', 'Strapping, polyester 16mm',       'ROLL', NULL)
ON CONFLICT (sku) DO NOTHING;

INSERT INTO locations (code, zone, capacity) VALUES
  ('RECV-01',   'RECV', 2000),
  ('RECV-02',   'RECV', 2000),
  ('A-01-01',   'BULK', 800),
  ('A-01-02',   'BULK', 800),
  ('A-02-01',   'BULK', 800),
  ('B-01-01',   'PICK', 200),
  ('B-01-02',   'PICK', 200),
  ('B-02-01',   'PICK', 200),
  ('DISP-01',   'DISP', 5000)
ON CONFLICT (code) DO NOTHING;

-- Opening stock. Bulk holds the depth, the pick face holds the pieces.
INSERT INTO stock (sku, location, qty) VALUES
  ('HL-PAL-0001', 'A-01-01', 240),
  ('HL-PAL-0001', 'B-01-01',  36),
  ('HL-CRT-0002', 'A-01-02', 600),
  ('HL-CRT-0002', 'B-01-02', 120),
  ('HL-BAT-0003', 'A-02-01',  90),
  ('HL-STR-0005', 'B-02-01',  48)
ON CONFLICT (sku, location) DO NOTHING;

-- An inbound load that has not arrived yet.
INSERT INTO receipts (id, carrier, status) VALUES
  ('RCV-5001', 'Harbourline Freight', 'EXPECTED')
ON CONFLICT (id) DO NOTHING;

INSERT INTO receipt_lines (receipt_id, line_no, sku, qty_expected) VALUES
  ('RCV-5001', 1, 'HL-CRT-0002', 300),
  ('RCV-5001', 2, 'HL-STR-0005',  60)
ON CONFLICT (receipt_id, line_no) DO NOTHING;

-- An order waiting to be picked. Deliberately asks for more pallet wrap than
-- the pick face holds, so allocation has to fall back to bulk - the first
-- business rule worth having.
INSERT INTO orders (id, customer, status) VALUES
  ('ORD-7001', 'Austral Distribution', 'NEW')
ON CONFLICT (id) DO NOTHING;

INSERT INTO order_lines (order_id, line_no, sku, qty) VALUES
  ('ORD-7001', 1, 'HL-PAL-0001', 48),
  ('ORD-7001', 2, 'HL-CRT-0002', 80)
ON CONFLICT (order_id, line_no) DO NOTHING;

INSERT INTO shipments (id, status, carrier) VALUES
  ('SHP-1001', 'in-transit',   'Harbourline Freight'),
  ('SHP-2002', 'delayed',      'Harbourline Freight'),
  ('SHP-3003', 'customs-hold', 'Harbourline Freight')
ON CONFLICT (id) DO NOTHING;

-- OPENING BALANCES ARE MOVEMENTS TOO.
--
-- Stock seeded straight into the balance table would be invisible to the
-- ledger, and /reports/reconciliation - which re-derives the balance from
-- movements and compares - would report a permanent discrepancy equal to the
-- opening stock. A control report that is always wrong is a control report
-- nobody reads.
--
-- So the opening count is recorded as what it actually is: an ADJUST movement
-- with no source location, performed by whoever counted the warehouse on day
-- one. Idempotent per row, because this file runs on every sync.
INSERT INTO movements (sku, to_location, qty, reason, actor)
SELECT s.sku, s.location, s.qty, 'ADJUST', 'seed/opening-balance'
FROM stock s
WHERE NOT EXISTS (
    SELECT 1 FROM movements m
    WHERE m.actor = 'seed/opening-balance'
      AND m.sku = s.sku
      AND m.to_location = s.location
);
