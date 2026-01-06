"""
Extensible Task data model for Gantt chart generation.
Designed to accommodate additional fields like category, assignee, status, etc.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional


@dataclass
class Task:
    """
    Represents a task/item from a Slack List.
    
    Core fields:
        id: Unique identifier from Slack
        name: Display name of the task
        start_date: When the task begins
        end_date: When the task ends
        category: For color-coding (e.g., "Students", "Projects")
        
    Extensible fields (stored in metadata):
        - group: For visual grouping (e.g., "Phase 1", "Backend")
        - assignee: Person responsible
        - status: Current state (e.g., "in_progress", "done")
        - Any other custom fields from the Slack List
    """
    
    id: str
    name: str
    start_date: date
    end_date: date
    category: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)
    
    @property
    def group(self) -> str:
        """Get task group for visual grouping. Defaults to 'default'."""
        return self.metadata.get("group", "default")
    
    @property
    def assignee(self) -> Optional[str]:
        """Get task assignee if available."""
        return self.metadata.get("assignee")
    
    @property
    def status(self) -> Optional[str]:
        """Get task status if available."""
        return self.metadata.get("status")
    
    @property
    def duration_days(self) -> int:
        """Calculate task duration in days (inclusive)."""
        delta = (self.end_date - self.start_date).days
        return max(1, delta + 1)
    
    def get_color(self, color_map: dict[str, str], default: str = "#3498db") -> str:
        """
        Determine task color based on category.
        
        Args:
            color_map: Dictionary mapping category names to hex colors
            default: Default color if category not in map
            
        Returns:
            Hex color string
        """
        if self.category and self.category in color_map:
            return color_map[self.category]
        return self.metadata.get("color", default)
    
    @classmethod
    def from_slack_record(cls, record: dict[str, Any], field_mapping: dict[str, str] = None) -> Optional["Task"]:
        """
        Create a Task from a Slack List record.
        
        Args:
            record: Raw record data from Slack Lists API
            field_mapping: Optional mapping of Slack field names to Task fields
                          e.g., {"Title": "name", "Start Date": "start_date"}
                          
        Returns:
            Task instance or None if required fields are missing
        """
        from utils.date_utils import parse_date
        
        # Default field mapping (can be customized)
        mapping = field_mapping or {
            "title": "name",
            "name": "name",
            "start_date": "start_date",
            "start": "start_date",
            "end_date": "end_date",
            "end": "end_date",
            "due_date": "end_date",
        }
        
        # Extract fields from record
        fields = record.get("fields", record)
        
        # Find the name field
        name = None
        for slack_field, task_field in mapping.items():
            if task_field == "name" and slack_field in fields:
                name = fields[slack_field]
                break
        
        if not name:
            name = fields.get("title") or fields.get("name") or "Untitled"
        
        # Find date fields
        start_date = None
        end_date = None
        
        for slack_field, task_field in mapping.items():
            value = fields.get(slack_field)
            if not value:
                continue
                
            if task_field == "start_date" and not start_date:
                start_date = parse_date(str(value))
            elif task_field == "end_date" and not end_date:
                end_date = parse_date(str(value))
        
        # Require at least start date
        if not start_date:
            return None
        
        # Default end date to start date if not provided
        if not end_date:
            end_date = start_date
        
        # Collect remaining fields as metadata
        metadata = {}
        known_fields = {"id", "title", "name", "start_date", "start", "end_date", "end", "due_date"}
        for key, value in fields.items():
            if key.lower() not in known_fields:
                # Normalize key to snake_case
                normalized_key = key.lower().replace(" ", "_")
                metadata[normalized_key] = value
        
        return cls(
            id=record.get("id", ""),
            name=str(name),
            start_date=start_date,
            end_date=end_date,
            metadata=metadata
        )


@dataclass
class TaskGroup:
    """
    A group of related tasks for visual grouping in the Gantt chart.
    """
    
    name: str
    tasks: list[Task] = field(default_factory=list)
    color: Optional[str] = None  # Optional group-level color override
    
    @property
    def start_date(self) -> Optional[date]:
        """Earliest start date in the group."""
        if not self.tasks:
            return None
        return min(t.start_date for t in self.tasks)
    
    @property
    def end_date(self) -> Optional[date]:
        """Latest end date in the group."""
        if not self.tasks:
            return None
        return max(t.end_date for t in self.tasks)
    
    @classmethod
    def group_tasks(cls, tasks: list[Task], group_by: str = "group") -> list["TaskGroup"]:
        """
        Group tasks by a metadata field.
        
        Args:
            tasks: List of tasks to group
            group_by: Metadata field to group by (default: "group")
            
        Returns:
            List of TaskGroup instances, sorted by earliest start date
        """
        groups: dict[str, list[Task]] = {}
        
        for task in tasks:
            group_name = task.metadata.get(group_by, "Other")
            if group_name not in groups:
                groups[group_name] = []
            groups[group_name].append(task)
        
        # Create TaskGroup instances
        task_groups = [
            cls(name=name, tasks=sorted(group_tasks, key=lambda t: t.start_date))
            for name, group_tasks in groups.items()
        ]
        
        # Sort groups by earliest start date
        return sorted(task_groups, key=lambda g: g.start_date or date.max)

