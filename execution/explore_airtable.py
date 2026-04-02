"""
Explores the Airtable base structure: lists all tables and their fields.
"""

import os
import json
import requests
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("AIRTABLE_TOKEN")
BASE_ID = os.getenv("AIRTABLE_BASE_ID")

headers = {"Authorization": f"Bearer {TOKEN}"}

resp = requests.get(
    f"https://api.airtable.com/v0/meta/bases/{BASE_ID}/tables",
    headers=headers
)
resp.raise_for_status()

data = resp.json()

for table in data["tables"]:
    print(f"\n=== Table: {table['name']} (id: {table['id']}) ===")
    for field in table["fields"]:
        print(f"  - {field['name']} [{field['type']}] (id: {field['id']})")
