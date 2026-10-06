"""
verify_quick.py
Standalone check: lists the accounts this push created in Salesforce today
and compares them against the CSV. Uses the cached OAuth refresh token, so
there's no browser prompt.

Usage:
    python verify_quick.py
"""

import os

import pandas as pd
import requests
from dotenv import load_dotenv

load_dotenv()

SF_CLIENT_ID = os.getenv("SF_CLIENT_ID")
SF_CLIENT_SECRET = os.getenv("SF_CLIENT_SECRET")
SF_DOMAIN = os.getenv("SF_DOMAIN", "login")
API_VERSION = "v59.0"

HERE = os.path.dirname(os.path.abspath(__file__))
TOKEN_FILE = os.path.join(HERE, ".sf_refresh_token")


def login():
    """Exchange the cached refresh token for a fresh access token."""
    if not os.path.exists(TOKEN_FILE):
        raise SystemExit(
            f"No cached token at {TOKEN_FILE}.\n"
            "Run push_to_salesforce.py once (it logs in through your browser\n"
            "and saves the token), then run this script."
        )
    with open(TOKEN_FILE) as fh:
        refresh_token = fh.read().strip()

    response = requests.post(
        f"https://{SF_DOMAIN}.salesforce.com/services/oauth2/token",
        data={
            "grant_type": "refresh_token",
            "client_id": SF_CLIENT_ID,
            "client_secret": SF_CLIENT_SECRET or "",
            "refresh_token": refresh_token,
        },
        timeout=30,
    )
    payload = response.json()
    if "access_token" not in payload:
        raise SystemExit(f"Login failed: {payload}")
    return payload["access_token"], payload["instance_url"]


def main():
    access_token, instance = login()
    headers = {"Authorization": f"Bearer {access_token}"}

    query = (
        "SELECT Name, Website, Fit_Score__c, Next_Action__c, Industry, "
        "BillingCity, BillingState, BillingCountry, NumberOfEmployees, CreatedDate "
        "FROM Account WHERE CreatedDate = TODAY ORDER BY CreatedDate DESC"
    )
    response = requests.get(
        f"{instance}/services/data/{API_VERSION}/query",
        headers=headers,
        params={"q": query},
        timeout=30,
    )
    data = response.json()
    if "records" not in data:
        raise SystemExit(f"Query failed: {data}")

    records = data["records"]
    print(f"\n{len(records)} account(s) created in Salesforce today:\n")
    if records:
        width = max(len(r["Name"]) for r in records)
        print(f"  {'Company'.ljust(width)}  {'Score':>5}  {'Website'.ljust(20)}  Next Action")
        print("  " + "-" * (width + 56))
        for r in records:
            score = r.get("Fit_Score__c")
            score = "--" if score is None else f"{score:g}"
            website = str(r.get("Website") or "")[:20]
            print(f"  {r['Name'].ljust(width)}  {score:>5}  {website.ljust(20)}  "
                  f"{r.get('Next_Action__c') or ''}")

    # Compare against the CSV so we can see exactly what didn't make it
    csv_path = os.path.join(HERE, "scored_accounts.csv")
    if os.path.exists(csv_path):
        df = pd.read_csv(csv_path)
        expected = {str(n).strip() for n in df["Name"].dropna()}
        created = {r["Name"] for r in records}
        missing = expected - created
        print(f"\n  Companies in CSV      : {len(expected)}")
        print(f"  Created in Salesforce : {len(created)}")
        if missing:
            print(f"  NOT created ({len(missing)})     : " + ", ".join(sorted(missing)))
        else:
            print("  Every company from the CSV is in Salesforce.")


if __name__ == "__main__":
    main()