"""
Base Visual AI Endpoint

Abstract base class for AI endpoints that work with images and videos.
Provides common utilities for image encoding, video frame extraction,
and visual annotation tasks.
"""

import base64
import logging
import os
import tempfile
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Type, Union

from pydantic import BaseModel

from .ai_endpoint import BaseAIEndpoint, ImageData, VisualAnnotationInput, AIEndpointRequestError

logger = logging.getLogger(__name__)


class BaseVisualAIEndpoint(BaseAIEndpoint, ABC):
    """
    Abstract base class for visual AI endpoints.

    Extends BaseAIEndpoint with capabilities for processing images and videos.
    Subclasses should implement query_with_image() for provider-specific image handling.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize the visual AI endpoint.

        Args:
            config: Configuration dictionary containing endpoint-specific settings
        """
        super().__init__(config)

        # Visual-specific configuration
        self.max_image_size = self.ai_config.get("max_image_size", 4096)  # Max dimension in pixels
        self.default_video_fps = self.ai_config.get("default_video_fps", 1)  # Frames per second for sampling
        self.max_frames = self.ai_config.get("max_frames", 10)  # Max frames for video analysis

    @abstractmethod
    def query_with_image(
        self,
        prompt: str,
        image_data: Union[ImageData, List[ImageData]],
        output_format: Type[BaseModel]
    ) -> Any:
        """
        Send a query with image(s) to the AI model.

        Args:
            prompt: The text prompt describing what to analyze
            image_data: Single ImageData or list of ImageData for multiple frames
            output_format: Pydantic model for structured output

        Returns:
            The model's response parsed according to output_format

        Raises:
            AIEndpointRequestError: If the request fails
        """
        pass

    def get_visual_ai(
        self,
        data: VisualAnnotationInput,
        output_format: Type[BaseModel]
    ) -> Any:
        """
        Get AI assistance for visual annotation.

        This is the main entry point for visual annotation tasks.
        It builds the prompt from templates and calls query_with_image().

        Args:
            data: VisualAnnotationInput containing task details and image data
            output_format: Pydantic model for structured output

        Returns:
            AI response (detections, classifications, hints, etc.)
        """
        try:
            from .ai_prompt import get_ai_prompt
            from string import Template

            ai_prompt = get_ai_prompt()

            # Check if annotation type and ai_assistant exist in prompts
            if data.annotation_type not in ai_prompt:
                logger.warning(f"No prompts found for annotation type: {data.annotation_type}")
                return {"error": f"No prompts configured for {data.annotation_type}"}

            if data.ai_assistant not in ai_prompt[data.annotation_type]:
                logger.warning(f"No prompt found for ai_assistant: {data.ai_assistant}")
                return {"error": f"No prompt configured for {data.ai_assistant}"}

            prompt_config = ai_prompt[data.annotation_type][data.ai_assistant]
            template_str = prompt_config.get("prompt", "")

            # Build template variables
            template_vars = {
                "description": data.description,
                "labels": ", ".join(data.labels) if data.labels else "any objects",
                "task_type": data.task_type,
                "confidence_threshold": data.confidence_threshold,
            }

            # Add video-specific variables
            if data.video_metadata:
                template_vars.update({
                    "duration": data.video_metadata.get("duration", 0),
                    "fps": data.video_metadata.get("fps", 30),
                    "num_frames": len(data.image_data) if isinstance(data.image_data, list) else 1,
                })

            # Add region info for classification
            if data.region:
                template_vars["region"] = f"x={data.region.get('x', 0):.2f}, y={data.region.get('y', 0):.2f}, width={data.region.get('width', 1):.2f}, height={data.region.get('height', 1):.2f}"

            # Substitute template variables
            template = Template(template_str)
            prompt = template.safe_substitute(template_vars)

            logger.debug(f"Visual AI prompt: {prompt[:200]}...")

            return self.query_with_image(prompt, data.image_data, output_format)

        except Exception as e:
            logger.error(f"Error in get_visual_ai: {type(e).__name__}: {e}")
            import traceback
            logger.error(f"Traceback:\n{traceback.format_exc()}")
            return {"error": f"Failed to get visual AI assistance: {str(e)}"}

    @staticmethod
    def encode_image_to_base64(image_path: str) -> ImageData:
        """
        Read an image file and encode it as base64.

        Args:
            image_path: Path to the image file

        Returns:
            ImageData with base64-encoded image

        Raises:
            AIEndpointRequestError: If the file cannot be read
        """
        try:
            import mimetypes

            # Determine MIME type
            mime_type, _ = mimetypes.guess_type(image_path)
            if not mime_type:
                # Default to JPEG if unknown
                mime_type = "image/jpeg"

            with open(image_path, "rb") as f:
                image_bytes = f.read()

            encoded = base64.b64encode(image_bytes).decode("utf-8")

            # Try to get dimensions using PIL if available
            width, height = None, None
            try:
                from PIL import Image
                with Image.open(image_path) as img:
                    width, height = img.size
            except ImportError:
                logger.debug("PIL not available, skipping dimension extraction")
            except Exception as e:
                logger.debug(f"Could not extract dimensions: {e}")

            return ImageData(
                source="base64",
                data=encoded,
                width=width,
                height=height,
                mime_type=mime_type
            )

        except Exception as e:
            raise AIEndpointRequestError(f"Failed to encode image: {e}")

    @staticmethod
    def download_image_to_base64(url: str, timeout: int = 30) -> ImageData:
        """
        Download an image from URL and encode as base64.

        Args:
            url: URL of the image
            timeout: Request timeout in seconds

        Returns:
            ImageData with base64-encoded image

        Raises:
            AIEndpointRequestError: If the download fails
        """
        try:
            import requests

            response = requests.get(url, timeout=timeout)
            response.raise_for_status()

            # Get MIME type from content-type header
            content_type = response.headers.get("Content-Type", "image/jpeg")
            if ";" in content_type:
                content_type = content_type.split(";")[0].strip()

            encoded = base64.b64encode(response.content).decode("utf-8")

            # Try to get dimensions
            width, height = None, None
            try:
                from PIL import Image
                import io
                img = Image.open(io.BytesIO(response.content))
                width, height = img.size
                img.close()
            except ImportError:
                logger.debug("PIL not available, skipping dimension extraction")
            except Exception as e:
                logger.debug(f"Could not extract dimensions: {e}")

            return ImageData(
                source="base64",
                data=encoded,
                width=width,
                height=height,
                mime_type=content_type
            )

        except Exception as e:
            raise AIEndpointRequestError(f"Failed to download image from {url}: {e}")

    @staticmethod
    def create_url_image_data(url: str) -> ImageData:
        """
        Create an ImageData object for a URL without downloading.

        Some APIs accept image URLs directly. Use this when you don't
        need to download the image first.

        Args:
            url: URL of the image

        Returns:
            ImageData with URL reference
        """
        return ImageData(
            source="url",
            data=url,
            mime_type=None
        )

    def extract_video_frames(
        self,
        video_path_or_url: str,
        fps: Optional[float] = None,
        max_frames: Optional[int] = None,
        start_time: float = 0,
        end_time: Optional[float] = None
    ) -> List[ImageData]:
        """
        Extract frames from a video file or URL.

        Args:
            video_path_or_url: Path to video file or URL
            fps: Frames per second to sample (default: self.default_video_fps)
            max_frames: Maximum number of frames to extract (default: self.max_frames)
            start_time: Start time in seconds
            end_time: End time in seconds (None for entire video)

        Returns:
            List of ImageData objects containing base64-encoded frames

        Raises:
            AIEndpointRequestError: If video processing fails
        """
        try:
            import cv2
        except ImportError:
            raise AIEndpointRequestError(
                "OpenCV (cv2) is required for video frame extraction. "
                "Install it with: pip install opencv-python"
            )

        fps = fps or self.default_video_fps
        max_frames = max_frames or self.max_frames

        temp_file = None
        video_path = video_path_or_url

        try:
            # If URL, download to temp file
            if video_path_or_url.startswith(("http://", "https://")):
                import requests

                response = requests.get(video_path_or_url, stream=True, timeout=60)
                response.raise_for_status()

                # Create temp file with appropriate extension
                suffix = ".mp4"
                if "." in video_path_or_url.split("/")[-1]:
                    suffix = "." + video_path_or_url.split(".")[-1].split("?")[0]

                temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
                for chunk in response.iter_content(chunk_size=8192):
                    temp_file.write(chunk)
                temp_file.close()
                video_path = temp_file.name

            # Open video
            cap = cv2.VideoCapture(video_path)
            if not cap.isOpened():
                raise AIEndpointRequestError(f"Could not open video: {video_path_or_url}")

            # Get video properties
            video_fps = cap.get(cv2.CAP_PROP_FPS)
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            duration = total_frames / video_fps if video_fps > 0 else 0

            if end_time is None:
                end_time = duration

            # Calculate frame interval
            frame_interval = int(video_fps / fps) if fps < video_fps else 1
            start_frame = int(start_time * video_fps)
            end_frame = int(min(end_time, duration) * video_fps)

            frames: List[ImageData] = []
            current_frame = start_frame

            cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

            while current_frame < end_frame and len(frames) < max_frames:
                cap.set(cv2.CAP_PROP_POS_FRAMES, current_frame)
                ret, frame = cap.read()

                if not ret:
                    break

                # Encode frame as JPEG
                _, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                encoded = base64.b64encode(buffer).decode("utf-8")

                height, width = frame.shape[:2]

                frames.append(ImageData(
                    source="base64",
                    data=encoded,
                    width=width,
                    height=height,
                    mime_type="image/jpeg"
                ))

                current_frame += frame_interval

            cap.release()

            logger.info(f"Extracted {len(frames)} frames from video")
            return frames

        except AIEndpointRequestError:
            raise
        except Exception as e:
            raise AIEndpointRequestError(f"Failed to extract video frames: {e}")
        finally:
            # Clean up temp file
            if temp_file and os.path.exists(temp_file.name):
                try:
                    os.unlink(temp_file.name)
                except Exception:
                    pass

    def get_video_metadata(self, video_path_or_url: str) -> Dict[str, Any]:
        """
        Get metadata from a video file or URL.

        Args:
            video_path_or_url: Path to video file or URL

        Returns:
            Dictionary with fps, duration, width, height, total_frames

        Raises:
            AIEndpointRequestError: If metadata extraction fails
        """
        try:
            import cv2
        except ImportError:
            raise AIEndpointRequestError(
                "OpenCV (cv2) is required for video metadata extraction. "
                "Install it with: pip install opencv-python"
            )

        temp_file = None
        video_path = video_path_or_url

        try:
            # If URL, download to temp file
            if video_path_or_url.startswith(("http://", "https://")):
                import requests

                response = requests.get(video_path_or_url, stream=True, timeout=60)
                response.raise_for_status()

                suffix = ".mp4"
                if "." in video_path_or_url.split("/")[-1]:
                    suffix = "." + video_path_or_url.split(".")[-1].split("?")[0]

                temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
                for chunk in response.iter_content(chunk_size=8192):
                    temp_file.write(chunk)
                temp_file.close()
                video_path = temp_file.name

            cap = cv2.VideoCapture(video_path)
            if not cap.isOpened():
                raise AIEndpointRequestError(f"Could not open video: {video_path_or_url}")

            fps = cap.get(cv2.CAP_PROP_FPS)
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            duration = total_frames / fps if fps > 0 else 0

            cap.release()

            return {
                "fps": fps,
                "duration": duration,
                "width": width,
                "height": height,
                "total_frames": total_frames
            }

        except AIEndpointRequestError:
            raise
        except Exception as e:
            raise AIEndpointRequestError(f"Failed to get video metadata: {e}")
        finally:
            if temp_file and os.path.exists(temp_file.name):
                try:
                    os.unlink(temp_file.name)
                except Exception:
                    pass

    def resize_image(
        self,
        image_data: ImageData,
        max_dimension: Optional[int] = None
    ) -> ImageData:
        """
        Resize an image to fit within max dimensions.

        Args:
            image_data: ImageData to resize
            max_dimension: Maximum width/height (default: self.max_image_size)

        Returns:
            Resized ImageData (or original if already within limits)
        """
        try:
            from PIL import Image
            import io
        except ImportError:
            logger.warning("PIL not available, cannot resize image")
            return image_data

        max_dimension = max_dimension or self.max_image_size

        try:
            # Decode image
            if image_data.source == "base64":
                img_bytes = base64.b64decode(image_data.data)
            else:
                # URL - need to download first
                import requests
                response = requests.get(image_data.data, timeout=30)
                img_bytes = response.content

            img = Image.open(io.BytesIO(img_bytes))
            width, height = img.size

            # Check if resize needed
            if width <= max_dimension and height <= max_dimension:
                return image_data

            # Calculate new dimensions
            if width > height:
                new_width = max_dimension
                new_height = int(height * (max_dimension / width))
            else:
                new_height = max_dimension
                new_width = int(width * (max_dimension / height))

            # Resize
            img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)

            # Re-encode
            buffer = io.BytesIO()
            img_format = "JPEG" if image_data.mime_type in [None, "image/jpeg"] else "PNG"
            img.save(buffer, format=img_format, quality=85)
            encoded = base64.b64encode(buffer.getvalue()).decode("utf-8")

            return ImageData(
                source="base64",
                data=encoded,
                width=new_width,
                height=new_height,
                mime_type=f"image/{img_format.lower()}"
            )

        except Exception as e:
            logger.warning(f"Failed to resize image: {e}")
            return image_data
