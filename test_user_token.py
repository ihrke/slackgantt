#!/usr/bin/env python3
"""
Test accessing Slack Lists with a user token.

To get a user token:
1. Go to https://api.slack.com/apps → your app
2. OAuth & Permissions → Add User Token Scopes:
   - lists:read
   - lists:write (optional)
3. Reinstall app
4. Copy the "User OAuth Token" (starts with xoxp-)
"""

import os
import requests
from dotenv import load_dotenv

load_dotenv()

# Try with user token if available, otherwise bot token
user_token = os.environ.get("SLACK_USER_TOKEN")
bot_token = os.environ.get("SLACK_BOT_TOKEN")
list_id = os.environ.get("SLACK_LIST_ID")

token = user_token or bot_token
token_type = "User" if user_token else "Bot"

print(f"Using {token_type} Token: {token[:20]}...")
print(f"List ID: {list_id}\n")

# Try to access the list
url = "https://slack.com/api/slackLists.items.list"
headers = {
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json"
}
payload = {"list_id": list_id}

response = requests.post(url, headers=headers, json=payload)
data = response.json()

print(f"Response OK: {data.get('ok')}")

if data.get("ok"):
    items = data.get("items", [])
    print(f"SUCCESS! Found {len(items)} items\n")
    
    for i, item in enumerate(items[:5]):
        print(f"Item {i+1}:")
        fields = item.get("fields", [])
        for field in fields:
            key = field.get("key", field.get("column_id", "unknown"))
            value = field.get("value", "")
            print(f"  {key}: {value}")
        print()
else:
    print(f"Error: {data.get('error')}")
    if data.get("error") == "list_not_found":
        print("\nThe list wasn't found. Possible reasons:")
        print("  1. Bot/user doesn't have access to this list")
        print("  2. List ID is incorrect")
        print("  3. lists:read scope is missing")
        print("\nTry adding a User Token with lists:read scope:")
        print("  1. Go to api.slack.com/apps → your app")
        print("  2. OAuth & Permissions → User Token Scopes → add 'lists:read'")
        print("  3. Reinstall app to workspace")
        print("  4. Copy 'User OAuth Token' (xoxp-...)")
        print("  5. Add SLACK_USER_TOKEN=xoxp-... to .env")

