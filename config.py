"""
Configuration management for the Slack Gantt Chart app.
Loads settings from environment variables with sensible defaults.
"""

import os
from dotenv import load_dotenv

# Load environment variables from .env file if present
load_dotenv()


class Config:
    """Application configuration loaded from environment variables."""
    
    # Slack credentials
    SLACK_BOT_TOKEN: str = os.environ.get("SLACK_BOT_TOKEN", "")
    SLACK_USER_TOKEN: str = os.environ.get("SLACK_USER_TOKEN", "")  # For Lists API
    SLACK_SIGNING_SECRET: str = os.environ.get("SLACK_SIGNING_SECRET", "")
    SLACK_APP_TOKEN: str = os.environ.get("SLACK_APP_TOKEN", "")  # For Socket Mode
    
    # Field mapping for Slack Lists - use human-readable column names
    # These are matched against CSV export headers (case-insensitive)
    LIST_NAME_COLUMN: str = os.environ.get("LIST_NAME_COLUMN", "Name")
    LIST_START_DATE_COLUMN: str = os.environ.get("LIST_START_DATE_COLUMN", "Start Date")
    LIST_END_DATE_COLUMN: str = os.environ.get("LIST_END_DATE_COLUMN", "End Date")
    LIST_NOTES_COLUMN: str = os.environ.get("LIST_NOTES_COLUMN", "notes")
    LIST_CATEGORY_COLUMN: str = os.environ.get("LIST_CATEGORY_COLUMN", "category")
    
    # Legacy field IDs (will be auto-discovered if not set)
    LIST_NAME_FIELD: str = os.environ.get("LIST_NAME_FIELD", "")
    LIST_START_DATE_FIELD: str = os.environ.get("LIST_START_DATE_FIELD", "")
    LIST_END_DATE_FIELD: str = os.environ.get("LIST_END_DATE_FIELD", "")
    LIST_NOTES_FIELD: str = os.environ.get("LIST_NOTES_FIELD", "")
    LIST_CATEGORY_FIELD: str = os.environ.get("LIST_CATEGORY_FIELD", "")
    
    @classmethod
    def get_category_options(cls) -> dict[str, str]:
        """
        Load category option ID to label mappings from environment.
        Format: CATEGORY_OPTIONS=OptID1:Label1,OptID2:Label2
        Example: CATEGORY_OPTIONS=Opt8FN0LU45:Students,OptX59LW1NP:Projects
        """
        options_str = os.environ.get("CATEGORY_OPTIONS", "")
        if not options_str:
            return {}
        
        options = {}
        for mapping in options_str.split(","):
            if ":" in mapping:
                opt_id, label = mapping.split(":", 1)
                options[opt_id.strip()] = label.strip()
        return options
    
    # Target configuration
    SLACK_LIST_ID: str = os.environ.get("SLACK_LIST_ID", "")
    SLACK_CANVAS_ID: str = os.environ.get("SLACK_CANVAS_ID", "")
    SLACK_CHANNEL_ID: str = os.environ.get("SLACK_CHANNEL_ID", "")
    
    # Chart configuration
    CHART_WIDTH: int = int(os.environ.get("CHART_WIDTH", "14"))
    CHART_HEIGHT: int = int(os.environ.get("CHART_HEIGHT", "8"))
    CHART_DPI: int = int(os.environ.get("CHART_DPI", "150"))
    CHART_TITLE: str = os.environ.get("CHART_TITLE", "Project Timeline")
    
    # Color scheme for task categories (extensible)
    # Format: category_name -> hex color
    DEFAULT_TASK_COLOR: str = os.environ.get("DEFAULT_TASK_COLOR", "#3498db")
    
    # Server configuration
    PORT: int = int(os.environ.get("PORT", "3000"))
    DEBUG: bool = os.environ.get("DEBUG", "false").lower() == "true"
    
    # Polling configuration (minutes between automatic updates, 0 = disabled)
    POLL_INTERVAL_MINUTES: int = int(os.environ.get("POLL_INTERVAL_MINUTES", "0"))
    
    @classmethod
    def validate(cls) -> list[str]:
        """Validate required configuration. Returns list of missing fields."""
        required = [
            ("SLACK_BOT_TOKEN", cls.SLACK_BOT_TOKEN),
            ("SLACK_SIGNING_SECRET", cls.SLACK_SIGNING_SECRET),
        ]
        return [name for name, value in required if not value]
    
    @classmethod
    def get_category_colors(cls) -> dict[str, str]:
        """
        Load category color mappings from environment.
        Format: CATEGORY_COLORS=category1:#color1,category2:#color2
        """
        colors_str = os.environ.get("CATEGORY_COLORS", "")
        if not colors_str:
            return {}
        
        colors = {}
        for mapping in colors_str.split(","):
            if ":" in mapping:
                category, color = mapping.split(":", 1)
                colors[category.strip()] = color.strip()
        return colors


# Singleton instance
config = Config()

