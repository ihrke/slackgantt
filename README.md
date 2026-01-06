# Slack Gantt Chart Generator

A Slack app that automatically generates Gantt chart images from Slack Lists and displays them in a Canvas.

## Features

- **Manual Trigger**: Use `/gantt` command to generate charts on demand
- **Optional Polling**: Auto-refresh chart at configurable intervals
- **Extensible**: Supports color-coding by category and visual grouping
- **Clean Design**: Modern, readable Gantt charts using matplotlib

> **Note**: Slack Lists does not currently emit events to the Events API, so real-time automatic updates aren't possible. Use the `/gantt` command or enable polling for periodic updates.

## Setup

### 1. Create a Slack App

1. Go to [api.slack.com/apps](https://api.slack.com/apps) and create a new app
2. Under **OAuth & Permissions**, add these Bot Token Scopes:
   - `lists:read` - Read list data
   - `files:write` - Upload chart images
   - `canvases:write` - Update canvases
   - `canvases:read` - Read canvas info
   - `chat:write` - Post messages
   - `commands` - Slash commands

3. Under **Event Subscriptions**:
   - Enable events
   - Set Request URL to `https://your-app.onrender.com/slack/events` (for HTTP mode)
   - Subscribe to bot events:
     - `app_home_opened` (optional, for App Home tab)

4. Under **Slash Commands**, create `/gantt` pointing to `https://your-app.onrender.com/slack/commands`

5. Install the app to your workspace

### 2. Environment Variables

```bash
# Required
SLACK_BOT_TOKEN=xoxb-your-bot-token
SLACK_SIGNING_SECRET=your-signing-secret

# For Socket Mode (development)
SLACK_APP_TOKEN=xapp-your-app-token

# Target resources
SLACK_LIST_ID=your-list-id
SLACK_CANVAS_ID=your-canvas-id
SLACK_CHANNEL_ID=your-channel-id

# Chart configuration (optional)
CHART_WIDTH=14
CHART_HEIGHT=8
CHART_DPI=150
CHART_TITLE=Project Timeline
CHART_GROUP_BY=category  # Group tasks by this field

# Category colors (optional)
CATEGORY_COLORS=development:#3498db,design:#9b59b6,testing:#27ae60

# Server
PORT=3000
DEBUG=false
DEBOUNCE_SECONDS=5
```

### 3. Get List and Canvas IDs

**List ID**: Open the list in Slack, click the three dots menu → "Copy link". The ID is in the URL.

**Canvas ID**: Open the canvas, click share → "Copy link". The ID is in the URL.

### 4. Deploy

#### Option A: Render (Recommended - Free Tier)

1. Fork this repo to your GitHub
2. Go to [render.com](https://render.com) and create a new Web Service
3. Connect your GitHub repo
4. Render will detect `render.yaml` automatically
5. Add environment variables in the Render dashboard

#### Option B: Local Development

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# or: venv\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt

# Set environment variables (create a .env file)
cp .env.example .env  # Edit with your values

# Run with Socket Mode
python app.py
```

## Slack List Format

Your Slack List should have these columns:

| Column | Description | Required |
|--------|-------------|----------|
| Name/Title | Task name | Yes |
| Start Date | When task begins | Yes |
| End Date | When task ends | No (defaults to start) |
| Category | For color-coding | No |
| Group | For visual grouping | No |

## Usage

### Manual Generation
Use the slash command in any channel:
```
/gantt              # Use configured list
/gantt <list_id>    # Use specific list
```

### Automatic Polling (Optional)
Set `POLL_INTERVAL_MINUTES` in your environment to auto-refresh:
```bash
POLL_INTERVAL_MINUTES=30  # Refresh every 30 minutes
```

## Customization

### Colors by Category

Set `CATEGORY_COLORS` environment variable:
```
CATEGORY_COLORS=development:#3498db,design:#9b59b6,testing:#27ae60,done:#27ae60
```

### Grouping Tasks

Set `CHART_GROUP_BY` to group tasks by a list column:
```
CHART_GROUP_BY=category
# or
CHART_GROUP_BY=phase
```

## Architecture

```
app.py              # Main entry point, event handlers
config.py           # Configuration management
models/
  task.py           # Task data model
services/
  list_service.py   # Fetch Slack List data
  chart_service.py  # Generate Gantt charts
  canvas_service.py # Upload images, update Canvas
utils/
  date_utils.py     # Date parsing helpers
```

## Troubleshooting

**Chart not generating?**
- Check that the bot is added to the channel
- Verify the SLACK_LIST_ID is correct
- Check logs for API errors

**No tasks showing?**
- Ensure your list has Start Date field populated
- Check date format (ISO 8601 works best)

**Permission errors?**
- Verify all required scopes are added
- Reinstall the app after adding scopes

## License

MIT

