"""
Configuration management for the Slack Gantt Chart app.
Loads settings from environment variables with sensible defaults.
"""

import os
import secrets
from dotenv import load_dotenv

# Load environment variables from .env file if present
load_dotenv()


class Config:
    """Application configuration loaded from environment variables."""
    
    # Slack OAuth credentials (for "Sign in with Slack")
    SLACK_CLIENT_ID: str = os.environ.get("SLACK_CLIENT_ID", "")
    SLACK_CLIENT_SECRET: str = os.environ.get("SLACK_CLIENT_SECRET", "")
    SLACK_TEAM_ID: str = os.environ.get("SLACK_TEAM_ID", "")  # Workspace ID to restrict access
    
    # Slack User Token for Lists API access
    SLACK_USER_TOKEN: str = os.environ.get("SLACK_USER_TOKEN", "")
    
    # Flask session secret key
    SECRET_KEY: str = os.environ.get("SECRET_KEY", secrets.token_hex(32))
    
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
    
    # Chart configuration
    CHART_WIDTH: int = int(os.environ.get("CHART_WIDTH", "14"))
    CHART_HEIGHT: int = int(os.environ.get("CHART_HEIGHT", "8"))
    CHART_DPI: int = int(os.environ.get("CHART_DPI", "150"))
    
    # Color scheme for task categories (extensible)
    # Format: category_name -> hex color
    DEFAULT_TASK_COLOR: str = os.environ.get("DEFAULT_TASK_COLOR", "#3498db")
    
    # Server configuration
    PORT: int = int(os.environ.get("PORT", "3000"))
    DEBUG: bool = os.environ.get("DEBUG", "false").lower() == "true"
    BASE_URL: str = os.environ.get("BASE_URL", "")  # e.g., https://slackgantt.example.com
    
    @classmethod
    def get_dashboard_url(cls) -> str:
        """Get the dashboard URL, using BASE_URL if set, otherwise localhost."""
        if cls.BASE_URL:
            return cls.BASE_URL.rstrip('/')
        return f"http://localhost:{cls.PORT}"
    
    @classmethod
    def get_oauth_redirect_uri(cls) -> str:
        """Get the OAuth callback URL."""
        return f"{cls.get_dashboard_url()}/oauth/callback"
    
    @classmethod
    def validate(cls) -> list[str]:
        """Validate required configuration. Returns list of missing fields."""
        required = [
            ("SLACK_CLIENT_ID", cls.SLACK_CLIENT_ID),
            ("SLACK_CLIENT_SECRET", cls.SLACK_CLIENT_SECRET),
            ("SLACK_USER_TOKEN", cls.SLACK_USER_TOKEN),
            ("SLACK_TEAM_ID", cls.SLACK_TEAM_ID),
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
