"""Hardware integration tests with cleaner connection handling for restart scenarios.

This version reduces log noise and handles connection state transitions more gracefully.

To run:
   RUN_HARDWARE_TESTS=true pytest tests/test_hardware_restart_clean.py -xvs --override-ini="addopts="
"""

import asyncio
import pytest
import pytest_asyncio
import time
import logging
from datetime import datetime
from typing import Any, Dict, Optional
import os
from contextlib import asynccontextmanager

from scopinator.seestar.client import SeestarClient, SeestarStatus
from scopinator.seestar.imaging_client import SeestarImagingClient
from scopinator.seestar.commands.simple import PiReboot, GetDeviceState
from scopinator.util.eventbus import EventBus


# Configuration
TELESCOPE_HOST = os.environ.get("TELESCOPE_HOST", "localhost")
TELESCOPE_PORT = int(os.environ.get("TELESCOPE_PORT", "4700"))
IMAGING_PORT = int(os.environ.get("IMAGING_PORT", "4800"))

# Mark as hardware test
pytestmark = [
    pytest.mark.hardware,
    pytest.mark.skipif(
        os.environ.get("RUN_HARDWARE_TESTS", "false").lower() != "true",
        reason="Hardware tests skipped (set RUN_HARDWARE_TESTS=true to run)"
    )
]


class ConnectionState:
    """Track connection state to reduce log noise."""
    CONNECTED = "connected"
    DISCONNECTING = "disconnecting"
    DISCONNECTED = "disconnected"
    RECONNECTING = "reconnecting"
    RESTART_PENDING = "restart_pending"


class CleanConnectionMonitor:
    """Enhanced connection monitor with cleaner output."""
    
    def __init__(self, client_name: str, quiet_until: float = 0):
        self.client_name = client_name
        self.state = ConnectionState.DISCONNECTED
        self.quiet_until = quiet_until  # Suppress logs until this time
        self.reconnect_attempts = 0
        self.last_attempt_time = 0
        self.backoff_seconds = 2.0
        self.max_backoff = 30.0
        self.states_log = []
        self.start_time = time.time()
        
    def set_quiet_period(self, seconds: float):
        """Set a quiet period to suppress non-critical logs."""
        self.quiet_until = time.time() + seconds
        
    def is_quiet(self) -> bool:
        """Check if we're in quiet period."""
        return time.time() < self.quiet_until
        
    def log_state_change(self, new_state: str, details: str = ""):
        """Log a state change with timestamp."""
        elapsed = time.time() - self.start_time
        timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
        
        self.state = new_state
        self.states_log.append((elapsed, new_state, details))
        
        # Only print important state changes or if not in quiet period
        if not self.is_quiet() or new_state in [ConnectionState.CONNECTED, ConnectionState.RESTART_PENDING]:
            symbol = {
                ConnectionState.CONNECTED: "✅",
                ConnectionState.DISCONNECTING: "🔻",
                ConnectionState.DISCONNECTED: "❌",
                ConnectionState.RECONNECTING: "🔄",
                ConnectionState.RESTART_PENDING: "⚠️"
            }.get(new_state, "•")
            
            print(f"[{timestamp}] [{elapsed:6.2f}s] {symbol} {self.client_name}: {new_state} {details}")
    
    def should_reconnect(self) -> bool:
        """Determine if we should attempt reconnection with backoff."""
        if self.state != ConnectionState.DISCONNECTED:
            return False
            
        current_time = time.time()
        time_since_last = current_time - self.last_attempt_time
        
        # Use exponential backoff
        current_backoff = min(self.backoff_seconds * (2 ** self.reconnect_attempts), self.max_backoff)
        
        if time_since_last >= current_backoff:
            self.last_attempt_time = current_time
            self.reconnect_attempts += 1
            return True
        return False
    
    def reset_reconnect_counters(self):
        """Reset reconnection counters after successful connection."""
        self.reconnect_attempts = 0
        self.last_attempt_time = 0


@asynccontextmanager
async def managed_logging(level=logging.WARNING):
    """Context manager to temporarily adjust logging levels."""
    # Get relevant loggers
    loggers = [
        logging.getLogger('scopinator.seestar.connection'),
        logging.getLogger('scopinator.seestar.client'),
        logging.getLogger('scopinator.seestar.imaging_client'),
        logging.getLogger('scopinator.seestar.rtspclient'),
    ]
    
    # Store original levels
    original_levels = {logger: logger.level for logger in loggers}
    
    # Set new level
    for logger in loggers:
        logger.setLevel(level)
    
    try:
        yield
    finally:
        # Restore original levels
        for logger, level in original_levels.items():
            logger.setLevel(level)


class TestCleanRestart:
    """Cleaner restart test with improved connection handling."""
    
    @pytest_asyncio.fixture
    async def clients_with_monitors(self):
        """Create clients with clean connection monitors."""
        event_bus = EventBus()
        
        # Create clients
        client = SeestarClient(
            host=TELESCOPE_HOST,
            port=TELESCOPE_PORT,
            event_bus=event_bus,
            connection_timeout=5.0,
            read_timeout=10.0,
        )
        
        imaging_client = SeestarImagingClient(
            host=TELESCOPE_HOST,
            port=IMAGING_PORT,
            event_bus=event_bus,
            connection_timeout=5.0,
            read_timeout=10.0,
        )
        
        # Create monitors
        client_monitor = CleanConnectionMonitor("Client")
        imaging_monitor = CleanConnectionMonitor("ImagingClient")
        
        yield client, imaging_client, client_monitor, imaging_monitor
        
        # Cleanup with error suppression
        for c in [client, imaging_client]:
            try:
                if c and c.is_connected:
                    await c.disconnect()
            except Exception:
                pass
    
    @pytest.mark.asyncio
    async def test_clean_restart_monitoring(self, clients_with_monitors):
        """Test restart with cleaner connection monitoring."""
        client, imaging_client, client_monitor, imaging_monitor = clients_with_monitors
        
        print("\n" + "="*80)
        print("CLEAN RESTART TEST WITH IMPROVED CONNECTION HANDLING")
        print("="*80)
        print(f"Target: {TELESCOPE_HOST}:{TELESCOPE_PORT} / {IMAGING_PORT}")
        print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("-"*80)
        
        # Use higher log level to reduce noise
        async with managed_logging(logging.ERROR):
            try:
                # Phase 1: Connect
                print("\n[Phase 1: Initial Connection]")
                await client.connect()
                await imaging_client.connect()
                
                client_monitor.log_state_change(ConnectionState.CONNECTED, f"port {TELESCOPE_PORT}")
                imaging_monitor.log_state_change(ConnectionState.CONNECTED, f"port {IMAGING_PORT}")
                
                # Phase 2: Verify streaming
                print("\n[Phase 2: Verify Streaming]")
                print("  Waiting 3 seconds for streaming to stabilize...")
                await asyncio.sleep(3)
                
                await imaging_client.start_streaming()
                frame_count = 0
                
                print("  Capturing test frames:")
                async for image in imaging_client.get_next_image(camera_id=0):
                    if image and image.image is not None:
                        frame_count += 1
                        print(f"    Frame {frame_count}: {image.image.shape}")
                        if frame_count >= 3:
                            break
                
                # Phase 3: Send restart
                print("\n[Phase 3: Sending Restart Command]")
                print("  ⚡ Sending PiReboot command...")
                
                # Set quiet period for expected disconnection
                expected_downtime = 35  # seconds
                client_monitor.set_quiet_period(expected_downtime)
                imaging_monitor.set_quiet_period(expected_downtime)
                
                client_monitor.log_state_change(ConnectionState.RESTART_PENDING, 
                                               f"expecting ~{expected_downtime}s downtime")
                imaging_monitor.log_state_change(ConnectionState.RESTART_PENDING,
                                               f"expecting ~{expected_downtime}s downtime")
                
                restart_cmd = PiReboot()
                try:
                    response = await asyncio.wait_for(
                        client.send_and_recv(restart_cmd), 
                        timeout=2.0
                    )
                    if response and response.result:
                        print("  ✅ Restart command acknowledged")
                except asyncio.TimeoutError:
                    print("  ⏱️ Restart command sent (no response expected)")
                
                # Phase 4: Monitor recovery
                print(f"\n[Phase 4: Monitoring Recovery for 60 seconds]")
                print(f"  Note: Suppressing connection logs for {expected_downtime}s")
                print("-"*80)
                
                monitoring_start = time.time()
                monitoring_duration = 60.0
                check_interval = 1.0
                
                # Track key metrics
                disconnection_time = None
                reconnection_time = None
                last_client_state = True
                last_imaging_state = True
                
                while (time.time() - monitoring_start) < monitoring_duration:
                    elapsed = time.time() - monitoring_start
                    
                    # Check connection states
                    client_connected = client.is_connected
                    imaging_connected = imaging_client.is_connected
                    
                    # Detect disconnection
                    if last_client_state and not client_connected:
                        disconnection_time = elapsed
                        client_monitor.log_state_change(ConnectionState.DISCONNECTED, 
                                                       "restart in progress")
                    
                    if last_imaging_state and not imaging_connected:
                        imaging_monitor.log_state_change(ConnectionState.DISCONNECTED,
                                                        "restart in progress")
                    
                    # Try reconnection with backoff
                    if not client_connected and client_monitor.should_reconnect():
                        try:
                            client_monitor.log_state_change(ConnectionState.RECONNECTING,
                                                          f"attempt #{client_monitor.reconnect_attempts}")
                            await asyncio.wait_for(client.connect(), timeout=2.0)
                            if client.is_connected:
                                reconnection_time = elapsed
                                client_monitor.reset_reconnect_counters()
                                client_monitor.log_state_change(ConnectionState.CONNECTED,
                                                              f"recovered after {elapsed:.1f}s")
                        except Exception:
                            pass  # Will retry with backoff
                    
                    if not imaging_connected and imaging_monitor.should_reconnect():
                        try:
                            imaging_monitor.log_state_change(ConnectionState.RECONNECTING,
                                                           f"attempt #{imaging_monitor.reconnect_attempts}")
                            await asyncio.wait_for(imaging_client.connect(), timeout=2.0)
                            if imaging_client.is_connected:
                                imaging_monitor.reset_reconnect_counters()
                                imaging_monitor.log_state_change(ConnectionState.CONNECTED,
                                                               f"recovered after {elapsed:.1f}s")
                        except Exception:
                            pass
                    
                    last_client_state = client_connected
                    last_imaging_state = imaging_connected
                    
                    # Show progress indicator every 10 seconds
                    if int(elapsed) % 10 == 0 and elapsed > 0:
                        status = "🟢" if (client_connected and imaging_connected) else "🔴"
                        print(f"  [{elapsed:3.0f}s] Status: {status} Client: {client_connected}, Imaging: {imaging_connected}")
                    
                    await asyncio.sleep(check_interval)
                
                # Phase 5: Summary
                print("\n" + "="*80)
                print("RESTART TEST SUMMARY")
                print("="*80)
                
                if disconnection_time:
                    print(f"  Disconnection detected at: {disconnection_time:.1f}s")
                if reconnection_time:
                    print(f"  Reconnection completed at: {reconnection_time:.1f}s")
                    print(f"  Total downtime: {reconnection_time - disconnection_time:.1f}s")
                
                print(f"\n  Final Status:")
                print(f"    Client: {'Connected ✅' if client.is_connected else 'Disconnected ❌'}")
                print(f"    Imaging: {'Connected ✅' if imaging_client.is_connected else 'Disconnected ❌'}")
                
                print(f"\n  Connection State Changes:")
                for monitor in [client_monitor, imaging_monitor]:
                    print(f"\n  {monitor.client_name}:")
                    for elapsed, state, details in monitor.states_log:
                        print(f"    [{elapsed:6.2f}s] {state} {details}")
                
                # Verify recovery
                if client.is_connected and imaging_client.is_connected:
                    print("\n✅ SUCCESS: Both clients recovered successfully")
                    
                    # Test functionality
                    try:
                        device_state = await asyncio.wait_for(
                            client.send_and_recv(GetDeviceState()),
                            timeout=5.0
                        )
                        if device_state and device_state.result:
                            print(f"   Verified device is responsive")
                    except Exception as e:
                        print(f"   Warning: Could not verify device state: {e}")
                else:
                    print("\n⚠️  WARNING: Not all clients recovered")
                
            except Exception as e:
                print(f"\n❌ Test failed with error: {e}")
                raise
        
        print("\n" + "="*80)
        print("TEST COMPLETED")
        print("="*80)


if __name__ == "__main__":
    pytest.main([__file__, "-xvs", "--override-ini=addopts="])