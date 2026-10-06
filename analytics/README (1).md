# AI Revenue Command Center

A portfolio prototype demonstrating account discovery, CRM integration, AI-driven lead qualification, and pipeline analytics for a fictional enterprise Salesforce DevOps company (CloudRelease AI).

## What's real vs. simulated
- **Account data (Clay):** REAL companies and REAL enrichment data, pulled live.
- **Salesforce records:** REAL records in a personal Developer Edition org.
- **AI qualification:** REAL LLM calls (NVIDIA-hosted model) with structured JSON output, not scripted responses.
- **Slack alerts and emails:** REAL messages sent by the workflow.
- **Inbound leads and their outcomes:** SIMULATED test data. No real prospects, and the `outcome` column (replied / meeting booked / no response) is entered by hand.

## Architecture
Clay -> Salesforce (Python) -> n8n (webhook -> validate -> dedupe -> LLM -> Salesforce upsert -> Supabase log -> Slack + email) -> Supabase analytics

See `/docs/architecture.png`.

## n8n workflow: production patterns
| Concern | How it is handled |
|---|---|
| Security | Header-auth webhook; API keys live in n8n credentials, never in the exported JSON |
| Input quality | Email format, required fields, sanitized text; bad input returns HTTP 400 |
| Speed | Immediate HTTP 202 so the sender never waits on the AI |
| Idempotency | Dedupe key (email + company + day) checked in Supabase, plus a unique index |
| AI reliability | Retries; if the model fails or returns bad JSON, the lead is routed to a human (fail-safe) |
| CRM hygiene | SOQL lookup by email, then update or create, so no duplicate Leads |
| Resilience | A CRM or notification failure never blocks logging; failures are recorded |
| Notifications | Urgent: Slack alert to the sales rep + SLA email to the lead. Nurture: resource email |
| Observability | Every lead logged to Supabase with `ai_status` and `crm_status`; Error Workflow emails ops |

## Folder structure
- `/docs` - strategy, ICP, research brief, architecture diagram
- `/clay` - exported scored account CSV + screenshots
- `/salesforce` - Python integration script + field mapping
- `/n8n` - exported workflow JSON (`day4-workflow-production.json`) + screenshots
- `/analytics` - SQL setup, analytics queries, and result screenshots
- `/hubspot` - HubSpot integration script *(include only if you completed Day 6)*

## How to run this
1. Read `/docs` for the GTM strategy and ICP.
2. Clay scoring logic: `/docs/day2-account-discovery.md`.
3. Run `salesforce/push_to_salesforce.py` (needs your own `.env`, see `.env.example`).
4. In Supabase, run `analytics/supabase_setup.sql`, then import `n8n/day4-workflow-production.json` into your own n8n instance and create the credentials it asks for (webhook header auth, LLM API key, Salesforce, Supabase service role, Slack, SMTP).
5. Send a test lead:
```bash
curl -X POST "https://YOUR-N8N-HOST/webhook/day4-qualify" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: YOUR_WEBHOOK_KEY" \
  -d '{"firstName":"Riley","lastName":"Chen","email":"riley@demo.example","company":"Acme Org Farm","message":"Salesforce production is down after a failed deployment","test_mode":true}'
```
6. Run the queries in `analytics/analytics_queries.sql` in your Supabase SQL Editor.

## Analytics (Supabase)
Five queries measure the funnel: leads per route, average fit score by outcome, overall conversion rate, urgent vs. nurture conversion, and a fit-score leaderboard. A bonus query tracks automation health (AI fallbacks and CRM failures). Results are in `/analytics/screenshots`.

## Known limitations
This is a prototype, not a production system. Outcomes are simulated, the email footer is not a full GDPR / CAN-SPAM consent flow, and there is no real conversion tracking back from the CRM yet.

## About this project
Built as a hands-on demonstration of GTM engineering skills: account scoring, CRM integration, AI agent workflows with production safeguards, and funnel analytics.

[Loom walkthrough](your-loom-link-here) | [LinkedIn post](your-post-link-here)
