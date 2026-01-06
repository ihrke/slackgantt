#!/usr/bin/env python3
"""Check what scopes the bot token has."""

import os
import requests
from dotenv import load_dotenv

load_dotenv()

token = os.environ.get("SLACK_BOT_TOKEN")

# Get token info
url = "https://slack.com/api/auth.test"
headers = {"Authorization": f"Bearer {token}"}

response = requests.get(url, headers=headers)
data = response.json()

print("Auth Test Response:")
print(f"  OK: {data.get('ok')}")
print(f"  User: {data.get('user')}")
print(f"  Team: {data.get('team')}")
print(f"  User ID: {data.get('user_id')}")
print(f"  Bot ID: {data.get('bot_id')}")

# Check scopes via api.test
url2 = "https://slack.com/api/apps.permissions.scopes.list"
response2 = requests.get(url2, headers=headers)
data2 = response2.json()

if data2.get("ok"):
    print("\nScopes:")
    for scope in data2.get("scopes", []):
        print(f"  - {scope}")
else:
    print(f"\nCouldn't get scopes: {data2.get('error')}")
    
# Alternative: check via OAuth info
print("\nChecking OAuth info...")
url3 = "https://slack.com/api/oauth.v2.access"
# This won't work without client credentials, so let's try another way

# Try listing all channels to see if basic access works
print("\nTesting basic API access (conversations.list)...")
url4 = "https://slack.com/api/conversations.list"
response4 = requests.get(url4, headers=headers, params={"limit": 3})
data4 = response4.json()

if data4.get("ok"):
    channels = data4.get("channels", [])
    print(f"  Can access {len(channels)} channels")
    for ch in channels[:3]:
        print(f"    - #{ch.get('name')}")
else:
    print(f"  Error: {data4.get('error')}")
    print(f"  Needed scope: {data4.get('needed')}")

