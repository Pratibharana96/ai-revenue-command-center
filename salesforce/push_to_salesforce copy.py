"""
push_to_salesforce.py
Reads the Day 2 Clay export (top5_scored_accounts.csv) and creates/updates
matching Account records in Salesforce with Fit Score, AI Reasoning, and
Next Action.

Requires a .env file (never committed to Git) with:
    SF_USERNAME=your_username
    SF_PASSWORD=your_password
    SF_SECURITY_TOKEN=your_security_token
"""

import os
import pandas as pd
from simple_salesforce import Salesforce
from dotenv import load_dotenv

load_dotenv()

SF_USERNAME = os.getenv("SF_USERNAME")
SF_PASSWORD = os.getenv("SF_PASSWORD")
SF_SECURITY_TOKEN = os.getenv("SF_SECURITY_TOKEN")

CSV_PATH = "../clay/top5_scored_accounts.csv"


def get_next_action(score):
    """Turn a numeric fit score into a plain-English recommended action."""
    if score >= 7:
        return "Prioritize for outreach this week"
    elif score >= 4:
        return "Add to nurture sequence"
    else:
        return "Monitor only"


def build_reasoning(row):
    """Compose a short, human-readable explanation from the scoring signals."""
    parts = []

    sf_relevance = row.get("Salesforce Relevance")
    if pd.notna(sf_relevance) and float(sf_relevance) > 0:
        parts.append(
            f"Salesforce relevance signal ({sf_relevance}/3)"
        )

    devops_signal = row.get("DevOps/Release Signal")
    if pd.notna(devops_signal) and float(devops_signal) > 0:
        parts.append(
            f"active DevOps/release hiring ({devops_signal}/3)"
        )

    growth = row.get("Headcount Growth %")
    if pd.notna(growth):
        try:
            if float(growth) > 20:
                parts.append(f"{growth}% headcount growth in 6 months")
        except (ValueError, TypeError):
            pass

    if not parts:
        return "No strong signals detected; scored on firmographics only."
    return "Scored on: " + "; ".join(parts) + "."


def safe_soql_name(name):
    """Escape single quotes so a company name can't break the SOQL query."""
    return str(name).replace("'", "\\'")


def main():
    if not all([SF_USERNAME, SF_PASSWORD, SF_SECURITY_TOKEN]):
        raise SystemExit(
            "Missing credentials. Check that your .env file exists in this "
            "folder and contains SF_USERNAME, SF_PASSWORD, SF_SECURITY_TOKEN."
        )

    sf = Salesforce(
        username=SF_USERNAME,
        password=SF_PASSWORD,
        security_token=SF_SECURITY_TOKEN,
    )

    df = pd.read_csv(CSV_PATH)

    for _, row in df.iterrows():
        name = row["Name"]
        # score = float(row.get("Final Score", 0) or 0)
        salesforce_score = float(row.get("Salesforce Relevance", 0) or 0)
        devops_score = float(row.get("DevOps/Release Signal", 0) or 0)
        growth_score = float(row.get("Growth Bonus", 0) or 0)

        score = salesforce_score + devops_score + growth_score
        reasoning = build_reasoning(row)
        next_action = get_next_action(score)

        query = f"SELECT Id FROM Account WHERE Name = '{safe_soql_name(name)}' LIMIT 1"
        existing = sf.query(query)

        record = {
            "Fit_Score__c": score,
            "AI_Reasoning__c": reasoning,
            "Next_Action__c": next_action,
        }

        if existing["totalSize"] > 0:
            account_id = existing["records"][0]["Id"]
            sf.Account.update(account_id, record)
            print(f"Updated: {name} (score {score}) -> {next_action}")
        else:
            record["Name"] = name
            if pd.notna(row.get("Domain")):
                record["Website"] = row["Domain"]
            sf.Account.create(record)
            print(f"Created: {name} (score {score}) -> {next_action}")


if __name__ == "__main__":
    main()
