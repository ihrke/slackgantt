"""
Gantt chart generation service using matplotlib (static) and Plotly (interactive).
Produces clean, extensible charts with support for colors and grouping.
"""

import io
import json
import logging
from datetime import date, timedelta
from typing import Optional

# Set matplotlib backend before importing pyplot (required for server use)
import matplotlib
matplotlib.use('Agg')

import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.patches as mpatches
import numpy as np
from matplotlib.figure import Figure
import plotly.graph_objects as go
from plotly.utils import PlotlyJSONEncoder

from models.task import Task, TaskGroup
from config import config

logger = logging.getLogger(__name__)

# Default color palette for categories (visually distinct, accessible)
DEFAULT_COLORS = [
    "#3498db",  # Blue
    "#e74c3c",  # Red
    "#2ecc71",  # Green
    "#9b59b6",  # Purple
    "#f39c12",  # Orange
    "#1abc9c",  # Teal
    "#e91e63",  # Pink
    "#00bcd4",  # Cyan
    "#ff9800",  # Amber
    "#607d8b",  # Blue Grey
]


class ChartService:
    """
    Generates Gantt chart images from task data.
    
    Features:
    - Horizontal bar chart layout
    - Color coding by category
    - Visual grouping with separators
    - Automatic date range scaling
    - Clean, modern aesthetic
    """
    
    def __init__(
        self,
        width: int = None,
        height: int = None,
        dpi: int = None,
        title: str = None,
        color_map: dict[str, str] = None,
    ):
        """
        Initialize the ChartService.
        
        Args:
            width: Figure width in inches
            height: Figure height in inches
            dpi: Dots per inch for output
            title: Chart title
            color_map: Mapping of category names to colors
        """
        self.width = width or config.CHART_WIDTH
        self.height = height or config.CHART_HEIGHT
        self.dpi = dpi or config.CHART_DPI
        self.title = title or config.CHART_TITLE
        self.color_map = color_map or config.get_category_colors()
        self.default_color = config.DEFAULT_TASK_COLOR
        
        # Auto-assign colors to categories not in map
        self._color_index = 0
    
    def generate_chart(
        self,
        tasks: list[Task],
        group_by: str = None,
        output_format: str = "png",
        exclude_past: bool = True
    ) -> bytes:
        """
        Generate a Gantt chart image from tasks.
        
        Args:
            tasks: List of Task objects to visualize
            group_by: Optional metadata field to group tasks by
            output_format: Image format (png, svg, pdf)
            exclude_past: If True, exclude tasks that have ended before today
            
        Returns:
            Image data as bytes
        """
        # Filter out past events if requested
        if exclude_past:
            today = date.today()
            tasks = [t for t in tasks if t.end_date >= today]
        
        if not tasks:
            return self._generate_empty_chart(output_format)
        
        # Group tasks if requested
        if group_by:
            groups = TaskGroup.group_tasks(tasks, group_by)
            return self._generate_grouped_chart(groups, output_format)
        else:
            return self._generate_simple_chart(tasks, output_format)
    
    def _generate_simple_chart(self, tasks: list[Task], output_format: str) -> bytes:
        """Generate a simple (ungrouped) Gantt chart."""
        fig, ax = self._create_figure()
        
        # Sort tasks by start date
        sorted_tasks = sorted(tasks, key=lambda t: t.start_date, reverse=True)
        
        # Calculate date range
        min_date, max_date = self._get_date_bounds(sorted_tasks)
        
        # Plot each task
        y_positions = range(len(sorted_tasks))
        
        for i, task in enumerate(sorted_tasks):
            color = self._get_task_color(task)
            self._draw_task_bar(ax, task, i, color, min_date)
        
        # Configure axes
        self._configure_axes(ax, sorted_tasks, min_date, max_date, y_positions)
        
        return self._render_to_bytes(fig, output_format)
    
    def _generate_grouped_chart(self, groups: list[TaskGroup], output_format: str) -> bytes:
        """Generate a Gantt chart with visual task groupings."""
        fig, ax = self._create_figure()
        
        # Flatten tasks while tracking group boundaries
        all_tasks = []
        group_starts = []
        group_labels = []
        
        y_pos = 0
        for group in reversed(groups):  # Reverse so first group is at top
            group_starts.append(y_pos)
            group_labels.append(group.name)
            
            sorted_group_tasks = sorted(group.tasks, key=lambda t: t.start_date, reverse=True)
            for task in sorted_group_tasks:
                all_tasks.append((task, y_pos))
                y_pos += 1
            
            y_pos += 0.5  # Add space between groups
        
        if not all_tasks:
            return self._generate_empty_chart(output_format)
        
        # Calculate date range
        min_date, max_date = self._get_date_bounds([t for t, _ in all_tasks])
        
        # Plot tasks
        for task, y in all_tasks:
            color = self._get_task_color(task)
            self._draw_task_bar(ax, task, y, color, min_date)
        
        # Draw group separators and labels
        for i, (start_y, label) in enumerate(zip(group_starts, group_labels)):
            if i > 0:
                ax.axhline(y=start_y - 0.25, color='#bdc3c7', linestyle='--', linewidth=0.5)
        
        # Configure axes for grouped view
        y_positions = [y for _, y in all_tasks]
        task_names = [t.name for t, _ in all_tasks]
        self._configure_axes(ax, [t for t, _ in all_tasks], min_date, max_date, 
                            y_positions, task_names)
        
        return self._render_to_bytes(fig, output_format)
    
    def _create_figure(self) -> tuple[Figure, plt.Axes]:
        """Create a new figure with configured size."""
        fig, ax = plt.subplots(figsize=(self.width, self.height))
        fig.patch.set_facecolor('#ffffff')
        ax.set_facecolor('#fafafa')
        return fig, ax
    
    def _draw_task_bar(
        self,
        ax: plt.Axes,
        task: Task,
        y_position: float,
        color: str,
        min_date: date
    ):
        """Draw a single task bar on the chart."""
        start_num = mdates.date2num(task.start_date)
        end_num = mdates.date2num(task.end_date)
        duration = max(end_num - start_num, 0.5)  # Minimum visible width
        
        # Draw the bar
        bar = ax.barh(
            y=y_position,
            width=duration,
            left=start_num,
            height=0.6,
            color=color,
            edgecolor='white',
            linewidth=0.5,
            alpha=0.9
        )
        
        # Add task name inside bar if it fits, otherwise to the right
        bar_width_days = duration
        text_x = start_num + duration / 2
        
        if bar_width_days > 3:  # Enough room for text inside
            ax.text(
                text_x, y_position,
                task.name,
                ha='center', va='center',
                fontsize=8,
                color='white',
                fontweight='medium',
                clip_on=True
            )
        else:
            ax.text(
                end_num + 0.5, y_position,
                task.name,
                ha='left', va='center',
                fontsize=8,
                color='#2c3e50',
                clip_on=True
            )
    
    def _configure_axes(
        self,
        ax: plt.Axes,
        tasks: list[Task],
        min_date: date,
        max_date: date,
        y_positions: list,
        task_names: list[str] = None
    ):
        """Configure axis labels, limits, and styling."""
        # Set title
        ax.set_title(self.title, fontsize=14, fontweight='bold', pad=15, color='#2c3e50')
        
        # Configure x-axis (dates) - show month and year
        ax.xaxis_date()
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %Y'))
        ax.xaxis.set_major_locator(mdates.MonthLocator(interval=1))
        
        # Add padding to date range
        padding = timedelta(days=7)
        ax.set_xlim(
            mdates.date2num(min_date - padding),
            mdates.date2num(max_date + padding)
        )
        
        # Configure y-axis
        if task_names:
            ax.set_yticks(y_positions)
            ax.set_yticklabels(task_names, fontsize=9)
        else:
            ax.set_yticks(list(y_positions))
            ax.set_yticklabels([t.name for t in tasks], fontsize=9)
        
        # Expand y limits slightly
        if y_positions:
            y_min = min(y_positions) if isinstance(y_positions, list) else min(y_positions)
            y_max = max(y_positions) if isinstance(y_positions, list) else max(y_positions)
            ax.set_ylim(y_min - 0.5, y_max + 0.5)
        
        # Grid and styling
        ax.grid(axis='x', linestyle='-', alpha=0.3, color='#bdc3c7')
        ax.set_axisbelow(True)
        
        # Add "today" vertical line
        today = date.today()
        if min_date <= today <= max_date:
            today_num = mdates.date2num(today)
            ax.axvline(x=today_num, color='#e74c3c', linestyle='--', linewidth=2, label='Today')
            # Add "Today" label at the top
            ax.text(
                today_num, ax.get_ylim()[1] + 0.1,
                'Today',
                ha='center', va='bottom',
                fontsize=9, color='#e74c3c', fontweight='bold'
            )
        
        # Remove top and right spines
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['left'].set_color('#bdc3c7')
        ax.spines['bottom'].set_color('#bdc3c7')
        
        # Rotate x-axis labels
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha='right')
        
        # Tight layout
        plt.tight_layout()
    
    def _get_task_color(self, task: Task) -> str:
        """Determine color for a task based on its category."""
        if task.category:
            if task.category in self.color_map:
                return self.color_map[task.category]
            else:
                # Auto-assign a color from the palette
                color = DEFAULT_COLORS[self._color_index % len(DEFAULT_COLORS)]
                self.color_map[task.category] = color
                self._color_index += 1
                return color
        return task.get_color(self.color_map, self.default_color)
    
    def _get_date_bounds(self, tasks: list[Task]) -> tuple[date, date]:
        """Get the min and max dates from tasks."""
        if not tasks:
            today = date.today()
            return today, today + timedelta(days=30)
        
        min_date = min(t.start_date for t in tasks)
        max_date = max(t.end_date for t in tasks)
        return min_date, max_date
    
    def _generate_empty_chart(self, output_format: str) -> bytes:
        """Generate a placeholder chart when no tasks are available."""
        fig, ax = self._create_figure()
        
        ax.text(
            0.5, 0.5,
            "No tasks with valid dates found",
            ha='center', va='center',
            fontsize=14,
            color='#7f8c8d',
            transform=ax.transAxes
        )
        ax.set_title(self.title, fontsize=14, fontweight='bold', pad=15, color='#2c3e50')
        ax.axis('off')
        
        return self._render_to_bytes(fig, output_format)
    
    def _render_to_bytes(self, fig: Figure, output_format: str) -> bytes:
        """Render figure to bytes buffer."""
        buffer = io.BytesIO()
        fig.savefig(
            buffer,
            format=output_format,
            dpi=self.dpi,
            bbox_inches='tight',
            facecolor='white',
            edgecolor='none'
        )
        plt.close(fig)
        buffer.seek(0)
        return buffer.getvalue()
    
    def add_legend(self, ax: plt.Axes, categories: list[str]):
        """Add a legend for category colors."""
        patches = [
            mpatches.Patch(color=self.color_map.get(cat, self.default_color), label=cat)
            for cat in categories
        ]
        ax.legend(
            handles=patches,
            loc='upper right',
            framealpha=0.9,
            fontsize=8
        )


def create_chart_service(
    color_map: dict[str, str] = None,
    **kwargs
) -> ChartService:
    """Factory function to create a ChartService instance."""
    return ChartService(color_map=color_map, **kwargs)


class InteractiveChartService:
    """
    Generates interactive Gantt charts using Plotly.
    
    Features:
    - Hover tooltips with task details
    - Zoom and pan
    - Color coding by category
    - Responsive layout
    """
    
    def __init__(
        self,
        title: str = None,
        color_map: dict[str, str] = None,
    ):
        """
        Initialize the InteractiveChartService.
        
        Args:
            title: Chart title
            color_map: Mapping of category names to colors
        """
        self.title = title or config.CHART_TITLE
        self.color_map = color_map or config.get_category_colors()
        self.default_color = config.DEFAULT_TASK_COLOR
        self._color_index = 0
    
    def generate_plotly_chart(self, tasks: list[Task], title: str = None, categories_filter: list[str] = None) -> go.Figure:
        """
        Generate an interactive Plotly Gantt chart.
        
        Args:
            tasks: List of Task objects to visualize
            title: Optional title override
            categories_filter: Optional list of categories to display
            
        Returns:
            Plotly Figure object
        """
        if not tasks:
            return self._generate_empty_chart()
        
        # Filter by categories if specified
        if categories_filter:
            tasks = [t for t in tasks if t.category in categories_filter]
            if not tasks:
                return self._generate_empty_chart()
        
        # Sort tasks by category then by start date
        sorted_tasks = sorted(tasks, key=lambda t: (t.category or '', t.start_date), reverse=True)
        
        # Build the figure using timeline approach for better date handling
        fig = go.Figure()
        
        # Track which categories have been added to legend
        legend_added = set()
        
        # Get today's date for filtering and today marker
        today = date.today()
        
        for i, task in enumerate(sorted_tasks):
            color = self._get_task_color(task)
            duration_days = (task.end_date - task.start_date).days + 1
            
            # Extract notes from metadata if available
            notes = self._extract_notes(task)
            
            # Create hover text with details
            hover_text = (
                f"<b>{task.name}</b><br>"
                f"Start: {task.start_date.strftime('%b %d, %Y')}<br>"
                f"End: {task.end_date.strftime('%b %d, %Y')}<br>"
                f"Duration: {duration_days} days"
            )
            
            # Add category/metadata to hover if available
            if task.category:
                hover_text += f"<br>Category: {task.category}"
            if task.assignee:
                hover_text += f"<br>Assignee: {task.assignee}"
            if notes:
                hover_text += f"<br><br><i>Notes:</i> {notes}"
            
            # Convert dates to datetime strings for Plotly
            start_str = task.start_date.isoformat()
            end_str = task.end_date.isoformat()
            
            # Show in legend only once per category
            category_key = task.category or "Uncategorized"
            show_legend = category_key not in legend_added
            if show_legend:
                legend_added.add(category_key)
            
            # Use scatter with horizontal bars for better date axis handling
            fig.add_trace(go.Scatter(
                x=[start_str, end_str],
                y=[task.name, task.name],
                mode='lines',
                line=dict(color=color, width=25),
                hovertemplate=hover_text + "<extra></extra>",
                name=category_key,
                legendgroup=category_key,
                showlegend=show_legend,
                customdata=[{"end_date": end_str, "is_past": task.end_date < today}]  # For filtering
            ))
        
        # Calculate initial x-axis range: start at earliest ongoing event
        ongoing_tasks = [t for t in tasks if t.start_date <= today <= t.end_date]
        
        if ongoing_tasks:
            # Start from earliest ongoing task
            range_start = min(t.start_date for t in ongoing_tasks)
        else:
            # No ongoing tasks - start from earliest future task or overall min
            future_tasks = [t for t in tasks if t.start_date > today]
            if future_tasks:
                range_start = min(t.start_date for t in future_tasks)
            else:
                range_start = min(t.start_date for t in tasks)
        
        # End range at max date + some padding
        max_date = max(t.end_date for t in tasks)
        range_end = max_date + timedelta(days=30)
        
        # Configure layout
        chart_title = title or self.title
        fig.update_layout(
            title=dict(
                text=chart_title,
                font=dict(size=20, color='#2c3e50'),
                x=0.5,
                xanchor='center'
            ),
            xaxis=dict(
                type='date',
                title='Timeline',
                gridcolor='#e0e0e0',
                showgrid=True,
                tickformat='%b %d, %Y',
                dtick='M1',  # Monthly ticks
                range=[range_start.isoformat(), range_end.isoformat()],
                rangeslider=dict(visible=True),  # Add range slider for easy navigation
            ),
            yaxis=dict(
                title='',
                autorange='reversed',  # Keep original order
                showgrid=False,
            ),
            barmode='overlay',
            plot_bgcolor='#fafafa',
            paper_bgcolor='white',
            margin=dict(l=20, r=20, t=60, b=80),
            hoverlabel=dict(
                bgcolor='white',
                font_size=13,
                font_family='system-ui, -apple-system, sans-serif'
            ),
            height=max(500, len(tasks) * 40 + 150),  # Dynamic height
            legend=dict(
                orientation='h',
                yanchor='bottom',
                y=1.02,
                xanchor='right',
                x=1,
                title='Categories'
            )
        )
        
        # Add today marker
        min_date = min(t.start_date for t in tasks)
        
        if min_date <= today <= max_date:
            fig.add_shape(
                type="line",
                x0=today,
                x1=today,
                y0=0,
                y1=1,
                yref="paper",
                line=dict(color="#e74c3c", width=2, dash="dash")
            )
            fig.add_annotation(
                x=today,
                y=1.02,
                yref="paper",
                text="Today",
                showarrow=False,
                font=dict(color="#e74c3c", size=11)
            )
        
        return fig
    
    def generate_chart_json(self, tasks: list[Task], title: str = None, categories_filter: list[str] = None) -> str:
        """
        Generate Plotly chart as JSON for embedding in HTML.
        
        Args:
            tasks: List of Task objects
            title: Optional title override
            categories_filter: Optional list of categories to display
            
        Returns:
            JSON string for Plotly.js
        """
        fig = self.generate_plotly_chart(tasks, title=title, categories_filter=categories_filter)
        return json.dumps(fig.to_dict(), cls=PlotlyJSONEncoder)
    
    def generate_chart_html(self, tasks: list[Task], title: str = None, full_html: bool = False) -> str:
        """
        Generate Plotly chart as HTML.
        
        Args:
            tasks: List of Task objects
            title: Optional title override
            full_html: If True, return complete HTML document
            
        Returns:
            HTML string
        """
        fig = self.generate_plotly_chart(tasks, title=title)
        return fig.to_html(full_html=full_html, include_plotlyjs='cdn')
    
    def _get_task_color(self, task: Task) -> str:
        """Determine color for a task based on its category."""
        if task.category:
            if task.category in self.color_map:
                return self.color_map[task.category]
            else:
                color = DEFAULT_COLORS[self._color_index % len(DEFAULT_COLORS)]
                self.color_map[task.category] = color
                self._color_index += 1
                return color
        return task.get_color(self.color_map, self.default_color)
    
    def _extract_notes(self, task: Task) -> str:
        """Extract notes from task metadata."""
        # Notes are already extracted and stored in metadata by ListService
        notes = task.metadata.get('notes', '')
        
        # Handle rich_text JSON format from Slack (in case it's still raw)
        if isinstance(notes, str) and notes.startswith('['):
            try:
                rich_text = json.loads(notes)
                texts = []
                for block in rich_text:
                    if isinstance(block, dict):
                        for element in block.get("elements", []):
                            if isinstance(element, dict):
                                for sub in element.get("elements", []):
                                    if isinstance(sub, dict) and sub.get("type") == "text":
                                        texts.append(sub.get("text", ""))
                if texts:
                    return " ".join(texts)
            except json.JSONDecodeError:
                pass
        
        return notes if isinstance(notes, str) else ""
    
    def _generate_empty_chart(self) -> go.Figure:
        """Generate a placeholder chart when no tasks are available."""
        fig = go.Figure()
        
        fig.add_annotation(
            text="No tasks with valid dates found",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
            font=dict(size=16, color='#7f8c8d')
        )
        
        fig.update_layout(
            title=dict(text=self.title, font=dict(size=20, color='#2c3e50')),
            plot_bgcolor='#fafafa',
            paper_bgcolor='white',
            height=300
        )
        
        return fig


def create_interactive_chart_service(
    color_map: dict[str, str] = None,
    **kwargs
) -> InteractiveChartService:
    """Factory function to create an InteractiveChartService instance."""
    return InteractiveChartService(color_map=color_map, **kwargs)

