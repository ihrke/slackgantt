"""
Service for fetching and parsing Slack List data.
Uses User OAuth Token for Lists API access.
"""

import json
import logging
import re
from datetime import date
from typing import Optional

import requests

from models.task import Task
from config import config

logger = logging.getLogger(__name__)


def extract_text_from_rich_text(rich_text_value) -> str:
    """
    Extract plain text from Slack's rich_text field format.
    
    The name field comes as a JSON array like:
    [{"type":"rich_text","elements":[{"type":"rich_text_section","elements":[{"type":"text","text":"Task name"}]}]}]
    """
    if isinstance(rich_text_value, str):
        # Try to parse as JSON
        try:
            rich_text_value = json.loads(rich_text_value)
        except json.JSONDecodeError:
            # It's already plain text
            return rich_text_value
    
    if not isinstance(rich_text_value, list):
        return str(rich_text_value)
    
    # Extract text from the nested structure
    texts = []
    for block in rich_text_value:
        if isinstance(block, dict):
            for element in block.get("elements", []):
                if isinstance(element, dict):
                    for sub_element in element.get("elements", []):
                        if isinstance(sub_element, dict) and sub_element.get("type") == "text":
                            texts.append(sub_element.get("text", ""))
    
    return " ".join(texts) if texts else str(rich_text_value)


def parse_date_value(value) -> Optional[date]:
    """Parse various date formats from Slack Lists."""
    if not value:
        return None
    
    value_str = str(value).strip()
    
    # Try ISO format (YYYY-MM-DD)
    if re.match(r'^\d{4}-\d{2}-\d{2}$', value_str):
        try:
            parts = value_str.split('-')
            return date(int(parts[0]), int(parts[1]), int(parts[2]))
        except (ValueError, IndexError):
            pass
    
    # Try timestamp (seconds since epoch)
    if value_str.isdigit() and len(value_str) >= 10:
        try:
            from datetime import datetime
            timestamp = int(value_str)
            if timestamp > 1e12:  # Milliseconds
                timestamp = timestamp / 1000
            return datetime.fromtimestamp(timestamp).date()
        except (ValueError, OSError):
            pass
    
    # Try dateutil parser as fallback
    try:
        from dateutil import parser
        return parser.parse(value_str).date()
    except (ValueError, TypeError):
        pass
    
    return None


class ListService:
    """
    Fetches and parses data from Slack Lists.
    Requires User OAuth Token with lists:read scope.
    """
    
    def __init__(self, user_token: str = None):
        """
        Initialize the ListService.
        
        Args:
            user_token: Slack User OAuth Token (xoxp-...)
        """
        self.user_token = user_token or config.SLACK_USER_TOKEN
        self._cache: dict[str, list[Task]] = {}
        self._list_info_cache: dict[str, dict] = {}
        self._csv_cache: dict[str, dict] = {}  # Cache for CSV data with readable values
        self._column_mapping: dict[str, dict[str, str]] = {}  # list_id -> {column_name: column_id}
        
        # Column names from config (human-readable)
        self.name_column = config.LIST_NAME_COLUMN
        self.start_date_column = config.LIST_START_DATE_COLUMN
        self.end_date_column = config.LIST_END_DATE_COLUMN
        self.category_column = config.LIST_CATEGORY_COLUMN
        self.notes_column = config.LIST_NOTES_COLUMN
        
        # Category option ID -> name mapping (auto-discovered)
        self.category_options: dict[str, str] = {}
    
    def fetch_list_items(self, list_id: str, force_refresh: bool = False) -> list[Task]:
        """
        Fetch all items from a Slack List and convert to Tasks.
        
        Args:
            list_id: The ID of the Slack List
            force_refresh: If True, refresh all caches
            
        Returns:
            List of Task objects with valid date fields
        """
        if not self.user_token:
            logger.error("No user token configured. Set SLACK_USER_TOKEN in .env")
            return []
        
        try:
            # Clear caches if force refresh
            if force_refresh:
                self._csv_cache.pop(list_id, None)
                self._column_mapping.pop(list_id, None)
                self.category_options = {}
            
            # Auto-discover column mappings and category options from CSV
            self._discover_schema(list_id)
            
            items = self._fetch_items_from_api(list_id)
            
            if not items:
                logger.warning(f"No items found in list {list_id}")
                return []
            
            # Convert to Task objects
            tasks = []
            for item in items:
                task = self._parse_item_to_task(item, list_id)
                if task:
                    tasks.append(task)
                else:
                    logger.debug(f"Skipped item - missing required fields")
            
            # Sort by start date
            tasks.sort(key=lambda t: (t.start_date, t.name))
            
            # Cache the result
            self._cache[list_id] = tasks
            
            logger.info(f"Fetched {len(tasks)} tasks from list {list_id}")
            return tasks
            
        except Exception as e:
            logger.exception(f"Error fetching list {list_id}: {e}")
            return self._cache.get(list_id, [])
    
    def _fetch_items_from_api(self, list_id: str) -> list[dict]:
        """Fetch items from Slack Lists API."""
        url = "https://slack.com/api/slackLists.items.list"
        headers = {
            "Authorization": f"Bearer {self.user_token}",
            "Content-Type": "application/json"
        }
        payload = {"list_id": list_id}
        
        response = requests.post(url, headers=headers, json=payload)
        data = response.json()
        
        if data.get("ok"):
            return data.get("items", [])
        else:
            logger.error(f"Slack API error: {data.get('error')}")
            return []
    
    def _discover_schema(self, list_id: str):
        """
        Auto-discover column ID mappings and category options by comparing
        CSV export (with human-readable headers/values) against API data.
        """
        if list_id in self._column_mapping and self.category_options:
            return  # Already discovered
        
        csv_data = self._fetch_csv_data(list_id)
        if not csv_data["rows"]:
            logger.warning("Could not fetch CSV data for schema discovery")
            return
        
        api_items = self._fetch_items_from_api(list_id)
        if not api_items:
            logger.warning("Could not fetch API items for schema discovery")
            return
        
        # Build column name -> ID mapping by matching values
        column_mapping = {}
        category_mapping = {}
        
        # Get CSV column headers
        csv_columns = csv_data["columns"]
        logger.debug(f"CSV columns: {csv_columns}")
        
        # Match each CSV row with its API equivalent by task name
        for csv_row in csv_data["rows"]:
            csv_name = csv_row.get("Name", "").strip()
            if not csv_name:
                continue
            
            # Find matching API item
            for api_item in api_items:
                api_name = None
                api_fields = {}
                
                for field in api_item.get("fields", []):
                    key = field.get("key", "")
                    value = field.get("value", "")
                    text = field.get("text", "")
                    api_fields[key] = {"value": value, "text": text}
                    
                    # Check if this is the name field
                    if text and text.strip() == csv_name:
                        api_name = text.strip()
                        column_mapping["Name"] = key
                
                if api_name != csv_name:
                    continue
                
                # Found matching item - now map other columns
                for csv_col in csv_columns:
                    if csv_col == "Name" or csv_col == "Created":
                        continue
                    
                    csv_value = csv_row.get(csv_col, "").strip()
                    if not csv_value:
                        continue
                    
                    # Find which API field has this value
                    for api_key, api_data in api_fields.items():
                        api_value = str(api_data["value"]).strip() if api_data["value"] else ""
                        api_text = str(api_data["text"]).strip() if api_data["text"] else ""
                        
                        # Direct match for dates and text
                        if csv_value == api_value or csv_value == api_text:
                            if csv_col not in column_mapping:
                                column_mapping[csv_col] = api_key
                                logger.debug(f"Mapped '{csv_col}' -> '{api_key}'")
                        
                        # Category option ID -> human-readable name
                        if api_value and api_value.startswith("Opt"):
                            if api_value not in category_mapping:
                                category_mapping[api_value] = csv_value
                                column_mapping[csv_col] = api_key
                                logger.debug(f"Mapped category option '{api_value}' -> '{csv_value}'")
        
        self._column_mapping[list_id] = column_mapping
        self.category_options = category_mapping
        
        logger.info(f"Auto-discovered column mapping: {column_mapping}")
        logger.info(f"Auto-discovered category mapping: {category_mapping}")
    
    def _get_column_id(self, list_id: str, column_name: str) -> Optional[str]:
        """Get the API column ID for a given human-readable column name."""
        mapping = self._column_mapping.get(list_id, {})
        return mapping.get(column_name)
    
    def _parse_item_to_task(self, item: dict, list_id: str = None) -> Optional[Task]:
        """Parse a Slack List item into a Task object."""
        fields = item.get("fields", [])
        
        # Build dicts from the fields array
        field_by_id = {}  # column_id -> value
        field_text_by_id = {}  # column_id -> text (for rich text fields)
        
        for field in fields:
            key = field.get("key", field.get("column_id", ""))
            value = field.get("value", "")
            text = field.get("text", "")
            if key:
                field_by_id[key] = value
                if text:
                    field_text_by_id[key] = text
        
        # Get column IDs using discovered mapping
        name_col_id = self._get_column_id(list_id, self.name_column)
        start_col_id = self._get_column_id(list_id, self.start_date_column)
        end_col_id = self._get_column_id(list_id, self.end_date_column)
        category_col_id = self._get_column_id(list_id, self.category_column)
        notes_col_id = self._get_column_id(list_id, self.notes_column)
        
        # Extract task name (prefer text field for rich text)
        name = ""
        if name_col_id:
            name = field_text_by_id.get(name_col_id, "") or extract_text_from_rich_text(field_by_id.get(name_col_id, ""))
        
        # Fallback: look for common name fields
        if not name:
            for key in ["name", "Name", "title", "Title"]:
                if key in field_by_id:
                    name = extract_text_from_rich_text(field_by_id[key])
                    break
                if key in field_text_by_id:
                    name = field_text_by_id[key]
                    break
        
        if not name:
            return None
        
        # Extract dates
        start_date = None
        end_date = None
        
        if start_col_id:
            start_date = parse_date_value(field_by_id.get(start_col_id))
        if end_col_id:
            end_date = parse_date_value(field_by_id.get(end_col_id))
        
        # Fallback: look for date fields by common names
        if not start_date:
            for key in ["date", "start_date", "start"]:
                if key in field_by_id:
                    start_date = parse_date_value(field_by_id[key])
                    if start_date:
                        break
        
        if not start_date:
            logger.debug(f"Task '{name}' has no valid start date")
            return None
        
        # Default end date to start date if not provided
        if not end_date:
            end_date = start_date
        
        # Extract category - apply option mapping if available
        category = None
        if category_col_id:
            category_id = field_by_id.get(category_col_id, "")
            if category_id:
                category = self.category_options.get(category_id, category_id)
        
        # Extract notes
        notes = None
        if notes_col_id:
            notes_value = field_by_id.get(notes_col_id, "")
            notes = extract_text_from_rich_text(notes_value) if notes_value else None
        
        # Collect remaining fields as metadata
        metadata = {"notes": notes} if notes else {}
        used_col_ids = {name_col_id, start_col_id, end_col_id, category_col_id, notes_col_id}
        for key, value in field_by_id.items():
            if key not in used_col_ids and value:
                metadata[key] = value
        
        return Task(
            id=item.get("id", ""),
            name=name,
            start_date=start_date,
            end_date=end_date,
            category=category,
            metadata=metadata
        )
    
    def _fetch_csv_data(self, list_id: str) -> dict:
        """
        Fetch CSV export of list to get human-readable column headers and values.
        Uses slackLists.download.start and slackLists.download.get APIs.
        
        Returns dict with:
            - columns: list of column headers
            - rows: list of dicts with human-readable values
            - category_values: set of unique category values found
        """
        if list_id in self._csv_cache:
            return self._csv_cache[list_id]
        
        result = {"columns": [], "rows": [], "category_values": set()}
        
        try:
            headers = {
                "Authorization": f"Bearer {self.user_token}",
                "Content-Type": "application/json"
            }
            
            # Start download job
            url = "https://slack.com/api/slackLists.download.start"
            response = requests.post(url, headers=headers, json={"list_id": list_id})
            data = response.json()
            
            if not data.get("ok"):
                logger.debug(f"Could not start download: {data.get('error')}")
                return result
            
            job_id = data.get("job_id")
            
            # Get download URL (with retry for job completion)
            import time
            for _ in range(5):
                time.sleep(1)
                url = "https://slack.com/api/slackLists.download.get"
                response = requests.post(url, headers=headers, json={"list_id": list_id, "job_id": job_id})
                data = response.json()
                
                if data.get("ok") and data.get("status") == "COMPLETED":
                    break
            
            if not data.get("ok") or data.get("status") != "COMPLETED":
                logger.debug(f"Download job not completed")
                return result
            
            # Download the CSV
            download_url = data.get("download_url")
            if download_url:
                csv_response = requests.get(download_url, headers={"Authorization": f"Bearer {self.user_token}"})
                if csv_response.status_code == 200:
                    import csv
                    import io
                    reader = csv.DictReader(io.StringIO(csv_response.text))
                    result["columns"] = reader.fieldnames or []
                    
                    for row in reader:
                        result["rows"].append(row)
                        # Extract category values
                        if "category" in row and row["category"]:
                            result["category_values"].add(row["category"])
                    
                    logger.info(f"Retrieved CSV with {len(result['rows'])} rows, categories: {result['category_values']}")
            
        except Exception as e:
            logger.debug(f"Error fetching CSV: {e}")
        
        self._csv_cache[list_id] = result
        return result
    
    def get_category_options(self) -> dict[str, str]:
        """Return the auto-discovered category option mapping."""
        return self.category_options
    
    def get_column_mapping(self, list_id: str) -> dict[str, str]:
        """Return the auto-discovered column name -> ID mapping."""
        return self._column_mapping.get(list_id, {})
    
    def get_list_info(self, list_id: str) -> dict:
        """
        Get the title and description of a Slack List.
        Uses CSV column headers to infer list structure.
        Falls back to configured values.
        """
        if list_id in self._list_info_cache:
            return self._list_info_cache[list_id]
        
        info = {
            "title": config.CHART_TITLE,
            "description": ""
        }
        
        # Try to get CSV data which has human-readable column names
        csv_data = self._fetch_csv_data(list_id)
        if csv_data["columns"]:
            logger.debug(f"CSV columns: {csv_data['columns']}")
        
        self._list_info_cache[list_id] = info
        return info
    
    def get_list_title(self, list_id: str) -> str:
        """Get the title of a Slack List."""
        return self.get_list_info(list_id)["title"]
    
    def get_list_description(self, list_id: str) -> str:
        """Get the description of a Slack List."""
        return self.get_list_info(list_id)["description"]
    
    def get_unique_categories(self, tasks: list[Task]) -> list[str]:
        """Get unique category values from tasks, with option ID mapping."""
        categories = set()
        for task in tasks:
            if task.category:
                # Apply mapping if available
                mapped = self.category_options.get(task.category, task.category)
                categories.add(mapped)
        return sorted(categories)
    
    def get_cached_tasks(self, list_id: str) -> Optional[list[Task]]:
        """Get cached tasks for a list if available."""
        return self._cache.get(list_id)
    
    def clear_cache(self, list_id: str = None):
        """Clear cached tasks for a specific list or all lists."""
        if list_id:
            self._cache.pop(list_id, None)
        else:
            self._cache.clear()


def create_list_service(user_token: str = None) -> ListService:
    """Factory function to create a ListService instance."""
    return ListService(user_token)
