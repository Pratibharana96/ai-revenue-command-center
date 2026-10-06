-- =====================================================================
-- AI REVENUE COMMAND CENTER - Supabase analytics (Day 5)
-- Run each block separately in Supabase -> SQL Editor. Screenshot each result.
-- NOTE: outcome values are SIMULATED test data, not real prospect activity.
-- =====================================================================

-- ---------------------------------------------------------------------
-- STEP 0: Confirm the table and the rows your n8n workflow already wrote
-- ---------------------------------------------------------------------
SELECT id, event_time, company_name, contact_name, fit_score, route_decision, outcome, crm_status, ai_status
FROM lead_events
ORDER BY id DESC;

-- ---------------------------------------------------------------------
-- STEP 1: Log the 4 Day-4 test events (simulated outcomes)
-- Replace fit_score / route_decision with what your workflow actually returned.
-- Keys start with 'seed|' so they never clash with live webhook rows.
-- ---------------------------------------------------------------------
INSERT INTO lead_events
  (company_name, contact_name, fit_score, route_decision, outcome, ai_status, crm_status, idempotency_key)
VALUES
  ('IgniteTech',      'Mohit Khosla', 8, 'urgent',  'meeting booked', 'ok', 'ok', 'seed|ignitetech'),
  ('Small Retail Co', 'Jane Doe',     2, 'nurture', 'no response',    'ok', 'ok', 'seed|small-retail-co'),
  ('Replit',          'Marina Lee',   9, 'urgent',  'replied',        'ok', 'ok', 'seed|replit'),
  ('ArhamSoft',       'Safina Naz',   5, 'nurture', 'no response',    'ok', 'ok', 'seed|arhamsoft');

-- Optional: simulate outcomes for the leads your Postman requests created.
-- (Edit the emails to match your own test rows.)
-- UPDATE lead_events SET outcome = 'meeting booked'
--   WHERE email = 'riley.chen.urgent.401@demo.example';
-- UPDATE lead_events SET outcome = 'no response'
--   WHERE email = 'morgan.lee.nurture.401@demo.example';

-- ---------------------------------------------------------------------
-- QUERY 1 - How many leads went to each route?
-- ---------------------------------------------------------------------
SELECT route_decision, COUNT(*) AS lead_count
FROM lead_events
GROUP BY route_decision
ORDER BY lead_count DESC;

-- ---------------------------------------------------------------------
-- QUERY 2 - Average fit score by outcome
-- (leads still 'pending' are excluded, they have no outcome yet)
-- ---------------------------------------------------------------------
SELECT outcome, ROUND(AVG(fit_score), 1) AS avg_fit_score, COUNT(*) AS leads
FROM lead_events
WHERE outcome NOT LIKE 'pending%'
GROUP BY outcome
ORDER BY avg_fit_score DESC;

-- ---------------------------------------------------------------------
-- QUERY 3 - Overall conversion rate (replied or meeting booked)
-- ---------------------------------------------------------------------
SELECT
  COUNT(*) AS leads_with_outcome,
  ROUND(100.0 * SUM(CASE WHEN outcome IN ('replied', 'meeting booked') THEN 1 ELSE 0 END) / COUNT(*), 1) AS conversion_rate_pct
FROM lead_events
WHERE outcome NOT LIKE 'pending%';

-- ---------------------------------------------------------------------
-- QUERY 4 - Does urgent routing actually convert better?
-- ---------------------------------------------------------------------
SELECT
  route_decision,
  COUNT(*) AS leads,
  ROUND(100.0 * SUM(CASE WHEN outcome IN ('replied', 'meeting booked') THEN 1 ELSE 0 END) / COUNT(*), 1) AS conversion_pct
FROM lead_events
WHERE outcome NOT LIKE 'pending%'
GROUP BY route_decision
ORDER BY conversion_pct DESC;

-- ---------------------------------------------------------------------
-- QUERY 5 - Full leaderboard, highest fit score first
-- ---------------------------------------------------------------------
SELECT company_name, fit_score, route_decision, outcome, crm_status, ai_status
FROM lead_events
ORDER BY fit_score DESC;

-- ---------------------------------------------------------------------
-- BONUS - Automation health (shows you measure the workflow itself)
-- ---------------------------------------------------------------------
SELECT
  COUNT(*) AS total_leads,
  SUM(CASE WHEN ai_status <> 'ok'  THEN 1 ELSE 0 END) AS ai_fallbacks,
  SUM(CASE WHEN crm_status = 'failed' THEN 1 ELSE 0 END) AS crm_failures,
  ROUND(100.0 * SUM(CASE WHEN ai_status = 'ok' AND crm_status = 'ok' THEN 1 ELSE 0 END) / COUNT(*), 1) AS clean_run_pct
FROM lead_events;
