#!/usr/bin/env python3
"""Debug script to inspect Slack List structure and column names."""

import os
import sys
from dotenv import load_dotenv
load_dotenv()

import requests
import json
import time

USER_TOKEN = os.environ.get("SLACK_USER_TOKEN")
LIST_ID = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("SLACK_LIST_ID")

if not USER_TOKEN:
    print("ERROR: SLACK_USER_TOKEN not set in .env")
    sys.exit(1)

if not LIST_ID:
    print("ERROR: Provide list_id as argument or set SLACK_LIST_ID in .env")
    sys.exit(1)

headers = {
    "Authorization": f"Bearer {USER_TOKEN}",
    "Content-Type": "application/json"
}

print(f"\n{'='*60}")
print(f"Debugging List: {LIST_ID}")
print(f"{'='*60}")

# 1. Fetch items from API
print("\n[1] Fetching items from slackLists.items.list...")
response = requests.post(
    "https://slack.com/api/slackLists.items.list",
    headers=headers,
    json={"list_id": LIST_ID}
)
data = response.json()

if not data.get("ok"):
    print(f"ERROR: {data.get('error')}")
    sys.exit(1)

# Print all top-level keys to see if there's column info
print(f"  Response keys: {list(data.keys())}")
for k in data.keys():
    if k not in ['ok', 'items', 'response_metadata']:
        print(f"    {k}: {data[k]}")

# Check for columns/schema in response
if 'columns' in data:
    print(f"\n  COLUMNS FOUND: {data['columns']}")
if 'schema' in data:
    print(f"\n  SCHEMA FOUND: {data['schema']}")

items = data.get("items", [])
print(f"Found {len(items)} items")

# Try slackLists.items.info to get detailed item with column names
if items:
    first_item_id = items[0].get("id")
    print(f"\n[1b] Fetching detailed info via slackLists.items.info for {first_item_id}...")
    response = requests.post(
        "https://slack.com/api/slackLists.items.info",
        headers=headers,
        json={"list_id": LIST_ID, "id": first_item_id}
    )
    info_data = response.json()
    if info_data.get("ok"):
        print(f"  Response keys: {list(info_data.keys())}")
        
        # Check the 'list' object for column definitions
        list_obj = info_data.get("list", {})
        print(f"  List object keys: {list(list_obj.keys())}")
        
        if "columns" in list_obj:
            print(f"\n  COLUMNS FOUND!")
            for col in list_obj["columns"]:
                print(f"    - {col}")
        
        if "name" in list_obj:
            print(f"\n  LIST NAME: {list_obj['name']}")
        
        # Print full list object (truncated)
        print(f"\n  Full list object: {json.dumps(list_obj, indent=2)[:1500]}...")
        
        # Check the record object
        record = info_data.get("record", {})
        print(f"\n  Record keys: {list(record.keys())}")
    else:
        print(f"  ERROR: {info_data.get('error')}")

if items:
    print("\n[2] First item structure:")
    first_item = items[0]
    print(f"  Item ID: {first_item.get('id')}")
    print(f"  Fields:")
    for field in first_item.get("fields", []):
        key = field.get("key", "")
        value = str(field.get("value", ""))
        text = field.get("text", "")
        print(f"    - key: {key}")
        val_display = value[:50] if value else '(empty)'
        val_suffix = '...' if value and len(value) > 50 else ''
        print(f"      value: {val_display}{val_suffix}")
        if text:
            text_display = str(text)[:50]
            text_suffix = '...' if len(str(text)) > 50 else ''
            print(f"      text: {text_display}{text_suffix}")

# 2. Fetch CSV to see human-readable column names
print("\n[3] Fetching CSV export for column names...")
response = requests.post(
    "https://slack.com/api/slackLists.download.start",
    headers=headers,
    json={"list_id": LIST_ID}
)
data = response.json()

if not data.get("ok"):
    print(f"ERROR starting download: {data.get('error')}")
else:
    job_id = data.get("job_id")
    print(f"  Download job started: {job_id}")
    
    # Wait for completion
    for i in range(10):
        time.sleep(1)
        response = requests.post(
            "https://slack.com/api/slackLists.download.get",
            headers=headers,
            json={"list_id": LIST_ID, "job_id": job_id}
        )
        data = response.json()
        
        if data.get("ok") and data.get("status") == "COMPLETED":
            print(f"  Download ready!")
            
            # Print full response to see all available data
            print(f"\n  download.get response keys: {list(data.keys())}")
            for k, v in data.items():
                if k not in ['ok', 'status']:
                    print(f"    {k}: {str(v)[:100]}")
            
            # Check for list name in response
            if data.get("list_name"):
                print(f"\n  LIST TITLE: {data.get('list_name')}")
            
            # Download CSV
            download_url = data.get("download_url")
            print(f"\n  Download URL: {download_url[:80]}..." if download_url else "  No download URL")
            if download_url:
                # Try different auth methods
                print("\n  Trying auth methods...")
                
                # Method 1: No auth (pre-signed URL)
                r1 = requests.get(download_url)
                print(f"  [No auth] Status: {r1.status_code}, Type: {r1.headers.get('Content-Type', '?')[:30]}")
                
                # Method 2: Bearer token header
                r2 = requests.get(download_url, headers={"Authorization": f"Bearer {USER_TOKEN}"})
                print(f"  [Bearer]  Status: {r2.status_code}, Type: {r2.headers.get('Content-Type', '?')[:30]}")
                
                # Method 3: Cookie
                r3 = requests.get(download_url, cookies={"d": USER_TOKEN})
                print(f"  [Cookie]  Status: {r3.status_code}, Type: {r3.headers.get('Content-Type', '?')[:30]}")
                
                # Use whichever worked (CSV content type)
                csv_response = None
                for r in [r1, r2, r3]:
                    if 'text/csv' in r.headers.get('Content-Type', '') or (r.status_code == 200 and r.text.startswith('"') or r.text.startswith('Name')):
                        csv_response = r
                        break
                
                if not csv_response:
                    csv_response = r2  # Default to bearer
                    
                print(f"\n  Using response with first 100 chars: {csv_response.text[:100]}")
                if csv_response.status_code == 200:
                    lines = csv_response.text.split('\n')
                    if lines:
                        columns = lines[0].split(',')
                        print(f"\n[4] CSV Column Headers:")
                        for i, col in enumerate(columns):
                            col_clean = col.strip('"')
                            print(f"    {i+1}. {col_clean}")
                        
                        if len(lines) > 1:
                            print(f"\n[5] First row data:")
                            print(f"    {lines[1][:200]}...")
            break
        elif data.get("status") == "FAILED":
            print(f"  Download failed")
            break
        print(f"  Waiting... ({i+1}/10)")

print(f"\n{'='*60}")
print("EXPECTED COLUMN NAMES (from config/env):")
print(f"  LIST_NAME_COLUMN = {os.environ.get('LIST_NAME_COLUMN', 'Name')}")
print(f"  LIST_START_DATE_COLUMN = {os.environ.get('LIST_START_DATE_COLUMN', 'Start Date')}")
print(f"  LIST_END_DATE_COLUMN = {os.environ.get('LIST_END_DATE_COLUMN', 'End Date')}")
print(f"  LIST_CATEGORY_COLUMN = {os.environ.get('LIST_CATEGORY_COLUMN', 'category')}")
print(f"  LIST_NOTES_COLUMN = {os.environ.get('LIST_NOTES_COLUMN', 'notes')}")
print(f"{'='*60}")
print("\nIf columns don't match, update your .env file with the correct column names.")

