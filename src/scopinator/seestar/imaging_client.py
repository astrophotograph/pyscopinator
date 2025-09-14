import asyncio
import collections
from typing import TypeVar, Literal, Optional
import threading
import time

import numpy as np
from jinja2.nodes import NodeType

from scopinator.seestar.commands.parameterized import IscopeStartView, IscopeStartViewParams, ScopeViewMode
from scopinator.util.logging_config import get_logger
logging = get_logger(__name__)
from pydantic import BaseModel

from scopinator.seestar.commands.imaging import (
    BeginStreaming,
    StopStreaming,
    GetStackedImage,
)
from scopinator.seestar.commands.simple import TestConnection
from scopinator.seestar.connection import SeestarConnection
from scopinator.seestar.events import (
    EventTypes,
    AnnotateResult,
    BaseEvent,
    InternalEvent, ModeType,
)
from scopinator.seestar.protocol_handlers import BinaryProtocol, ScopeImage
from scopinator.seestar.rtspclient import RtspClient
from scopinator.util.eventbus import EventBus

U = TypeVar("U")


class SeestarImagingStatus(BaseModel):
    """Seestar imaging status."""

    temp: float | None = None
    charger_status: Literal["Discharging", "Charging", "Full", "Not charging"] | None = None
    charge_online: bool | None = None
    battery_capacity: int | None = None
    stacked_frame: int = 0
    dropped_frame: int = 0
    skipped_frame: int = 0  # Frames skipped due to ongoing image reception
    target_name: str = ""
    annotate: AnnotateResult | None = None
    is_streaming: bool = False
    is_fetching_images: bool = False
    is_receiving_image: bool = False  # True while receiving image data
    is_sending_image: bool = False
    
    # Image retrieval timing
    last_image_start_time: float | None = None  # Timestamp when image started being received (milliseconds)
    last_image_end_time: float | None = None    # Timestamp when image was fully received (milliseconds)
    last_image_elapsed_ms: float | None = None  # Time taken to receive the image in milliseconds
    last_image_size_bytes: int | None = None    # Size of the last image in bytes
    avg_image_elapsed_ms: float | None = None   # Rolling average of image retrieval times

    def reset(self):
        self.temp = None
        self.charger_status = None
        self.charge_online = None
        self.battery_capacity = None
        self.stacked_frame = 0
        self.dropped_frame = 0
        self.skipped_frame = 0
        self.target_name = ""
        self.annotate = None
        self.is_streaming = False
        self.is_fetching_images = False
        self.is_receiving_image = False
        self.is_sending_image = False
        # Reset timing fields
        self.last_image_start_time = None
        self.last_image_end_time = None
        self.last_image_elapsed_ms = None
        self.last_image_size_bytes = None
        self.avg_image_elapsed_ms = None


class ParsedEvent(BaseModel):
    """Parsed event."""

    event: EventTypes


class SeestarImagingClient(BaseModel, arbitrary_types_allowed=True):
    """Seestar imaging client."""

    host: str
    port: int
    connection: SeestarConnection | None = None
    id: int = 100
    is_connected: bool = False
    status: SeestarImagingStatus = SeestarImagingStatus()
    background_task: asyncio.Task | None = None
    reader_task: asyncio.Task | None = None
    recent_events: collections.deque = collections.deque(maxlen=5)
    event_bus: EventBus | None = None
    binary_protocol: BinaryProtocol = BinaryProtocol()
    image: ScopeImage | None = None
    secondary_image: ScopeImage | None = None # There could be a secondary camera.  Currently only applies to Streaming mode.
    client_mode: Literal["ContinuousExposure", "Stack", "Streaming"] | None = None
    cached_raw_image: Optional[ScopeImage] = None
    cached_raw_image_lock: threading.Lock = threading.Lock()
    
    enhancement_settings_changed_event: Optional[asyncio.Event] = None

    # Timeout configuration
    connection_timeout: float = 10.0
    read_timeout: float = 30.0
    write_timeout: float = 10.0
    
    # Connection monitoring
    connection_monitor_task: asyncio.Task | None = None
    _last_successful_read: float = 0.0
    _connection_check_interval: float = 15.0
    _reconnect_in_progress: bool = False
    _image_timing_history: collections.deque = collections.deque(maxlen=20)  # Keep last 20 timings for average

    def __init__(
        self,
        host: str,
        port: int,
        event_bus: EventBus | None = None,
        connection_timeout: float = 10.0,
        read_timeout: float = 30.0,
        write_timeout: float = 10.0,
    ):
        # Create an EventBus if none provided
        if event_bus is None:
            from scopinator.util.eventbus import EventBus
            event_bus = EventBus()
            
        super().__init__(
            host=host,
            port=port,
            event_bus=event_bus,
            connection_timeout=connection_timeout,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
        )

        self.event_bus.add_listener("Stack", self._handle_stack_event)
        self.event_bus.add_listener("ClientModeChanged", self._handle_client_mode)
        
        # Initialize enhancement settings changed event
        self.enhancement_settings_changed_event = asyncio.Event()
        
        # Initialize cached image lock
        self.cached_raw_image_lock = threading.Lock()
        
        self.connection = SeestarConnection(
            host=host,
            port=port,
            connection_timeout=connection_timeout,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            should_reconnect_callback=self._should_attempt_reconnection,
        )

    async def _reader(self):
        """Background task that continuously reads messages and handles them."""
        logging.info(f"Starting reader task for {self}")
        while self.is_connected:
            try:
                # Start timing when we begin receiving header (in milliseconds)
                import time
                image_start_time = time.time() * 1000
                
                header = await self.connection.read_exactly(80)
                if header is None:
                    # Connection issue handled by connection layer, just continue
                    await asyncio.sleep(0.1)
                    continue

                # Update last successful read timestamp
                self._last_successful_read = time.time()
                
                size, id, width, height = self.binary_protocol.parse_header(header)
                logging.trace(
                    f"imaging receive header: {size=} {width=} {height=} {id=}"
                )

                data = None
                if size is not None:
                    # Check if this looks like image data (not a small control message)
                    if width and height and width > 0 and height > 0 and size and size > 1000:
                        # Mark that we're receiving an image
                        self.status.is_receiving_image = True
                        # Only update start time if we don't already have one
                        # (it may have been set when we sent the request)
                        if not self.status.last_image_start_time:
                            self.status.last_image_start_time = image_start_time
                        self.status.last_image_size_bytes = size
                    
                    data = await self.connection.read_exactly(size)
                    if data is None:
                        logging.info(f"Connection interrupted while reading image data from {self.host}:{self.port}")
                        # Connection was reset and reconnected, need to restart streaming
                        self.status.is_receiving_image = False
                        
                        # If we were streaming, try to restart it
                        if self.status.is_streaming:
                            logging.info(f"Restarting streaming after reconnection for {self.host}:{self.port}")
                            try:
                                # Send BeginStreaming command again
                                _ = await self.send(BeginStreaming(id=21))
                                logging.debug(f"Streaming restarted successfully for {self.host}:{self.port}")
                            except Exception as e:
                                logging.debug(f"Failed to restart streaming: {e}")
                        
                        await asyncio.sleep(0.5)  # Give it a moment to stabilize
                        continue

                # print(f"Data: {data is not None} Size: {size}")
                # We need to skip "images" that are small.  They are just text responses...
                if data is not None and size is not None and size > 1000:
                    # Process the incoming message
                    self.image = await self.binary_protocol.handle_incoming_message(
                        width, height, data, id
                    )
                    
                    # Clear receiving flag after processing
                    self.status.is_receiving_image = False
                    
                    # Only update timing statistics for actual image data
                    # Skip small control messages (like TestConnection responses)
                    # Actual images should have reasonable dimensions and data size
                    if width and height and width > 0 and height > 0 and size and size > 1000:
                        # Calculate timing for actual images (already in milliseconds)
                        image_end_time = time.time() * 1000
                        elapsed_ms = image_end_time - image_start_time
                        
                        # Ensure minimum of 0.1ms to avoid showing 0 for very fast operations
                        # (can happen with cached or local images)
                        if elapsed_ms < 0.1:
                            elapsed_ms = 0.1
                        
                        # Update status with timing information
                        self.status.last_image_end_time = image_end_time
                        self.status.last_image_elapsed_ms = elapsed_ms
                        # Clear the start time now that the image is complete
                        self.status.last_image_start_time = None
                        
                        # Update rolling average
                        self._image_timing_history.append(elapsed_ms)
                        if self._image_timing_history:
                            self.status.avg_image_elapsed_ms = sum(self._image_timing_history) / len(self._image_timing_history)
                        
                        logging.debug(f"Image received in {elapsed_ms:.1f}ms (avg: {self.status.avg_image_elapsed_ms:.1f}ms, size: {size} bytes)")

            except Exception as e:
                logging.info(
                    f"Imaging reader task error for {self.host}:{self.port}: {type(e).__name__}"
                )
                self.status.is_receiving_image = False
                if self.is_connected:
                    await asyncio.sleep(1.0)  # Brief pause before retrying
                    continue
                else:
                    break
        logging.info(f"Reader task stopped for {self}")

    async def _heartbeat(self):
        """Background task that sends periodic heartbeat messages."""
        await asyncio.sleep(5)
        while self.is_connected:
            try:
                if self.connection.is_connected() and not self._reconnect_in_progress:
                    logging.trace(f"Pinging {self}")
                    await self.send(TestConnection())
                await asyncio.sleep(5)
            except Exception as e:
                logging.trace(f"Heartbeat failed for {self}: {e}")
                await asyncio.sleep(5)
                continue

    async def connect(self):
        await self.connection.open()
        self.is_connected = True
        
        # Cancel any existing reader task before starting a new one
        # This prevents duplicate readers after reconnection
        if self.reader_task:
            logging.debug(f"Canceling existing reader task before reconnect for {self}")
            self.reader_task.cancel()
            try:
                await self.reader_task
            except asyncio.CancelledError:
                pass
            self.reader_task = None
        
        self.status.reset()

        self._last_successful_read = time.time()
        self.background_task = asyncio.create_task(self._heartbeat())
        self.reader_task = asyncio.create_task(self._reader())
        self.connection_monitor_task = asyncio.create_task(self._connection_monitor())

        logging.info(f"Connected to {self}")

    async def disconnect(self):
        """Disconnect from Seestar."""
        self.is_connected = False
        
        if self.status.is_streaming:
            await self.stop_streaming()
            
        # Cancel background tasks
        if self.background_task:
            self.background_task.cancel()
            try:
                await self.background_task
            except asyncio.CancelledError:
                pass
            self.background_task = None
            
        if self.reader_task:
            self.reader_task.cancel()
            try:
                await self.reader_task
            except asyncio.CancelledError:
                pass
            self.reader_task = None
            
        if self.connection_monitor_task:
            self.connection_monitor_task.cancel()
            try:
                await self.connection_monitor_task
            except asyncio.CancelledError:
                pass
            self.connection_monitor_task = None
            
        await self.connection.close()
        logging.info(f"Disconnected from {self}")

    async def send(self, data: str | BaseModel):
        if isinstance(data, BaseModel):
            if data.id is None:
                data.id = self.id
                self.id += 1
            data = data.model_dump_json()
        await self.connection.write(data)

    async def get_next_image(self, camera_id: int):
        last_image: ScopeImage = ScopeImage(width=1080, height=1920, image=None)

        self.status.is_fetching_images = True
        try:
            while self.is_connected:
                if self.client_mode == "Streaming":
                    # If we're streaming, just run RTSP client, which runs as a background thread...
                    rtsp_port = 4554 + camera_id
                    with RtspClient(
                        rtsp_server_uri=f"rtsp://{self.host}:{rtsp_port}/stream"
                    ) as rtsp_client:
                        # Run RTSP client until it's closed
                        await rtsp_client.finish_opening()
                        while rtsp_client.is_opened():
                            image = ScopeImage(
                                width=1080, height=1920, image=rtsp_client.read()
                            )

                            if image is not None and image.image is not None:
                                # Check if image has changed from the last one we sent
                                if last_image.image is not None:
                                    changed = not np.array_equal(
                                        image.image, last_image.image
                                    )
                                else:
                                    # First image, always consider it as changed
                                    changed = True
                                
                                if changed:
                                    last_image = image
                                    # I don't think we need to actually store the image if we're streaming?
                                    #if camera_id == 0:
                                    #    self.image = image  # Update current image
                                    #else:
                                    #    self.secondary_image = image
                                    self.status.is_sending_image = True
                                    yield image
                                    self.status.is_sending_image = False

                                    # Cache the raw image for plate solving (this doesn't apply to streaming modes!)
                                    #with self.cached_raw_image_lock:
                                    #    self.cached_raw_image = image

                            await asyncio.sleep(0)

                    await asyncio.sleep(0.5)
                    continue

                # Star mode only
                if self.image is not None and self.image.image is not None:
                    # Check if image has changed from the last one we sent
                    if last_image.image is not None:
                        changed = not np.array_equal(
                            self.image.image, last_image.image
                        )
                    else:
                        # First image, always consider it as changed
                        changed = True

                    if changed:
                        logging.trace(f"Image changed, yielding image for {self}")
                        last_image = self.image
                        # self.image = image  # Update current image
                        self.status.is_sending_image = True
                        yield self.image
                        self.status.is_sending_image = False

                        # Cache the raw image for plate solving
                        with self.cached_raw_image_lock:
                            self.cached_raw_image = self.image

                await asyncio.sleep(0.1)
        except Exception as e:
            logging.error(f"Unexpected error in imaging reader task for {self}: {e}")
            import traceback

            traceback.print_exc()

        self.status.is_sending_image = False
        self.status.is_fetching_images = False

    async def _handle_stack_event(self, event: BaseEvent):
        if event.state == "frame_complete" and self.status.is_fetching_images:
            # Check if we're currently receiving an image
            if self.status.is_receiving_image:
                # Skip this frame request since we're already receiving an image
                self.status.skipped_frame += 1
                logging.debug(f"Skipped frame request (already receiving image). Total skipped: {self.status.skipped_frame}")
            else:
                # Only grab the frame if we're streaming in client and not currently receiving
                logging.debug("Grabbing frame")
                # Update the start time when we request a new image
                import time
                self.status.last_image_start_time = time.time() * 1000
                # Note: Don't set is_receiving_image here, let the reader set it when data arrives
                try:
                    await self.send(GetStackedImage(id=23))
                except (ConnectionError, ConnectionResetError, BrokenPipeError, OSError) as e:
                    logging.warning(f"Connection lost while requesting stacked image: {e}")
                    # Connection will be handled by reconnection logic
        else:
            logging.debug(f"Got stack event; ignoring {event.state=} {self.status.is_fetching_images=}")

    async def _handle_client_mode(self, event: BaseEvent):
        if isinstance(event, InternalEvent):
            params = event.params
            existing = params.get("existing")
            new_mode = params.get("new_mode")

            if existing == "ContinuousExposure":
                try:
                    await self.stop_streaming()
                except (ConnectionError, ConnectionResetError, BrokenPipeError, OSError) as e:
                    logging.warning(f"Connection lost while stopping streaming: {e}")
                    self.status.is_streaming = False
            if existing == "Streaming":
                try:
                    await self.stop_rtsp()
                except (ConnectionError, ConnectionResetError, BrokenPipeError, OSError) as e:
                    logging.warning(f"Connection lost while stopping RTSP: {e}")
                    self.status.is_rtsp_streaming = False

            # If transitioning from Idle/None to an active mode, attempt reconnection if needed
            if existing in ["Idle", None] and new_mode not in ["Idle", None]:
                if not self.connection.is_connected():
                    logging.info(f"Client mode changing from {existing} to {new_mode}, attempting reconnection")
                    if not self._reconnect_in_progress:
                        self._reconnect_in_progress = True
                        try:
                            await self.connection.open()
                            logging.info(f"Successfully reconnected for mode change to {new_mode}")
                        except Exception as e:
                            logging.error(f"Failed to reconnect when changing to {new_mode}: {e}")
                        finally:
                            self._reconnect_in_progress = False

            match new_mode:
                case "ContinuousExposure":
                    try:
                        await self.start_streaming()
                    except (ConnectionError, ConnectionResetError, BrokenPipeError, OSError) as e:
                        logging.warning(f"Connection lost while starting streaming: {e}")
                        self.status.is_streaming = False
                case "Streaming":
                    try:
                        await self.start_rtsp()
                    except (ConnectionError, ConnectionResetError, BrokenPipeError, OSError) as e:
                        logging.warning(f"Connection lost while starting RTSP: {e}")
                        self.status.is_rtsp_streaming = False
                # For Stacking, AutoGoto and None we don't need to do anything

            self.client_mode = new_mode

    async def start_streaming(self):
        """Start streaming from the Seestar."""
        if self.status.is_streaming:
            logging.warning(f"Already streaming from {self}")
            return

        _ = await self.send(BeginStreaming(id=21))
        self.status.is_streaming = True
        # if response and response.result is not None:
        #     self.status.is_streaming = True
        #     logging.info(f"Started streaming from {self}")
        # else:
        #     logging.error(f"Failed to start streaming from {self}: {response}")

    async def stop_streaming(self):
        """Stop streaming from the Seestar."""
        if not self.status.is_streaming:
            logging.warning(f"Not streaming from {self}")
            return

        await self.send(StopStreaming())
        self.status.is_streaming = False

    async def start_rtsp(self):
        """Start RTSP streams from Seestar."""
        pass

    async def stop_rtsp(self):
        """Stop RTSP streams from Seestar."""
        pass

    def trigger_enhancement_settings_changed(self):
        """Trigger instant processing of cached image when enhancement settings change."""
        if self.enhancement_settings_changed_event is not None:
            self.enhancement_settings_changed_event.set()
            logging.info("Enhancement settings changed event triggered")
    
    def get_cached_raw_image(self) -> Optional[ScopeImage]:
        """Get the cached raw image."""
        with self.cached_raw_image_lock:
            return self.cached_raw_image

    async def _connection_monitor(self):
        """Background task that monitors connection health and manages reconnection."""
        logging.info(f"Starting connection monitor task for {self}")
        
        while self.is_connected:
            try:
                await asyncio.sleep(self._connection_check_interval)
                
                if not self.is_connected:
                    break
                    
                # Check if we should attempt reconnection
                if not self.connection.is_connected() and self._should_attempt_reconnection():
                    if not self._reconnect_in_progress:
                        self._reconnect_in_progress = True
                        logging.info(f"Connection monitor initiating reconnection for {self}")
                        try:
                            # Ensure clean state before reconnection
                            # Cancel the reader task if it's still running
                            if self.reader_task and not self.reader_task.done():
                                logging.debug(f"Canceling reader task before reconnection for {self}")
                                self.reader_task.cancel()
                                try:
                                    await self.reader_task
                                except asyncio.CancelledError:
                                    pass
                                self.reader_task = None
                            
                            # Reconnect and restart the reader task
                            await self.connection.open()
                            
                            # Restart the reader task after successful reconnection
                            self.reader_task = asyncio.create_task(self._reader())
                            logging.info(f"Connection monitor successfully reconnected {self} and restarted reader task")
                            
                            # If we were streaming, restart it
                            if self.status.is_streaming:
                                logging.debug(f"Restarting streaming after connection monitor reconnection")
                                try:
                                    await self.send(BeginStreaming(id=21))
                                    logging.debug(f"Streaming restarted by connection monitor")
                                except Exception as e:
                                    logging.debug(f"Connection monitor failed to restart streaming: {e}")
                        except Exception as e:
                            logging.debug(f"Connection monitor failed to reconnect {self.host}:{self.port}: {type(e).__name__}")
                        finally:
                            self._reconnect_in_progress = False
                            
            except Exception as e:
                logging.debug(f"Error in connection monitor task for {self.host}:{self.port}: {type(e).__name__}")
                await asyncio.sleep(5.0)  # Wait before retrying
                
        logging.debug(f"Connection monitor task stopped for {self}")
    
    def _should_attempt_reconnection(self) -> bool:
        """Check if reconnection should be attempted based on client_mode."""
        return self.client_mode not in ["Idle", None]

    async def __aenter__(self):
        """Async context manager entry - connects to the telescope."""
        await self.connect()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit - disconnects from the telescope."""
        await self.disconnect()
        # Don't suppress exceptions
        return False

    def __str__(self):
        return f"{self.host}:{self.port}"
