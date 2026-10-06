"""
push_to_salesforce.py
Reads the scored accounts CSV (Clay export) and creates/updates matching
Account records in Salesforce with Fit Score, AI Reasoning, Next Action,
plus the firmographic fields available in the export.

Requires a .env file (never committed to Git) with:
    SF_USERNAME=your_username
    SF_PASSWORD=your_password
    SF_SECURITY_TOKEN=your_security_token
    SF_CLIENT_ID=connected_app_consumer_key
    SF_CLIENT_SECRET=connected_app_consumer_secret

    # Optional:
    SF_DOMAIN=login          # 'test' for a sandbox, or your My Domain
    SF_AUTH_MODE=auto        # auto | browser | password | soap
    SF_REDIRECT_PORT=8080    # must match the Connected App callback URL

Authentication (see README.md for the full walkthrough):
    auto (default) - reuses a cached refresh token if one exists, otherwise
    opens Salesforce in your browser once (OAuth 2.0 authorization code +
    PKCE flow) and caches the resulting refresh token. This works in every
    org and needs no special org settings.

Usage:
    python push_to_salesforce.py                 # push to Salesforce
    python push_to_salesforce.py --dry-run       # preview only, writes nothing
    python push_to_salesforce.py --csv other.csv # use a different CSV
"""

import argparse
import base64
import hashlib
import os
import secrets
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

import pandas as pd
import requests
from dotenv import load_dotenv
from simple_salesforce import Salesforce
from simple_salesforce.exceptions import SalesforceAuthenticationFailed

load_dotenv()

SF_USERNAME = os.getenv("SF_USERNAME")
SF_PASSWORD = os.getenv("SF_PASSWORD")
SF_SECURITY_TOKEN = os.getenv("SF_SECURITY_TOKEN")
SF_CLIENT_ID = os.getenv("SF_CLIENT_ID")
SF_CLIENT_SECRET = os.getenv("SF_CLIENT_SECRET")
SF_DOMAIN = os.getenv("SF_DOMAIN", "login")
SF_AUTH_MODE = os.getenv("SF_AUTH_MODE", "auto")  # auto | browser | password | soap
SF_REDIRECT_PORT = int(os.getenv("SF_REDIRECT_PORT", "8080"))

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CSV = os.path.join(HERE, "scored_accounts.csv")
REFRESH_TOKEN_FILE = os.path.join(HERE, ".sf_refresh_token")
REDIRECT_URI = f"http://localhost:{SF_REDIRECT_PORT}/callback"
TOKEN_URL = f"https://{SF_DOMAIN}.salesforce.com/services/oauth2/token"
AUTHORIZE_URL = f"https://{SF_DOMAIN}.salesforce.com/services/oauth2/authorize"
AUTH_TIMEOUT = 300  # seconds to wait for the browser login


# ------------------------------------------------------------ connection --

def connect():
    """
    Authenticate to Salesforce.

    auto (default):
      1. A refresh token cached by an earlier browser login, if present
      2. The OAuth 2.0 web-server (authorization code + PKCE) flow: opens
         Salesforce in your browser once, then caches a refresh token so
         later runs are silent
      3. simple_salesforce's legacy SOAP login() with a v64.0 retry

    Set SF_AUTH_MODE to force a path: browser, password, or soap.
    The username-password flow is blocked in orgs created from Summer '26
    onward and is retired everywhere on 2027-02-20.
    """
    if not SF_USERNAME or not SF_PASSWORD:
        raise SystemExit(
            "Missing credentials. Create a .env file in this folder containing:\n"
            "  SF_USERNAME=...\n  SF_PASSWORD=...\n"
            "  SF_CLIENT_ID=...\n  SF_CLIENT_SECRET=...\n"
            "(Connected App consumer key / secret - see README.md)"
        )

    mode = (SF_AUTH_MODE or "auto").strip().lower()

    if mode in ("auto", "browser", "password") and not SF_CLIENT_ID:
        raise SystemExit(
            "SF_CLIENT_ID is not set.\n"
            "Create a Connected App in Salesforce and put its Consumer Key and\n"
            "Secret in .env - see README.md for the steps."
        )

    if mode == "browser":
        return browser_login()
    if mode == "password":
        return password_login()
    if mode == "soap":
        return soap_login()

    # auto: cached token first, then the browser flow.
    sf = refresh_token_login()
    if sf is not None:
        return sf
    return browser_login()


def _save_refresh_token(token):
    with open(REFRESH_TOKEN_FILE, "w") as fh:
        fh.write(token.strip())
    try:
        os.chmod(REFRESH_TOKEN_FILE, 0o600)
    except OSError:
        pass


def _session_from_token(payload, remember=True):
    """Build a simple_salesforce client from a token response, caching any
    refresh token it contains."""
    if remember and payload.get("refresh_token"):
        _save_refresh_token(payload["refresh_token"])
    return Salesforce(
        session_id=payload["access_token"],
        instance_url=payload["instance_url"],
    )


def refresh_token_login():
    """Reuse a refresh token cached by an earlier browser login."""
    if not SF_CLIENT_ID or not os.path.exists(REFRESH_TOKEN_FILE):
        return None
    with open(REFRESH_TOKEN_FILE) as fh:
        refresh_token = fh.read().strip()
    if not refresh_token:
        return None

    response = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "client_id": SF_CLIENT_ID,
            "client_secret": SF_CLIENT_SECRET or "",
            "refresh_token": refresh_token,
        },
        timeout=30,
    )
    if response.status_code != 200:
        print("note: the cached Salesforce token is no longer valid; "
              "opening your browser to log in again.")
        return None
    print("Logged in using the cached token.")
    return _session_from_token(response.json())


def browser_login():
    """
    OAuth 2.0 authorization code flow with PKCE.

    Starts a throwaway HTTP server on localhost, opens Salesforce's
    authorize page in your browser, and captures the redirect that carries
    the authorization code. Requires no org-side toggles.
    """
    code_verifier = secrets.token_urlsafe(96)
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode("ascii")).digest()
    ).rstrip(b"=").decode("ascii")
    state = secrets.token_urlsafe(16)

    captured = {}

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - name mandated by http.server
            parsed = urlparse(self.path)
            if parsed.path != "/callback":
                self.send_response(404)
                self.end_headers()
                return
            params = parse_qs(parsed.query)
            if params.get("state", [""])[0] != state:
                captured["error"] = "state mismatch - aborting"
                body = b"<h2>Login aborted (state mismatch).</h2>"
            elif "error" in params:
                captured["error"] = params["error"][0]
                body = b"<h2>Salesforce denied the request.</h2>"
            else:
                captured["code"] = params.get("code", [""])[0]
                body = (b"<h2>Authorized.</h2><p>You can close this tab and "
                        b"return to the terminal.</p>")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):  # silence request logging
            pass

    try:
        server = HTTPServer(("127.0.0.1", SF_REDIRECT_PORT), CallbackHandler)
    except OSError:
        raise SystemExit(
            f"Could not listen on port {SF_REDIRECT_PORT}.\n"
            "Choose another port, set SF_REDIRECT_PORT=<port> in .env, and use\n"
            "the same port in your Connected App's callback URL."
        )

    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        authorize_url = AUTHORIZE_URL + "?" + urlencode({
            "response_type": "code",
            "client_id": SF_CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "scope": "api refresh_token",
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        })

        print("\nOpening Salesforce in your browser to authorize this app...")
        print(f"(waiting for the redirect to {REDIRECT_URI})")
        if not webbrowser.open(authorize_url):
            print("Could not open a browser automatically. Visit this URL:\n")
            print(authorize_url + "\n")

        deadline = time.time() + AUTH_TIMEOUT
        while time.time() < deadline and not captured:
            time.sleep(0.5)
    finally:
        server.shutdown()

    if "error" in captured:
        raise SystemExit(f"Salesforce authorization failed: {captured['error']}")
    if "code" not in captured:
        raise SystemExit("Timed out waiting for the browser login. Please re-run.")

    response = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": captured["code"],
            "client_id": SF_CLIENT_ID,
            "client_secret": SF_CLIENT_SECRET or "",
            "redirect_uri": REDIRECT_URI,
            "code_verifier": code_verifier,
        },
        timeout=30,
    )
    payload = response.json()
    if response.status_code != 200 or "access_token" not in payload:
        raise SystemExit(
            f"Token exchange failed ({response.status_code}): "
            f"{payload.get('error')}: {payload.get('error_description')}\n\n"
            "Check that the Connected App's callback URL is exactly:\n"
            f"  {REDIRECT_URI}\n"
            "and that your user is permitted to use the app - an admin may need\n"
            "to install it under Setup -> Connected Apps OAuth Usage."
        )

    print("Authorized. A refresh token has been cached for future runs.")
    return _session_from_token(payload)


def password_login():
    """
    OAuth 2.0 username-password (ROPC) flow. Blocked in orgs created from
    Summer '26 onward and retired everywhere on 2027-02-20 - kept only for
    older orgs where it is still permitted.
    """
    response = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "password",
            "client_id": SF_CLIENT_ID,
            "client_secret": SF_CLIENT_SECRET or "",
            "username": SF_USERNAME,
            # The security token is simply appended to the password.
            "password": SF_PASSWORD + (SF_SECURITY_TOKEN or ""),
        },
        timeout=30,
    )
    payload = response.json()
    if response.status_code != 200 or "access_token" not in payload:
        raise SystemExit(
            f"Salesforce login failed ({response.status_code}): "
            f"{payload.get('error')}: {payload.get('error_description')}\n\n"
            "If the error mentions an unsupported grant type, your org blocks\n"
            "the username-password flow. Re-run without SF_AUTH_MODE=password\n"
            "to use the browser login instead."
        )
    return _session_from_token(payload)


def soap_login():
    """Legacy SOAP API login() - disabled by default in newer orgs and being
    retired. Retries on API v64.0, the last version that supports it."""
    kwargs = dict(
        username=SF_USERNAME,
        password=SF_PASSWORD,
        security_token=SF_SECURITY_TOKEN,
        domain=SF_DOMAIN,
    )
    try:
        return Salesforce(**kwargs)
    except SalesforceAuthenticationFailed as exc:
        if "login()" in str(exc) or "SOAP" in str(exc):
            try:
                return Salesforce(version="64.0", **kwargs)
            except SalesforceAuthenticationFailed:
                pass
        raise SystemExit(
            f"\nSalesforce login failed: {exc}\n\n"
            "Your org has the legacy SOAP API login() call disabled. Either:\n"
            "  1. (Recommended) Set SF_CLIENT_ID/SF_CLIENT_SECRET from a\n"
            "     Connected App and re-run - the script logs in through your\n"
            "     browser. See README.md.\n"
            "  2. Ask an admin to enable it: Setup -> User Interface -> Setup ->\n"
            "     'Enable SOAP API login()'"
        )


# ---------------------------------------------------------------- scoring --

def get_next_action(score):
    """Turn a numeric fit score into a plain-English recommended action."""
    if score >= 7:
        return "Prioritize for outreach this week"
    elif score >= 4:
        return "Add to nurture sequence"
    else:
        return "Monitor only"


def safe_float(value, default=0.0):
    """Coerce a CSV cell to float, treating blank/NaN/garbage as the default."""
    if value is None:
        return default
    try:
        if pd.isna(value):
            return default
    except (TypeError, ValueError):
        pass
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def build_reasoning(row):
    """Compose a short, human-readable explanation from the scoring signals."""
    parts = []

    sf_relevance = safe_float(row.get("Salesforce Relevance"))
    if sf_relevance > 0:
        parts.append(f"Salesforce relevance signal ({sf_relevance:g}/3)")

    devops_signal = safe_float(row.get("DevOps/Release Signal"))
    if devops_signal > 0:
        parts.append(f"active DevOps/release hiring ({devops_signal:g}/3)")

    growth = row.get("Headcount Growth %")
    growth_value = safe_float(growth, default=None) if growth is not None else None
    if growth_value is not None and growth_value > 20:
        parts.append(f"{growth_value:g}% headcount growth in 6 months")

    if not parts:
        return "No strong signals detected; scored on firmographics only."
    return "Scored on: " + "; ".join(parts) + "."


def safe_soql_name(name):
    """Escape single quotes so a company name can't break the SOQL query."""
    return str(name).replace("'", "\\'")


# ------------------------------------------------------------ field prep --

def clean(value):
    """Return a trimmed string, or None for empty/NaN cells."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return text or None


def clean_employees(value):
    """Employee Count as an int Salesforce can store (or None)."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return None


def build_record(row):
    """Map a CSV row onto Salesforce Account fields."""
    score = (safe_float(row.get("Salesforce Relevance"))
             + safe_float(row.get("DevOps/Release Signal"))
             + safe_float(row.get("Growth Bonus")))

    record = {
        # Scoring fields
        "Fit_Score__c": score,
        "AI_Reasoning__c": build_reasoning(row),
        "Next_Action__c": get_next_action(score),
        # Standard Account fields
        "Name": clean(row.get("Name")),
        "Website": clean(row.get("Domain")),
        "Description": clean(row.get("Description")),
        "Industry": clean(row.get("Industry")),
        "Type": clean(row.get("Type")),
        "BillingCity": clean(row.get("City")),
        "BillingState": clean(row.get("State or Province")),
        "BillingCountry": clean(row.get("Country")),
        "NumberOfEmployees": clean_employees(row.get("Employee Count")),
    }
    return {k: v for k, v in record.items() if v is not None}


# ------------------------------------------------------- schema filtering --

def sf_schema(sf):
    """Describe the Account object: {field_api_name: metadata}."""
    meta = sf.Account.describe()
    return {f["name"]: f for f in meta["fields"]}


def picklist_ok(field_meta, value):
    """True if a picklist value is allowed for this field."""
    for pv in field_meta.get("picklistValues", []):
        if pv.get("value") == value:
            return pv.get("active", True)
    # No exact match: allow only if the picklist is unrestricted.
    return not field_meta.get("restrictedPicklist", False)


def filter_record(record, schema, creating):
    """
    Keep only fields that exist in the org and are writable in this context.
    Returns (usable_record, skipped_notes).
    """
    usable, skipped = {}, []
    for field, value in record.items():
        meta = schema.get(field)
        if meta is None:
            skipped.append(f"{field} (field not found in org)")
            continue
        if field == "Name":
            # Name is required on create; on update it's harmless.
            usable[field] = value
            continue
        if creating and not meta.get("createable", False):
            skipped.append(f"{field} (not createable)")
            continue
        if not creating and not meta.get("updateable", False):
            skipped.append(f"{field} (not updateable)")
            continue
        if meta.get("type") in ("picklist", "multipicklist") and not picklist_ok(meta, value):
            skipped.append(f"{field}='{value}' (not an allowed picklist value)")
            continue
        if meta.get("type") == "double" and not isinstance(value, (int, float)):
            skipped.append(f"{field} (expected a number, got '{value}')")
            continue
        usable[field] = value
    return usable, skipped


# ------------------------------------------------------------------ main --

def main():
    parser = argparse.ArgumentParser(description="Push scored accounts to Salesforce.")
    parser.add_argument("--csv", default=DEFAULT_CSV, help="Path to the scored accounts CSV")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview the payloads without writing to Salesforce")
    args = parser.parse_args()

    if not os.path.exists(args.csv):
        raise SystemExit(f"CSV not found: {args.csv}")

    df = pd.read_csv(args.csv)
    if "Name" not in df.columns:
        raise SystemExit("CSV has no 'Name' column - is this the right export?")

    sf = connect()

    schema = sf_schema(sf)
    missing_custom = [f for f in ("Fit_Score__c", "AI_Reasoning__c", "Next_Action__c")
                      if f not in schema]
    if missing_custom:
        print("WARNING: these custom fields were not found in your org and "
              f"will be skipped: {', '.join(missing_custom)}")
        print("         Create them on the Account object (Number / Long Text Area / "
              "Text) to store the scoring data.\n")

    created = updated = failed = 0
    seen_names = set()

    for _, row in df.iterrows():
        name = clean(row.get("Name"))
        if not name:
            continue
        if name in seen_names:
            print(f"Skipped duplicate row in CSV: {name}")
            continue
        seen_names.add(name)

        record = build_record(row)
        query = f"SELECT Id FROM Account WHERE Name = '{safe_soql_name(name)}' LIMIT 1"
        existing = sf.query(query)

        if existing["totalSize"] > 0:
            account_id = existing["records"][0]["Id"]
            payload, skipped = filter_record(record, schema, creating=False)
            if args.dry_run:
                print(f"[dry-run] Would UPDATE {name}: {payload}")
                continue
            try:
                sf.Account.update(account_id, payload)
                updated += 1
                print(f"Updated: {name} (score {record.get('Fit_Score__c')}) "
                      f"-> {record.get('Next_Action__c')}")
            except Exception as exc:  # noqa: BLE001 - report and keep going
                failed += 1
                print(f"FAILED to update {name}: {exc}")
        else:
            payload, skipped = filter_record(record, schema, creating=True)
            if args.dry_run:
                print(f"[dry-run] Would CREATE {name}: {payload}")
                continue
            try:
                sf.Account.create(payload)
                created += 1
                print(f"Created: {name} (score {record.get('Fit_Score__c')}) "
                      f"-> {record.get('Next_Action__c')}")
            except Exception as exc:  # noqa: BLE001 - report and keep going
                failed += 1
                print(f"FAILED to create {name}: {exc}")

        for note in skipped:
            print(f"    note: skipped {note}")

    if not args.dry_run:
        print(f"\nDone. Created: {created}, Updated: {updated}, Failed: {failed}")
    else:
        print("\nDry run complete - nothing was written to Salesforce.")


if __name__ == "__main__":
    main()
