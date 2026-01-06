#!/usr/bin/env python3
"""
Debug script to inspect Slack List structure and data.
"""

import os
import json
import requests
from dotenv import load_dotenv
from slack_sdk import WebClient

load_dotenv()

def main():
    token = os.environ.get("SLACK_BOT_TOKEN")
    list_id = os.environ.get("SLACK_LIST_ID")
    
    if not token:
        print("ERROR: SLACK_BOT_TOKEN not set in .env")
        return
    
    if not list_id:
        print("ERROR: SLACK_LIST_ID not set in .env")
        return
    
    print(f"Bot Token: {token[:20]}...")
    print(f"List ID: {list_id}\n")
    
    # Method 1: Try using requests directly with POST
    print("=" * 50)
    print("Method 1: Direct POST to slackLists.items.list")
    print("=" * 50)
    
    url = "https://slack.com/api/slackLists.items.list"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    payload = {"list_id": list_id}
    
    try:
        response = requests.post(url, headers=headers, json=payload)
        data = response.json()
        print(f"Response OK: {data.get('ok')}")
        
        if data.get("ok"):
            items = data.get("items", [])
            print(f"Found {len(items)} items\n")
            
            if items:
                print("First item structure:")
                print(json.dumps(items[0], indent=2, default=str))
        else:
            print(f"Error: {data.get('error')}")
            print(f"Full response: {json.dumps(data, indent=2)}")
    except Exception as e:
        print(f"Request failed: {e}")
    
    # Method 2: Try using slack_sdk WebClient
    print("\n" + "=" * 50)
    print("Method 2: Slack SDK api_call")
    print("=" * 50)
    
    client = WebClient(token=token)
    
    # Check what scopes we have
    try:
        auth_response = client.auth_test()
        print(f"Bot User: {auth_response.get('user')}")
        print(f"Team: {auth_response.get('team')}")
        print(f"Scopes: {auth_response.get('response_metadata', {}).get('scopes', 'N/A')}")
    except Exception as e:
        print(f"Auth test failed: {e}")
    
    # Try various API methods
    api_methods = [
        ("slackLists.items.list", {"list_id": list_id}),
        ("slackLists.list.get", {"list_id": list_id}),
        ("lists.items.list", {"list_id": list_id}),
    ]
    
    for method, params in api_methods:
        print(f"\nTrying {method}...")
        try:
            response = client.api_call(api_method=method, params=params)
            print(f"  OK: {response.get('ok')}")
            if response.get("ok"):
                print(f"  Response: {json.dumps(response.data, indent=2, default=str)[:500]}...")
            else:
                print(f"  Error: {response.get('error')}")
        except Exception as e:
            print(f"  Failed: {e}")


if __name__ == "__main__":
    main()
