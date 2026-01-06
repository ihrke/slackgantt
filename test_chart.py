#!/usr/bin/env python3
"""Test generating a Gantt chart from the Slack List."""

import os
from dotenv import load_dotenv

load_dotenv()

from services.list_service import ListService
from services.chart_service import ChartService

def main():
    list_id = os.environ.get("SLACK_LIST_ID")
    
    print(f"Fetching tasks from list {list_id}...")
    
    # Fetch tasks
    list_service = ListService()
    tasks = list_service.fetch_list_items(list_id)
    
    print(f"\nFound {len(tasks)} tasks:")
    for task in tasks:
        print(f"  - {task.name}")
        print(f"    Start: {task.start_date}, End: {task.end_date}")
    
    if not tasks:
        print("\nNo tasks found!")
        return
    
    # Generate chart
    print("\nGenerating Gantt chart...")
    chart_service = ChartService()
    image_data = chart_service.generate_chart(tasks)
    
    # Save to file
    output_path = "gantt_chart.png"
    with open(output_path, "wb") as f:
        f.write(image_data)
    
    print(f"\n✅ Chart saved to: {output_path}")
    print(f"   File size: {len(image_data):,} bytes")


if __name__ == "__main__":
    main()

