"""
Service for uploading images and updating Slack Canvases.
"""

import logging
from typing import Optional

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from config import config

logger = logging.getLogger(__name__)


class CanvasService:
    """
    Manages Slack Canvas updates with Gantt chart images.
    
    Flow:
    1. Upload image to Slack via files.upload
    2. Update Canvas section with the new image
    """
    
    def __init__(self, client: WebClient):
        """
        Initialize the CanvasService.
        
        Args:
            client: Slack WebClient instance
        """
        self.client = client
        self._last_file_id: Optional[str] = None
    
    def upload_and_update_canvas(
        self,
        image_data: bytes,
        canvas_id: str,
        channel_id: str = None,
        filename: str = "gantt_chart.png",
        title: str = "Project Gantt Chart"
    ) -> bool:
        """
        Upload a chart image and update the target Canvas with a link.
        
        Args:
            image_data: PNG image data as bytes
            canvas_id: ID of the Canvas to update
            channel_id: Channel to share the file in (optional)
            filename: Name for the uploaded file
            title: Title for the file
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Step 1: Upload the image
            file_id, permalink = self._upload_image(image_data, channel_id, filename, title)
            if not file_id:
                return False
            
            # Step 2: Update the Canvas with a link to the image
            success = self._update_canvas(canvas_id, file_id, title, permalink)
            
            # Step 3: Delete old file to save storage
            if success and self._last_file_id and self._last_file_id != file_id:
                self._delete_old_file(self._last_file_id)
            
            self._last_file_id = file_id
            return success
            
        except Exception as e:
            logger.error(f"Error updating canvas: {e}")
            return False
    
    def _upload_image(
        self,
        image_data: bytes,
        channel_id: str = None,
        filename: str = "gantt_chart.png",
        title: str = "Project Gantt Chart"
    ) -> tuple[Optional[str], Optional[str]]:
        """
        Upload an image to Slack privately (not posted to any channel).
        
        Returns:
            Tuple of (file_id, permalink) if successful, (None, None) otherwise
        """
        try:
            # Upload privately - no channel means no message posted
            response = self.client.files_upload_v2(
                content=image_data,
                filename=filename,
                title=title
            )
            
            if response.get("ok"):
                file_info = response.get("file", {})
                file_id = file_info.get("id")
                permalink = file_info.get("permalink", "")
                logger.info(f"Uploaded image: {file_id}, permalink: {permalink}")
                return file_id, permalink
            else:
                logger.error(f"Upload failed: {response.get('error')}")
                return None, None
                
        except SlackApiError as e:
            logger.error(f"Slack API error uploading image: {e.response['error']}")
            return None, None
    
    def _update_canvas(self, canvas_id: str, file_id: str, title: str, permalink: str = None) -> bool:
        """
        Update a Canvas with the chart image.
        
        Strategy: Try to REPLACE existing section, otherwise insert new one.
        """
        try:
            # Try to find existing section with our title
            existing_section_id = self._find_gantt_section(canvas_id, title)
            
            if existing_section_id:
                # Replace existing section
                return self._replace_chart_section(canvas_id, existing_section_id, file_id, title, permalink)
            else:
                # No existing section, insert at start
                return self._add_chart_to_canvas(canvas_id, file_id, title, permalink)
                
        except SlackApiError as e:
            logger.error(f"Slack API error updating canvas: {e.response['error']}")
            return False
    
    def _find_gantt_section(self, canvas_id: str, title: str) -> Optional[str]:
        """Find the section ID containing our gantt chart title."""
        try:
            response = self.client.api_call(
                api_method="canvases.sections.lookup",
                json={
                    "canvas_id": canvas_id,
                    "criteria": {"contains_text": f"📊 {title}"}
                }
            )
            
            if response.get("ok"):
                sections = response.get("sections", [])
                if sections:
                    return sections[0].get("id")
        except Exception as e:
            logger.debug(f"Could not find existing section: {e}")
        return None
    
    def _replace_chart_section(
        self,
        canvas_id: str,
        section_id: str,
        file_id: str,
        title: str,
        permalink: str = None
    ) -> bool:
        """Replace existing chart section with new content."""
        import datetime
        
        try:
            if not permalink:
                permalink = f"https://slack.com/files/{file_id}"
            
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
            dashboard_url = f"{config.get_dashboard_url()}/"
            
            # Image embed - files are NOT deleted so references stay valid
            markdown_content = f"**📊 {title}** | [Dashboard]({dashboard_url}) | _{timestamp}_\n\n![Chart]({permalink})"
            
            response = self.client.api_call(
                api_method="canvases.edit",
                json={
                    "canvas_id": canvas_id,
                    "changes": [{
                        "operation": "replace",
                        "section_id": section_id,
                        "document_content": {
                            "type": "markdown",
                            "markdown": markdown_content
                        }
                    }]
                }
            )
            
            if response.get("ok"):
                logger.info(f"Replaced existing chart section")
                return True
            else:
                logger.error(f"Replace failed: {response.get('error')}")
                # Fall back to delete + insert
                return self._add_chart_to_canvas(canvas_id, file_id, title, permalink)
                
        except Exception as e:
            logger.error(f"Error replacing section: {e}")
            return self._add_chart_to_canvas(canvas_id, file_id, title, permalink)
    
    def _delete_existing_gantt_sections(self, canvas_id: str, title: str = "Timeline"):
        """Find and delete existing gantt chart sections from the canvas."""
        # Search for multiple patterns since markdown creates multiple sections
        # Include patterns for all parts of our gantt block AND orphaned content
        search_patterns = [
            f"📊 {title}",
            "Last updated:",
            "gantt_chart.png",
            "![Gantt Chart]",
            "View Interactive Dashboard",
            "localhost:3000",
            "This file was deleted",  # Catch dead file links
            "files/U0A6M5NMX19",  # Catch old file permalinks by user ID
            "GANTT_CHART",  # Old marker from previous versions
            "cogneuro-uit.slack.com/files",  # Catch embedded image URLs
            "Gantt Chart",  # Generic match for image alt text
        ]
        
        deleted_ids = set()
        
        for pattern in search_patterns:
            try:
                response = self.client.api_call(
                    api_method="canvases.sections.lookup",
                    json={
                        "canvas_id": canvas_id,
                        "criteria": {"contains_text": pattern}
                    }
                )
                
                if response.get("ok"):
                    sections = response.get("sections", [])
                    for section in sections:
                        section_id = section.get("id")
                        if section_id and section_id not in deleted_ids:
                            try:
                                self.client.api_call(
                                    api_method="canvases.edit",
                                    json={
                                        "canvas_id": canvas_id,
                                        "changes": [{
                                            "operation": "delete",
                                            "section_id": section_id
                                        }]
                                    }
                                )
                                deleted_ids.add(section_id)
                                logger.debug(f"Deleted old gantt section: {section_id}")
                            except Exception as e:
                                logger.debug(f"Could not delete section {section_id}: {e}")
            except Exception as e:
                logger.debug(f"Could not look up sections for '{pattern}': {e}")
        
        if deleted_ids:
            logger.info(f"Deleted {len(deleted_ids)} old gantt sections from canvas")
    
    def _add_chart_to_canvas(
        self,
        canvas_id: str,
        file_id: str,
        title: str,
        permalink: str = None
    ) -> bool:
        """Add the chart image to the canvas at the top."""
        import datetime
        
        try:
            if not permalink:
                permalink = f"https://slack.com/files/{file_id}"
            
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
            dashboard_url = f"{config.get_dashboard_url()}/"
            
            # Image embed - files are NOT deleted so references stay valid
            markdown_content = f"**📊 {title}** | [Dashboard]({dashboard_url}) | _{timestamp}_\n\n![Chart]({permalink})"
            
            response = self.client.api_call(
                api_method="canvases.edit",
                json={
                    "canvas_id": canvas_id,
                    "changes": [{
                        "operation": "insert_at_start",
                        "document_content": {
                            "type": "markdown",
                            "markdown": markdown_content
                        }
                    }]
                }
            )
            
            if response.get("ok"):
                logger.info(f"Canvas updated with chart image at top")
                return True
            else:
                logger.error(f"Canvas edit failed: {response.get('error')}")
                return False
                
        except SlackApiError as e:
            logger.error(f"Error adding chart to canvas: {e.response['error']}")
            return False
    
    def _get_canvas_info(self, canvas_id: str) -> dict:
        """Get information about a Canvas."""
        try:
            response = self.client.api_call(
                api_method="canvases.sections.lookup",
                json={"canvas_id": canvas_id}
            )
            return response
        except SlackApiError:
            return {}
    
    def _find_image_section(self, canvas_info: dict) -> Optional[str]:
        """Find an existing image section in the canvas."""
        sections = canvas_info.get("sections", [])
        for section in sections:
            if section.get("type") == "image":
                return section.get("id")
        return None
    
    def _update_canvas_section(
        self,
        canvas_id: str,
        section_id: str,
        file_id: str
    ) -> bool:
        """Update an existing Canvas section with a new image."""
        try:
            response = self.client.api_call(
                api_method="canvases.sections.update",
                json={
                    "canvas_id": canvas_id,
                    "section_id": section_id,
                    "content": {
                        "type": "image",
                        "file_id": file_id
                    }
                }
            )
            return response.get("ok", False)
        except SlackApiError as e:
            logger.error(f"Error updating section: {e.response['error']}")
            return False
    
    
    def _delete_old_file(self, file_id: str):
        """Delete an old file to clean up storage."""
        try:
            self.client.files_delete(file=file_id)
            logger.debug(f"Deleted old file: {file_id}")
        except SlackApiError:
            pass  # Non-critical, ignore errors
    
    def post_to_channel(
        self,
        image_data: bytes,
        channel_id: str,
        message: str = "Updated Gantt Chart",
        filename: str = "gantt_chart.png"
    ) -> bool:
        """
        Alternative: Post the chart directly to a channel.
        
        Use this if Canvas API is not available or as a simpler alternative.
        """
        try:
            response = self.client.files_upload_v2(
                content=image_data,
                filename=filename,
                title=message,
                channels=channel_id,
                initial_comment=message
            )
            return response.get("ok", False)
        except SlackApiError as e:
            logger.error(f"Error posting to channel: {e.response['error']}")
            return False


def create_canvas_service(bot_token: str) -> CanvasService:
    """Factory function to create a CanvasService instance."""
    client = WebClient(token=bot_token)
    return CanvasService(client)

