#!/usr/bin/env python3
"""
Helper script to discover category option IDs from your Slack List
and generate the mapping for .env file.

Usage:
    python setup_categories.py

This will:
1. Fetch all items from your configured list
2. Show all unique category option IDs found
3. Let you enter the human-readable names for each
4. Output the CATEGORY_OPTIONS line for your .env file
"""

import os
import sys
from dotenv import load_dotenv

# Load .env first
load_dotenv()

# Set matplotlib backend before any imports
os.environ['MPLBACKEND'] = 'Agg'

import requests
from config import config


def get_category_options():
    """Fetch all unique category option IDs from the list."""
    url = "https://slack.com/api/slackLists.items.list"
    headers = {
        "Authorization": f"Bearer {config.SLACK_USER_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {"list_id": config.SLACK_LIST_ID}
    
    response = requests.post(url, headers=headers, json=payload)
    data = response.json()
    
    if not data.get("ok"):
        print(f"Error: {data.get('error')}")
        return {}
    
    # Collect all unique category option IDs with example task names
    category_field = config.LIST_CATEGORY_FIELD
    options = {}
    
    for item in data.get("items", []):
        task_name = None
        category_id = None
        
        for field in item.get("fields", []):
            if field.get("key") == "name":
                task_name = field.get("text", "")
            elif field.get("key") == category_field:
                category_id = field.get("value", "")
        
        if category_id and category_id not in options:
            options[category_id] = {"examples": []}
        if category_id and task_name:
            if len(options[category_id]["examples"]) < 3:
                options[category_id]["examples"].append(task_name)
    
    return options


def main():
    print("=" * 60)
    print("Slack List Category Setup")
    print("=" * 60)
    print()
    
    if not config.SLACK_USER_TOKEN:
        print("Error: SLACK_USER_TOKEN not configured in .env")
        sys.exit(1)
    
    if not config.SLACK_LIST_ID:
        print("Error: SLACK_LIST_ID not configured in .env")
        sys.exit(1)
    
    print(f"Fetching categories from list: {config.SLACK_LIST_ID}")
    print(f"Category field: {config.LIST_CATEGORY_FIELD}")
    print()
    
    options = get_category_options()
    
    if not options:
        print("No category options found in your list.")
        print("Make sure you have items with categories assigned.")
        sys.exit(0)
    
    print(f"Found {len(options)} unique category option(s):")
    print()
    
    # Check existing mappings
    existing = config.get_category_options()
    
    mappings = {}
    for opt_id, info in options.items():
        examples = ", ".join(info["examples"]) if info["examples"] else "(no examples)"
        
        if opt_id in existing:
            current = existing[opt_id]
            print(f"  {opt_id}")
            print(f"    Current name: {current}")
            print(f"    Example tasks: {examples}")
            answer = input(f"    Keep '{current}'? [Y/n/new name]: ").strip()
            if answer.lower() == 'n':
                new_name = input(f"    Enter new name: ").strip()
                mappings[opt_id] = new_name if new_name else opt_id
            elif answer and answer.lower() != 'y':
                mappings[opt_id] = answer
            else:
                mappings[opt_id] = current
        else:
            print(f"  {opt_id} (NEW)")
            print(f"    Example tasks: {examples}")
            name = input(f"    Enter category name: ").strip()
            mappings[opt_id] = name if name else opt_id
        print()
    
    # Generate the .env line
    mapping_str = ",".join(f"{k}:{v}" for k, v in mappings.items())
    
    print("=" * 60)
    print("Add this line to your .env file:")
    print("=" * 60)
    print()
    print(f"CATEGORY_OPTIONS={mapping_str}")
    print()
    
    # Offer to update .env automatically
    update = input("Update .env file automatically? [y/N]: ").strip().lower()
    if update == 'y':
        env_path = os.path.join(os.path.dirname(__file__), ".env")
        
        # Read existing .env
        with open(env_path, 'r') as f:
            lines = f.readlines()
        
        # Update or add CATEGORY_OPTIONS
        found = False
        for i, line in enumerate(lines):
            if line.startswith("CATEGORY_OPTIONS="):
                lines[i] = f"CATEGORY_OPTIONS={mapping_str}\n"
                found = True
                break
        
        if not found:
            lines.append(f"\nCATEGORY_OPTIONS={mapping_str}\n")
        
        with open(env_path, 'w') as f:
            f.writelines(lines)
        
        print("✅ .env file updated!")
        print("Restart the app to apply changes.")
    
    print()
    print("Done!")


if __name__ == "__main__":
    main()

