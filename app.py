"""
Slack Gantt Chart App - Main Entry Point

This app provides:
- Interactive web dashboard with Plotly charts
- Slack OAuth authentication ("Sign in with Slack")
- API endpoints for data access
"""

# Set matplotlib backend FIRST (before any other imports that might use it)
import matplotlib
matplotlib.use('Agg')

import logging
import os
import time
from datetime import date
from functools import wraps

from flask import Flask, request, render_template, jsonify, Response, redirect, url_for, session
from authlib.integrations.flask_client import OAuth

from config import config
from models.task import Task
from services.list_service import ListService
from services.chart_service import ChartService, InteractiveChartService

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

# Initialize Flask app
flask_app = Flask(__name__)
flask_app.template_folder = os.path.join(os.path.dirname(__file__), 'templates')
flask_app.secret_key = config.SECRET_KEY

# Alias for gunicorn compatibility
app = flask_app

# Initialize OAuth
oauth = OAuth(flask_app)
oauth.register(
    name='slack',
    client_id=config.SLACK_CLIENT_ID,
    client_secret=config.SLACK_CLIENT_SECRET,
    authorize_url='https://slack.com/oauth/v2/authorize',
    access_token_url='https://slack.com/api/oauth.v2.access',
    authorize_params={
        'user_scope': 'identity.basic,identity.team',  # User identity scopes for "Sign in with Slack"
    },
)

# Initialize services
list_service = ListService()  # Uses SLACK_USER_TOKEN from config
chart_service = ChartService()
interactive_chart_service = InteractiveChartService()

# Cache for tasks (to avoid hitting Slack API on every page load)
_task_cache: dict[str, list[Task]] = {}  # list_id -> tasks
_cache_timestamp: dict[str, float] = {}  # list_id -> timestamp
CACHE_TTL_SECONDS = 60  # Cache for 1 minute


# ============================================================================
# Authentication Helpers
# ============================================================================

def login_required(f):
    """Decorator to require Slack authentication."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            # Store the original URL to redirect back after login
            session['next_url'] = request.url
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


def get_current_user():
    """Get the current logged-in user from session."""
    return session.get('user')


# ============================================================================
# OAuth Routes
# ============================================================================

@flask_app.route('/login')
def login():
    """Redirect to Slack OAuth."""
    redirect_uri = config.get_oauth_redirect_uri()
    return oauth.slack.authorize_redirect(redirect_uri)


@flask_app.route('/logout')
def logout():
    """Clear session and redirect to login."""
    session.clear()
    return redirect(url_for('login'))


@flask_app.route('/oauth/callback')
def oauth_callback():
    """Handle OAuth callback from Slack."""
    try:
        token = oauth.slack.authorize_access_token()
        
        # Extract user info from the token response
        # Slack's OAuth v2 returns user info in authed_user
        authed_user = token.get('authed_user', {})
        user_id = authed_user.get('id')
        access_token = authed_user.get('access_token')
        
        if not user_id:
            logger.error("No user ID in OAuth response")
            return "Authentication failed: No user ID", 400
        
        # Get user identity using the access token
        import requests
        headers = {'Authorization': f'Bearer {access_token}'}
        identity_response = requests.get(
            'https://slack.com/api/users.identity',
            headers=headers
        )
        identity_data = identity_response.json()
        
        if not identity_data.get('ok'):
            logger.error(f"Failed to get user identity: {identity_data.get('error')}")
            return f"Authentication failed: {identity_data.get('error')}", 400
        
        user = identity_data.get('user', {})
        team = identity_data.get('team', {})
        
        # Verify user is from the correct workspace
        team_id = team.get('id')
        if config.SLACK_TEAM_ID and team_id != config.SLACK_TEAM_ID:
            logger.warning(f"User from wrong workspace: {team_id} != {config.SLACK_TEAM_ID}")
            return "Access denied: You must be a member of the authorized workspace", 403
        
        # Store user info in session
        session['user'] = {
            'id': user.get('id'),
            'name': user.get('name'),
            'email': user.get('email'),
            'image': user.get('image_48'),
            'team_id': team_id,
            'team_name': team.get('name'),
        }
        
        logger.info(f"User {user.get('name')} logged in from workspace {team.get('name')}")
        
        # Redirect to original URL or dashboard
        next_url = session.pop('next_url', None)
        if next_url:
            return redirect(next_url)
        return redirect(url_for('dashboard'))
        
    except Exception as e:
        logger.exception(f"OAuth error: {e}")
        return f"Authentication failed: {str(e)}", 500


# ============================================================================
# Task Cache Helper
# ============================================================================

def get_cached_tasks(list_id: str, force_refresh: bool = False) -> list[Task]:
    """Get tasks with caching to reduce API calls."""
    now = time.time()
    cache_expired = (now - _cache_timestamp.get(list_id, 0)) > CACHE_TTL_SECONDS
    
    if force_refresh or cache_expired or list_id not in _task_cache:
        _task_cache[list_id] = list_service.fetch_list_items(list_id)
        _cache_timestamp[list_id] = now
    
    return _task_cache.get(list_id, [])


# ============================================================================
# Web Dashboard Routes
# ============================================================================

@flask_app.route("/")
@login_required
def dashboard():
    """Render the interactive Gantt chart dashboard."""
    import json
    
    # Get list_id from query parameter
    list_id = request.args.get('list_id')
    if not list_id:
        return render_template(
            'dashboard.html',
            error="Missing list_id parameter. Please provide a list ID: /?list_id=YOUR_LIST_ID",
            title="Error",
            user=get_current_user()
        ), 400
    
    all_tasks = get_cached_tasks(list_id)
    today = date.today()
    
    # Get filter parameters from query string
    show_past = request.args.get('show_past', 'false').lower() == 'true'
    active_categories = request.args.get('categories', '')  # Comma-separated
    
    # Get list info (title, description)
    list_info = list_service.get_list_info(list_id)
    chart_title = list_info["title"]
    list_description = list_info["description"]
    
    # Get unique categories and assign colors (from ALL tasks, not filtered)
    all_categories = set()
    for task in all_tasks:
        cat = task.category or "Uncategorized"
        all_categories.add(cat)
    
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
    for cat in sorted(all_categories):
        if cat in configured_colors:
            category_colors[cat] = configured_colors[cat]
        else:
            category_colors[cat] = color_palette[color_index % len(color_palette)]
            color_index += 1
    
    # Determine which categories are active
    if active_categories:
        active_cat_set = set(active_categories.split(','))
    else:
        active_cat_set = all_categories  # All active by default
    
    # Filter tasks for the chart
    chart_tasks = []
    for task in all_tasks:
        task_cat = task.category or "Uncategorized"
        is_past = task.end_date < today
        
        # Include if category is active AND (show_past OR not past)
        if task_cat in active_cat_set and (show_past or not is_past):
            chart_tasks.append(task)
    
    # Update interactive chart service with colors
    interactive_chart_service.color_map = category_colors
    
    # Generate chart JSON with filtered tasks
    chart_json = interactive_chart_service.generate_chart_json(chart_tasks, title=chart_title)
    
    # Prepare tasks JSON for JavaScript (ALL tasks for table)
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
        for task in all_tasks
    ])
    
    return render_template(
        'dashboard.html',
        title=chart_title,
        description=list_description,
        tasks=all_tasks,  # All tasks for table
        chart_tasks=chart_tasks,  # Filtered tasks for chart
        chart_json=chart_json,
        tasks_json=tasks_json,
        categories=sorted(all_categories),
        category_colors=category_colors,
        category_colors_json=json.dumps(category_colors),
        active_categories=list(active_cat_set),
        active_categories_json=json.dumps(list(active_cat_set)),
        show_past=show_past,
        today_date=today,
        list_id=list_id,
        user=get_current_user()
    )


@flask_app.route("/api/tasks")
@login_required
def api_tasks():
    """API endpoint to get tasks as JSON."""
    list_id = request.args.get('list_id')
    if not list_id:
        return jsonify({"success": False, "error": "Missing list_id parameter"}), 400
    
    force_refresh = request.args.get('refresh', 'false').lower() == 'true'
    
    try:
        tasks = get_cached_tasks(list_id, force_refresh=force_refresh)
        
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
@login_required
def api_chart_png():
    """API endpoint to get static chart as PNG."""
    list_id = request.args.get('list_id')
    if not list_id:
        return jsonify({"error": "Missing list_id parameter"}), 400
    
    try:
        tasks = get_cached_tasks(list_id)
        group_by = request.args.get('group_by')
        # exclude_past defaults to True, can be overridden with ?include_past=true
        include_past = request.args.get('include_past', 'false').lower() == 'true'
        image_data = chart_service.generate_chart(tasks, group_by=group_by, exclude_past=not include_past)
        
        return Response(image_data, mimetype='image/png')
    except Exception as e:
        logger.exception(f"Error generating chart: {e}")
        return jsonify({"error": str(e)}), 500


@flask_app.route("/api/chart.html")
@login_required
def api_chart_html():
    """API endpoint to get interactive chart as embeddable HTML."""
    list_id = request.args.get('list_id')
    if not list_id:
        return jsonify({"error": "Missing list_id parameter"}), 400
    
    try:
        tasks = get_cached_tasks(list_id)
        html = interactive_chart_service.generate_chart_html(tasks, full_html=False)
        
        return Response(html, mimetype='text/html')
    except Exception as e:
        logger.exception(f"Error generating chart: {e}")
        return jsonify({"error": str(e)}), 500


@flask_app.route("/health", methods=["GET"])
def health_check():
    """Health check endpoint for deployment platforms."""
    return {"status": "healthy", "app": "slackgantt"}


# ============================================================================
# Main Entry Point
# ============================================================================

def main():
    """Run the Flask app."""
    import ssl
    
    # Check if SSL certificates exist for HTTPS
    cert_file = os.path.join(os.path.dirname(__file__), 'cert.pem')
    key_file = os.path.join(os.path.dirname(__file__), 'key.pem')
    
    if os.path.exists(cert_file) and os.path.exists(key_file):
        logger.info(f"Starting SlackGantt dashboard with HTTPS on port {config.PORT}...")
        logger.info(f"Dashboard URL: https://localhost:{config.PORT}/")
        ssl_context = (cert_file, key_file)
        flask_app.run(host="0.0.0.0", port=config.PORT, debug=config.DEBUG, ssl_context=ssl_context)
    else:
        logger.info(f"Starting SlackGantt dashboard on port {config.PORT}...")
        logger.info(f"Dashboard URL: http://localhost:{config.PORT}/")
        flask_app.run(host="0.0.0.0", port=config.PORT, debug=config.DEBUG)


if __name__ == "__main__":
    main()
