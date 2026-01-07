"""
Slack Gantt Chart App - Main Entry Point

This app provides:
- Slack slash command (/gantt) to generate charts
- Interactive web dashboard with Plotly charts
- API endpoints for data access
"""

# Set matplotlib backend FIRST (before any other imports that might use it)
import matplotlib
matplotlib.use('Agg')

import logging
import os
import threading
import time
from datetime import date
from typing import Optional

from flask import Flask, request, render_template, jsonify, Response
from slack_bolt import App
from slack_bolt.adapter.flask import SlackRequestHandler
from slack_sdk import WebClient

from config import config
from models.task import Task, TaskGroup
from services.list_service import ListService
from services.chart_service import ChartService, InteractiveChartService
from services.canvas_service import CanvasService

# Configure logging
logging.basicConfig(
    level=logging.DEBUG if config.DEBUG else logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Validate configuration
missing = config.validate()
if missing:
    logger.warning(f"Missing configuration: {', '.join(missing)}")
    logger.warning("Set these environment variables before running in production")

# Initialize Slack Bolt app
# Use Socket Mode for development, HTTP for production
if config.SLACK_APP_TOKEN:
    # Socket Mode (recommended for development)
    from slack_bolt.adapter.socket_mode import SocketModeHandler
    bolt_app = App(token=config.SLACK_BOT_TOKEN)
else:
    # HTTP Mode (for production with webhooks)
    bolt_app = App(
        token=config.SLACK_BOT_TOKEN,
        signing_secret=config.SLACK_SIGNING_SECRET
    )

# Initialize services
client = WebClient(token=config.SLACK_BOT_TOKEN)
list_service = ListService()  # Uses SLACK_USER_TOKEN from config
chart_service = ChartService()
interactive_chart_service = InteractiveChartService()
canvas_service = CanvasService(client)

# Cache for tasks (to avoid hitting Slack API on every page load)
_task_cache: list[Task] = []
_cache_timestamp: float = 0
CACHE_TTL_SECONDS = 60  # Cache for 1 minute

# Polling state
_polling_thread: Optional[threading.Thread] = None
_stop_polling = threading.Event()


def regenerate_chart():
    """
    Regenerate the Gantt chart from the configured list and update the canvas.
    """
    global _last_update_time
    
    if not config.SLACK_LIST_ID:
        logger.warning("SLACK_LIST_ID not configured, skipping chart generation")
        return
    
    logger.info(f"Regenerating chart from list {config.SLACK_LIST_ID}")
    
    try:
        # Fetch tasks from the list
        tasks = list_service.fetch_list_items(config.SLACK_LIST_ID)
        
        if not tasks:
            logger.warning("No valid tasks found in list")
        
        # Generate the chart
        # Check if we should group by any field
        group_by = os.environ.get("CHART_GROUP_BY")  # e.g., "category" or "group"
        image_data = chart_service.generate_chart(tasks, group_by=group_by)
        
        # Update canvas or post to channel
        if config.SLACK_CANVAS_ID:
            success = canvas_service.upload_and_update_canvas(
                image_data=image_data,
                canvas_id=config.SLACK_CANVAS_ID,
                channel_id=config.SLACK_CHANNEL_ID,
                title=config.CHART_TITLE
            )
        elif config.SLACK_CHANNEL_ID:
            # Fallback: post directly to channel
            success = canvas_service.post_to_channel(
                image_data=image_data,
                channel_id=config.SLACK_CHANNEL_ID,
                message=f"📊 {config.CHART_TITLE} - Updated"
            )
        else:
            logger.warning("Neither SLACK_CANVAS_ID nor SLACK_CHANNEL_ID configured")
            success = False
        
        if success:
            logger.info("Chart updated successfully")
            _last_update_time = time.time()
        else:
            logger.error("Failed to update chart")
            
    except Exception as e:
        logger.exception(f"Error regenerating chart: {e}")


def start_polling():
    """
    Start background polling for list changes.
    Only runs if POLL_INTERVAL_MINUTES is set in environment.
    """
    global _polling_thread
    
    interval_minutes = int(os.environ.get("POLL_INTERVAL_MINUTES", "0"))
    if interval_minutes <= 0:
        logger.info("Polling disabled (set POLL_INTERVAL_MINUTES to enable)")
        return
    
    interval_seconds = interval_minutes * 60
    
    def poll_loop():
        logger.info(f"Starting polling every {interval_minutes} minutes")
        while not _stop_polling.is_set():
            regenerate_chart()
            _stop_polling.wait(interval_seconds)
    
    _polling_thread = threading.Thread(target=poll_loop, daemon=True)
    _polling_thread.start()


def stop_polling():
    """Stop the background polling thread."""
    _stop_polling.set()


# ============================================================================
# Slack Event Handlers
# ============================================================================

# NOTE: Slack Lists does not currently emit events to the Events API.
# Chart updates are triggered via:
#   1. /gantt slash command (manual)
#   2. Scheduled polling (if POLL_INTERVAL_MINUTES is set)
#
# If Slack adds list events in the future, handlers can be added here.


# ============================================================================
# Slash Command (Manual Trigger)
# ============================================================================

@bolt_app.command("/gantt")
def handle_gantt_command(ack, command, respond, client):
    """
    Handle /gantt slash command for manual chart generation.
    
    Usage:
        /gantt          - Regenerate chart from configured list
        /gantt [list_id] - Generate chart from specified list
    """
    ack()
    
    # Parse optional list ID from command text
    text = command.get("text", "").strip()
    list_id = text if text else config.SLACK_LIST_ID
    
    if not list_id:
        respond("Please configure SLACK_LIST_ID or provide a list ID: `/gantt <list_id>`")
        return
    
    try:
        # Fetch and generate
        tasks = list_service.fetch_list_items(list_id)
        
        # Update cache
        global _task_cache, _cache_timestamp
        _task_cache = tasks
        _cache_timestamp = time.time()
        
        if not tasks:
            respond("No tasks with valid dates found in the list.")
            return
        
        # Filter to active tasks for the PNG (excludes past events)
        today = date.today()
        active_tasks = [t for t in tasks if t.end_date >= today]
        
        if not active_tasks:
            respond("No active tasks found (all tasks have ended). Check the dashboard for completed events.")
            return
        
        group_by = os.environ.get("CHART_GROUP_BY")
        image_data = chart_service.generate_chart(tasks, group_by=group_by, exclude_past=True)
        
        # Build dashboard URL
        dashboard_url = f"{config.get_dashboard_url()}/"
        
        # Get chart title from list
        chart_title = list_service.get_list_title(list_id)
        
        # Calculate date range for summary (active tasks only)
        min_date = min(t.start_date for t in active_tasks).strftime('%b %d, %Y')
        max_date = max(t.end_date for t in active_tasks).strftime('%b %d, %Y')
        
        # Count stats
        total_tasks = len(tasks)
        active_count = len(active_tasks)
        past_count = total_tasks - active_count
        
        # Try to update Canvas if configured
        canvas_updated = False
        if config.SLACK_CANVAS_ID and config.SLACK_CANVAS_ID != "your-canvas-id":
            try:
                canvas_updated = canvas_service.upload_and_update_canvas(
                    image_data=image_data,
                    canvas_id=config.SLACK_CANVAS_ID,
                    channel_id=config.SLACK_CHANNEL_ID if config.SLACK_CHANNEL_ID != "your-channel-id" else None,
                    title=chart_title
                )
                if canvas_updated:
                    logger.info(f"Canvas {config.SLACK_CANVAS_ID} updated successfully")
            except Exception as e:
                logger.warning(f"Could not update canvas: {e}")
        
        # Respond with ephemeral message (only visible to the user)
        past_note = f" ({past_count} completed hidden)" if past_count > 0 else ""
        canvas_note = "📋 Canvas updated with chart\n" if canvas_updated else ""
        respond(
            f"✅ *{chart_title}* updated!\n"
            f"_{active_count} active tasks{past_note} • {min_date} to {max_date}_\n\n"
            f"{canvas_note}"
            f"🔗 <{dashboard_url}|View Interactive Dashboard>",
            response_type="ephemeral"
        )
            
    except Exception as e:
        logger.exception(f"Error in /gantt command: {e}")
        respond(f"❌ Error generating chart: {str(e)}", response_type="ephemeral")


# ============================================================================
# App Home Tab
# ============================================================================

@bolt_app.event("app_home_opened")
def handle_app_home_opened(client, event, logger):
    """Display app home with status and quick actions."""
    user_id = event["user"]
    
    try:
        client.views_publish(
            user_id=user_id,
            view={
                "type": "home",
                "blocks": [
                    {
                        "type": "header",
                        "text": {
                            "type": "plain_text",
                            "text": "📊 Gantt Chart Generator"
                        }
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": "This app automatically generates Gantt charts from your Slack Lists."
                        }
                    },
                    {
                        "type": "divider"
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": "*Configuration*\n"
                                   f"• List ID: `{config.SLACK_LIST_ID or 'Not configured'}`\n"
                                   f"• Canvas ID: `{config.SLACK_CANVAS_ID or 'Not configured'}`\n"
                                   f"• Channel ID: `{config.SLACK_CHANNEL_ID or 'Not configured'}`"
                        }
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": "*Quick Actions*\nUse `/gantt` in any channel to manually generate a chart."
                        }
                    }
                ]
            }
        )
    except Exception as e:
        logger.error(f"Error publishing home view: {e}")


# ============================================================================
# Flask App for HTTP Mode
# ============================================================================

flask_app = Flask(__name__)
flask_app.template_folder = os.path.join(os.path.dirname(__file__), 'templates')
handler = SlackRequestHandler(bolt_app)

# Alias for gunicorn compatibility (allows both `app:app` and `app:flask_app`)
app = flask_app


def get_cached_tasks(force_refresh: bool = False) -> list[Task]:
    """Get tasks with caching to reduce API calls."""
    global _task_cache, _cache_timestamp
    
    now = time.time()
    cache_expired = (now - _cache_timestamp) > CACHE_TTL_SECONDS
    
    if force_refresh or cache_expired or not _task_cache:
        if config.SLACK_LIST_ID:
            _task_cache = list_service.fetch_list_items(config.SLACK_LIST_ID)
            _cache_timestamp = now
        else:
            _task_cache = []
    
    return _task_cache


# ============================================================================
# Web Dashboard Routes
# ============================================================================

@flask_app.route("/")
def dashboard():
    """Render the interactive Gantt chart dashboard."""
    import json
    
    tasks = get_cached_tasks()
    
    # Get list info (title, description)
    list_info = list_service.get_list_info(config.SLACK_LIST_ID)
    chart_title = list_info["title"]
    list_description = list_info["description"]
    
    # Get unique categories and assign colors
    categories = set()
    for task in tasks:
        cat = task.category or "Uncategorized"
        categories.add(cat)
    
    # Build category color map
    category_colors = {}
    color_palette = [
        "#3498db",  # Blue
        "#e74c3c",  # Red
        "#2ecc71",  # Green
        "#9b59b6",  # Purple
        "#f39c12",  # Orange
        "#1abc9c",  # Teal
        "#e91e63",  # Pink
        "#00bcd4",  # Cyan
    ]
    
    # Use configured colors first, then assign from palette
    configured_colors = config.get_category_colors()
    color_index = 0
    for cat in sorted(categories):
        if cat in configured_colors:
            category_colors[cat] = configured_colors[cat]
        else:
            category_colors[cat] = color_palette[color_index % len(color_palette)]
            color_index += 1
    
    # Update interactive chart service with colors
    interactive_chart_service.color_map = category_colors
    
    # Generate chart JSON
    chart_json = interactive_chart_service.generate_chart_json(tasks, title=chart_title)
    
    # Prepare tasks JSON for JavaScript
    today = date.today()
    tasks_json = json.dumps([
        {
            "id": task.id,
            "name": task.name,
            "start_date": task.start_date.isoformat(),
            "end_date": task.end_date.isoformat(),
            "category": task.category or "Uncategorized",
            "duration_days": task.duration_days,
            "notes": task.metadata.get("notes", ""),
            "is_past": task.end_date < today
        }
        for task in tasks
    ])
    
    return render_template(
        'dashboard.html',
        title=chart_title,
        description=list_description,
        tasks=tasks,
        chart_json=chart_json,
        tasks_json=tasks_json,
        categories=sorted(categories),
        category_colors=category_colors,
        category_colors_json=json.dumps(category_colors),
        today_date=date.today()
    )


@flask_app.route("/api/tasks")
def api_tasks():
    """API endpoint to get tasks as JSON."""
    force_refresh = request.args.get('refresh', 'false').lower() == 'true'
    
    try:
        tasks = get_cached_tasks(force_refresh=force_refresh)
        
        return jsonify({
            "success": True,
            "tasks": [
                {
                    "id": task.id,
                    "name": task.name,
                    "start_date": task.start_date.isoformat(),
                    "end_date": task.end_date.isoformat(),
                    "duration_days": task.duration_days,
                    "category": task.category,
                    "metadata": task.metadata
                }
                for task in tasks
            ],
            "count": len(tasks)
        })
    except Exception as e:
        logger.exception(f"Error fetching tasks: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@flask_app.route("/api/chart.png")
def api_chart_png():
    """API endpoint to get static chart as PNG."""
    try:
        tasks = get_cached_tasks()
        group_by = request.args.get('group_by')
        # exclude_past defaults to True, can be overridden with ?include_past=true
        include_past = request.args.get('include_past', 'false').lower() == 'true'
        image_data = chart_service.generate_chart(tasks, group_by=group_by, exclude_past=not include_past)
        
        return Response(image_data, mimetype='image/png')
    except Exception as e:
        logger.exception(f"Error generating chart: {e}")
        return jsonify({"error": str(e)}), 500


@flask_app.route("/api/chart.html")
def api_chart_html():
    """API endpoint to get interactive chart as embeddable HTML."""
    try:
        tasks = get_cached_tasks()
        html = interactive_chart_service.generate_chart_html(tasks, full_html=False)
        
        return Response(html, mimetype='text/html')
    except Exception as e:
        logger.exception(f"Error generating chart: {e}")
        return jsonify({"error": str(e)}), 500


# ============================================================================
# Slack Event Routes
# ============================================================================

@flask_app.route("/slack/events", methods=["POST"])
def slack_events():
    """Handle incoming Slack events via HTTP."""
    return handler.handle(request)


@flask_app.route("/slack/commands", methods=["POST"])
def slack_commands():
    """Handle incoming slash commands via HTTP."""
    return handler.handle(request)


@flask_app.route("/health", methods=["GET"])
def health_check():
    """Health check endpoint for deployment platforms."""
    return {"status": "healthy", "app": "slackgantt"}


# ============================================================================
# Webhook Endpoint for Workflows
# ============================================================================

@flask_app.route("/webhook/update", methods=["POST"])
def webhook_update():
    """
    Webhook endpoint to trigger chart update.
    
    Can be called from Slack Workflows via "Send a webhook" step.
    
    Optional: Set WEBHOOK_SECRET in .env for authentication.
    If set, include header: Authorization: Bearer <secret>
    """
    # Check authentication if secret is configured
    webhook_secret = os.environ.get("WEBHOOK_SECRET", "")
    if webhook_secret:
        auth_header = request.headers.get("Authorization", "")
        if auth_header != f"Bearer {webhook_secret}":
            return {"ok": False, "error": "unauthorized"}, 401
    
    try:
        # Regenerate chart (same as /gantt command)
        regenerate_chart()
        return {"ok": True, "message": "Chart updated"}
    except Exception as e:
        logger.error(f"Webhook update error: {e}")
        return {"ok": False, "error": str(e)}, 500


# ============================================================================
# Main Entry Point
# ============================================================================

def main():
    """Run the Slack app."""
    # Start background polling if configured
    start_polling()
    
    if config.SLACK_APP_TOKEN:
        # Socket Mode + Flask web server (development)
        logger.info("Starting in Socket Mode + Flask web server...")
        from slack_bolt.adapter.socket_mode import SocketModeHandler
        
        # Start Socket Mode in a background thread
        socket_handler = SocketModeHandler(bolt_app, config.SLACK_APP_TOKEN)
        socket_thread = threading.Thread(target=socket_handler.start, daemon=True)
        socket_thread.start()
        
        # Run Flask in the main thread
        logger.info(f"Web dashboard available at http://localhost:{config.PORT}/")
        flask_app.run(host="0.0.0.0", port=config.PORT, debug=False, use_reloader=False)
    else:
        # HTTP Mode (production)
        logger.info(f"Starting HTTP server on port {config.PORT}...")
        flask_app.run(host="0.0.0.0", port=config.PORT, debug=config.DEBUG)


if __name__ == "__main__":
    main()

