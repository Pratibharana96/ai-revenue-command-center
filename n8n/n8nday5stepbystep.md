DAY 5 · AI Revenue Command Center
Automated Lead Qualification: n8n + NVIDIA NIM + Salesforce
An enterprise workflow that captures inbound web form submissions, qualifies pain points using NVIDIA NIM LLM (meta/llama-3.1-70b-instruct), parses structured JSON verdicts, and dynamically routes leads into Salesforce as either URGENT or NURTURE records.

1. System Architecture
text

                               ┌────────────────────────────────────────────────────────┐
                               │                    WORKFLOW CANVAS                     │
                               └────────────────────────────────────────────────────────┘

[ 1. Webhook Trigger ]
         │
         ▼
[ 2. NVIDIA Qualify ]  ──────► Calls Llama 3.1 70B Instruct API
         │
         ▼
[ 3. Parse AI Reply ]  ──────► Normalizes JSON & coerces boolean `route_to_human`
         │
         ▼
[ 4. IF route_to_human ]
         │
         ├───────────────────────► TRUE  ──────► [ 5. Salesforce Write Urgent ]
         │                                               (Description: "URGENT — ...")
         │
         └───────────────────────► FALSE ──────► [ 6. Salesforce Write Nurture ]
                                                         (Description: "Nurture — ...")
2. Important Links & Endpoints
Resource	URL / Details
n8n Instance	https://n8n.chefhome.in
Webhook Test Endpoint	https://n8n.chefhome.in/webhook-test/day4-qualify
Webhook Production Endpoint	https://n8n.chefhome.in/webhook/day4-qualify
Salesforce Org URL	https://orgfarm-ceb9ab7a86-dev-ed.develop.my.salesforce.com
Salesforce Today's Leads View	https://orgfarm-ceb9ab7a86-dev-ed.develop.my.salesforce.com/lightning/o/Lead/list?filterName=TodaysLeads
NVIDIA API Endpoint	https://integrate.api.nvidia.com/v1/chat/completions
OAuth Redirect Callback URL	https://n8n.chefhome.in/rest/oauth2-credential/callback
3. Node-by-Node Configuration Reference
Node 1: Webhook Trigger
Node Type: n8n-nodes-base.webhook
HTTP Method: POST
Path: day4-qualify
Authentication: None
Response Mode: On Received (200 OK)
Node 2: NVIDIA Qualify
Node Type: n8n-nodes-base.httpRequest
HTTP Method: POST
URL: https://integrate.api.nvidia.com/v1/chat/completions
Authentication: None (Header Auth)
Headers:
Header Name	Header Value
Authorization	Bearer nvapi-YOUR_NVIDIA_API_KEY
Content-Type	application/json
Accept	application/json
Body Content Type: JSON (Specify Body: Using JSON with Expression / fx enabled)
Body Code:
JavaScript

={{
  JSON.stringify({
    "model": "meta/llama-3.1-70b-instruct",
    "messages": [
      {
        "role": "system",
        "content": "You are an AI qualification assistant for Salesforce release pain points. Return ONLY valid JSON with no markdown syntax. Keys required: route_to_human (boolean), urgency (one of: urgent, high, medium, low), pain_point (string), summary (string), recommended_action (string), confidence (number 0-1). Set route_to_human to true if the message describes a production outage, failed deployment, data loss, security issue, release blocker, or immediate human help. Otherwise set route_to_human to false."
      },
      {
        "role": "user",
        "content": "First Name: " + ($json.body?.firstName || $json.firstName || '') + "\nLast Name: " + ($json.body?.lastName || $json.lastName || '') + "\nCompany: " + ($json.body?.company || $json.company || '') + "\nEmail: " + ($json.body?.email || $json.email || '') + "\nMessage: " + ($json.body?.message || $json.message || '')
      }
    ],
    "temperature": 0.1,
    "top_p": 0.7,
    "max_tokens": 1024,
    "stream": false
  })
}}
Node 3: Parse AI Reply
Node Type: n8n-nodes-base.code
Language: JavaScript (Run Once For Each Item)
Script:
JavaScript

const webhook = $('Webhook').item.json.body || $('Webhook').item.json;
const ai = $json;

const raw =
  ai.choices?.[0]?.message?.content ??
  ai.content?.[0]?.text ??
  ai.output ??
  '';

let cleaned = String(raw).trim();

// 1. Remove markdown fences (```json ... ```)
cleaned = cleaned
  .replace(/^```json\s*/i, '')
  .replace(/^```\s*/, '')
  .replace(/```$/, '')
  .trim();

// 2. Isolate inner JSON string between { and }
const first = cleaned.indexOf('{');
const last = cleaned.lastIndexOf('}');
if (first !== -1 && last !== -1 && last > first) {
  cleaned = cleaned.slice(first, last + 1);
}

// 3. Clean control characters that break JSON.parse
cleaned = cleaned.replace(/[\u0000-\u001F\u007F-\u009F]/g, " ");

let parsed = {};
try {
  parsed = JSON.parse(cleaned);
} catch (e) {
  // Regex fallback parser
  const routeMatch = /"route_to_human"\s*:\s*(true|"true"|1)/i.test(raw);
  parsed = {
    route_to_human: routeMatch,
    urgency: routeMatch ? 'urgent' : 'low',
    pain_point: 'JSON Parse Warning',
    summary: 'Extracted via fallback parser',
    recommended_action: 'Review payload manually',
    confidence: 0.5
  };
}

// 4. Safe coercion into Boolean
let routeBool = false;
if (typeof parsed.route_to_human === 'boolean') {
  routeBool = parsed.route_to_human;
} else if (typeof parsed.route_to_human === 'string') {
  routeBool = ['true', '1', 'yes', 'urgent'].includes(parsed.route_to_human.toLowerCase().trim());
} else if (typeof parsed.route_to_human === 'number') {
  routeBool = parsed.route_to_human === 1;
}

parsed.route_to_human = routeBool;

return [{
  json: {
    ...webhook,
    ...parsed,
    _raw_ai_response: raw
  }
}];
Node 4: IF route_to_human
Node Type: n8n-nodes-base.if (Type Version 2)
Condition:
Value 1: ={{ $json.route_to_human }}
Operation: Boolean is True
Node 5: Salesforce Write Urgent Lead
Node Type: n8n-nodes-base.httpRequest
HTTP Method: POST
URL: https://orgfarm-ceb9ab7a86-dev-ed.develop.my.salesforce.com/services/data/v59.0/sobjects/Lead
Authentication: Predefined Credential Type -> Salesforce OAuth2 API
Environment Type: Production
JSON Body:
JavaScript

={{
  JSON.stringify({
    "FirstName": $json.firstName || "Demo",
    "LastName": $json.lastName || "Lead",
    "Company": $json.company || "Demo Company",
    "Email": $json.email || "",
    "LeadSource": "Web - AI Qualified (Demo)",
    "Description": "URGENT — AI Qualification: " + ($json.summary || "") + " | Pain: " + ($json.pain_point || "") + " | Recommended: " + ($json.recommended_action || "") + " | Confidence: " + ($json.confidence || "")
  })
}}
Node 6: Salesforce Write Nurture Lead
Node Type: n8n-nodes-base.httpRequest
HTTP Method: POST
URL: https://orgfarm-ceb9ab7a86-dev-ed.develop.my.salesforce.com/services/data/v59.0/sobjects/Lead
Authentication: Same Salesforce OAuth2 API Credential
JSON Body: Same as Node 5, but replace prefix "URGENT — " with "Nurture — ".
4. Salesforce Connected App Setup
Create Connected App: Setup ➔ App Manager ➔ New Connected App.
Basic Settings:
App Name: n8n Integration
Email: your-email@example.com
OAuth Settings:
Check Enable OAuth Settings.
Callback URL: https://n8n.chefhome.in/rest/oauth2-credential/callback
Scopes:
Manage user data via APIs (api)
Perform requests at any time (refresh_token, offline_access)
Security Policies (CRITICAL):
Go to App Manager ➔ n8n Integration ➔ MANAGE ➔ Edit Policies:
Permitted Users: Set to All users may self-authorize.
IP Relaxation: Set to Relax IP restrictions.
Refresh Token Policy: Set to Refresh token is valid until revoked.
5. Troubleshooting & Resolved Errors Log
Error Message / Issue	Root Cause	Exact Solution
The model 'meta/llama-3.3-70b-instruct' has reached its end of life	Deprecated model string on NVIDIA NIM API endpoint.	Updated model string to meta/llama-3.1-70b-instruct.
ChatCompletionRequestUserMessageContent	NVIDIA API requires "content" to be a plain string, but an unescaped JSON object was passed.	Formatted dynamic user text using string concatenation: "First Name: " + $json.firstName....
Unexpected token '=', "={..." is not valid JSON	Leading = sign left inside JSON body field when not using n8n expression mode.	Toggled fx Expression mode on the node and wrapped the JSON in ={{ JSON.stringify(...) }}.
OAUTH_APPROVAL_ERROR_GENERIC : An unexpected error has occurred	Default Salesforce app security policies block self-authorization.	Changed Connected App policies under Manage to All users may self-authorize & Relax IP restrictions.
Unable to sign without access token	Node referenced dummy credential ID from imported JSON file.	Selected actual saved Salesforce OAuth2 credential from the dropdown on both Salesforce nodes.
Bad request - please check your parameters (Use one of these records?)	Salesforce Duplicate Rules blocked creation of identical lead email/name.	Added unique identifiers in test payloads (ava.patel.urgent@demo.example) or deactivated standard Lead duplicate rules in Salesforce.
Urgent payload routing to Nurture branch	AI returning "route_to_human": "true" (string) instead of boolean true.	Added type coercion in Code node (routeBool = ['true','1','yes'].includes(...)) to guarantee output is boolean.
6. Test Payloads (Postman / cURL)
Test Payload A: Urgent Branch Trigger
JSON

{
  "firstName": "Ava",
  "lastName": "Patel (Urgent)",
  "email": "ava.patel.urgent101@demo.example",
  "company": "Northwind Release Ops",
  "message": "Our Salesforce production deployment failed during the release window. Users are seeing 500 errors on Opportunity pages and we cannot roll back. This is blocking our quarter-end close. We need a human on a call immediately."
}
Expected Result:
NVIDIA AI Returns: route_to_human: true
IF Branch: True
Salesforce Lead Description starts with: URGENT — AI Qualification: ...
Test Payload B: Nurture Branch Trigger
JSON

{
  "firstName": "Ben",
  "lastName": "Turner (Nurture)",
  "email": "ben.turner.nurture101@demo.example",
  "company": "Contoso Salesforce Team",
  "message": "We are planning a large metadata deployment next month and want to know best practices for release management. Not urgent, just exploring options."
}
Expected Result:
NVIDIA AI Returns: route_to_human: false
IF Branch: False
Salesforce Lead Description starts with: Nurture — AI Qualification: ...
7. Verification Checklist
 Webhook receives POST request and outputs 200 OK.
 NVIDIA API executes successfully with 200 OK using meta/llama-3.1-70b-instruct.
 Code node cleans JSON and extracts route_to_human as a real boolean.
 IF node correctly splits logic into True and False outputs.
 Salesforce Lead is created with LeadSource = Web - AI Qualified (Demo).
 Description prefix matches the branch (URGENT — or Nurture —).