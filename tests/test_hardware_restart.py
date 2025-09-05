"""Hardware integration tests for restart scenarios and connection monitoring.

These tests require a real Seestar telescope to be connected and accessible.
They test the client's ability to handle device restarts and maintain connection state.

To run these tests:
1. Connect a Seestar telescope to your network
2. Set the TELESCOPE_HOST environment variable (default: localhost)
3. Run: RUN_HARDWARE_TESTS=true pytest tests/test_hardware_restart.py -v -s

For continuous monitoring output:
   RUN_HARDWARE_TESTS=true pytest tests/test_hardware_restart.py::TestRestartScenarios::test_restart_with_monitoring -xvs

Warning: These tests will restart your telescope!
"""

import asyncio
import pytest
import pytest_asyncio
import json
import time
from datetime import datetime
from typing import Any, Dict, Optional
import os

from scopinator.seestar.client import SeestarClient, SeestarStatus
from scopinator.seestar.imaging_client import SeestarImagingClient
from scopinator.seestar.commands.simple import PiReboot, GetDeviceState
from scopinator.seestar.commands.imaging import BeginStreaming, StopStreaming
from scopinator.util.eventbus import EventBus


# Configuration from environment variables
TELESCOPE_HOST = os.environ.get("TELESCOPE_HOST", "localhost")
TELESCOPE_PORT = int(os.environ.get("TELESCOPE_PORT", "4700"))
IMAGING_PORT = int(os.environ.get("IMAGING_PORT", "4800"))

# Mark all tests as hardware tests that require explicit opt-in
pytestmark = [
    pytest.mark.hardware,
    pytest.mark.skipif(
        os.environ.get("RUN_HARDWARE_TESTS", "false").lower() != "true",
        reason="Hardware tests skipped (set RUN_HARDWARE_TESTS=true to run)"
    )
]


class ConnectionMonitor:
    """Monitor and track connection state changes."""
    
    def __init__(self, client_name: str):
        self.client_name = client_name
        self.states: list[tuple[float, str, Any]] = []
        self.last_state: Dict[str, Any] = {}
        
    def record_state(self, timestamp: float, key: str, value: Any) -> bool:
        """Record a state change. Returns True if the value changed."""
        if key not in self.last_state or self.last_state[key] != value:
            self.states.append((timestamp, key, value))
            self.last_state[key] = value
            return True
        return False
    
    def print_change(self, timestamp: float, key: str, value: Any):
        """Print a state change."""
        elapsed = timestamp
        dt = datetime.fromtimestamp(timestamp)
        print(f"[{dt.strftime('%H:%M:%S.%f')[:-3]}] [{elapsed:6.2f}s] {self.client_name}.{key}: {value}")


class TestRestartScenarios:
    """Test scenarios involving device restart and recovery."""
    
    @pytest_asyncio.fixture
    async def clients(self):
        """Create both regular and imaging clients."""
        event_bus = EventBus()
        
        # Create regular client
        client = SeestarClient(
            host=TELESCOPE_HOST,
            port=TELESCOPE_PORT,
            event_bus=event_bus,
            connection_timeout=5.0,
            read_timeout=10.0,
        )
        
        # Create imaging client
        imaging_client = SeestarImagingClient(
            host=TELESCOPE_HOST,
            port=IMAGING_PORT,
            event_bus=event_bus,
            connection_timeout=5.0,
            read_timeout=10.0,
        )
        
        yield client, imaging_client
        
        # Cleanup - handle disconnected clients gracefully
        try:
            if client and client.is_connected:
                await client.disconnect()
        except Exception as e:
            pass  # Already disconnected or error during disconnect
        
        try:
            if imaging_client and imaging_client.is_connected:
                await imaging_client.disconnect()
        except Exception as e:
            pass  # Already disconnected or error during disconnect
    
    @pytest.mark.asyncio
    async def test_restart_with_monitoring(self, clients):
        """Connect, start streaming, restart device, and monitor recovery.
        
        This test:
        1. Connects both clients
        2. Starts streaming
        3. Sends restart command
        4. Monitors connection status for 60 seconds
        5. Tracks all state changes
        """
        client, imaging_client = clients
        
        # Create monitors for both clients
        client_monitor = ConnectionMonitor("Client")
        imaging_monitor = ConnectionMonitor("ImagingClient")
        
        print("\n" + "="*80)
        print("RESTART SCENARIO TEST WITH CONNECTION MONITORING")
        print("="*80)
        print(f"Target: {TELESCOPE_HOST}:{TELESCOPE_PORT} (regular) / {IMAGING_PORT} (imaging)")
        print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("-"*80)
        
        start_time = time.time()
        
        try:
            # Phase 1: Initial connection
            print("\n[Phase 1: Initial Connection]")
            await client.connect()
            await imaging_client.connect()
            
            # Record initial states
            current_time = time.time() - start_time
            client_monitor.record_state(current_time, "is_connected", client.is_connected)
            client_monitor.record_state(current_time, "status", str(client.status))
            imaging_monitor.record_state(current_time, "is_connected", imaging_client.is_connected)
            imaging_monitor.record_state(current_time, "client_mode", imaging_client.client_mode)
            
            print(f"✅ Both clients connected")
            print(f"   Client mode: {imaging_client.client_mode}")
            
            # Phase 2: Start streaming
            print("\n[Phase 2: Start Streaming]")
            await imaging_client.start_streaming()
            await asyncio.sleep(2)  # Let streaming stabilize
            
            current_time = time.time() - start_time
            imaging_monitor.record_state(current_time, "streaming", True)
            print(f"✅ Streaming started")
            
            # Capture a few frames to verify streaming works
            print("\n[Phase 3: Verify Streaming]")
            print("   Waiting 5 seconds for streaming to stabilize...")
            await asyncio.sleep(5)  # Wait longer for streaming to stabilize
            
            frame_count = 0
            async for image in imaging_client.get_next_image(camera_id=0):
                if image and image.image is not None:
                    frame_count += 1
                    print(f"   Frame {frame_count}: {image.image.shape}")
                    if frame_count >= 5:  # Capture more frames to verify stability
                        break
            
            # Phase 4: Send restart command
            print("\n[Phase 4: Sending Restart Command]")
            print("⚠️  RESTARTING TELESCOPE - This will take approximately 30-40 seconds")
            
            restart_cmd = PiReboot()
            try:
                response = await asyncio.wait_for(client.send_and_recv(restart_cmd), timeout=5.0)
                if response and response.result:
                    print(f"✅ Restart command accepted")
                else:
                    print(f"⚠️  Restart command sent but no confirmation received")
            except asyncio.TimeoutError:
                print(f"⚠️  Restart command sent but timed out waiting for response")
            
            # Phase 5: Monitor for 60 seconds
            print("\n[Phase 5: Monitoring Connection Status for 60 seconds]")
            print("-"*80)
            print("Format: [Time] [Elapsed] Client.property: value")
            print("-"*80)
            
            monitoring_start = time.time()
            monitoring_duration = 60.0
            check_interval = 0.5  # Check every 500ms
            
            while (time.time() - monitoring_start) < monitoring_duration:
                current_time = time.time() - start_time
                
                try:
                    # Check client connection status
                    if client_monitor.record_state(current_time, "is_connected", client.is_connected):
                        client_monitor.print_change(current_time, "is_connected", client.is_connected)
                    
                    # Check client status fields (safely access attributes)
                    if client.status:
                        status_dict = {}
                        
                        # Safely get device_state if it exists
                        if hasattr(client.status, 'device_state'):
                            status_dict["device_state"] = client.status.device_state
                        
                        # Safely get battery and temperature
                        if hasattr(client.status, 'battery_capacity'):
                            status_dict["battery_capacity"] = client.status.battery_capacity
                        if hasattr(client.status, 'temp'):
                            status_dict["temperature"] = client.status.temp
                        
                        # Get pi_status dict if available
                        if hasattr(client.status, 'pi_status') and isinstance(client.status.pi_status, dict):
                            pi_battery = client.status.pi_status.get("battery_capacity")
                            pi_temp = client.status.pi_status.get("temp")
                            if pi_battery is not None:
                                status_dict["pi_battery"] = pi_battery
                            if pi_temp is not None:
                                status_dict["pi_temp"] = pi_temp
                        
                        for key, value in status_dict.items():
                            if client_monitor.record_state(current_time, key, value):
                                client_monitor.print_change(current_time, key, value)
                    
                    # Check imaging client connection
                    if imaging_monitor.record_state(current_time, "is_connected", imaging_client.is_connected):
                        imaging_monitor.print_change(current_time, "is_connected", imaging_client.is_connected)
                    
                    # Check imaging client mode
                    if imaging_monitor.record_state(current_time, "client_mode", imaging_client.client_mode):
                        imaging_monitor.print_change(current_time, "client_mode", imaging_client.client_mode)
                    
                    # Check imaging client status
                    if imaging_client.status:
                        img_status_dict = {
                            "stacked_frame": imaging_client.status.stacked_frame,
                            "dropped_frame": imaging_client.status.dropped_frame,
                            "skipped_frame": imaging_client.status.skipped_frame,
                        }
                        
                        for key, value in img_status_dict.items():
                            if imaging_monitor.record_state(current_time, key, value):
                                imaging_monitor.print_change(current_time, key, value)
                    
                    # Try to reconnect if disconnected
                    if not client.is_connected and current_time > 10:  # Wait 10s before trying
                        try:
                            await asyncio.wait_for(client.connect(), timeout=1.0)
                            if client.is_connected:
                                client_monitor.record_state(current_time, "reconnected", True)
                                client_monitor.print_change(current_time, "reconnected", True)
                        except (asyncio.TimeoutError, Exception):
                            pass  # Silently continue
                    
                    if not imaging_client.is_connected and current_time > 10:
                        try:
                            await asyncio.wait_for(imaging_client.connect(), timeout=1.0)
                            if imaging_client.is_connected:
                                imaging_monitor.record_state(current_time, "reconnected", True)
                                imaging_monitor.print_change(current_time, "reconnected", True)
                        except (asyncio.TimeoutError, Exception):
                            pass
                
                except ConnectionResetError as e:
                    # Expected when telescope restarts
                    if "connection reset" not in str(client_monitor.last_state.get("connection_reset", "")).lower():
                        client_monitor.record_state(current_time, "connection_reset", True)
                        client_monitor.print_change(current_time, "connection_reset", "Connection reset by peer (expected during restart)")
                except Exception as e:
                    # Log unexpected errors but continue monitoring
                    if "unexpected_error" not in client_monitor.last_state:
                        client_monitor.record_state(current_time, "unexpected_error", str(e))
                        client_monitor.print_change(current_time, "unexpected_error", f"Error: {e}")
                
                await asyncio.sleep(check_interval)
            
            # Phase 6: Summary
            print("\n" + "="*80)
            print("MONITORING SUMMARY")
            print("="*80)
            
            print(f"\n[Client State Changes: {len(client_monitor.states)}]")
            for timestamp, key, value in client_monitor.states:
                dt = datetime.fromtimestamp(start_time + timestamp)
                print(f"  {dt.strftime('%H:%M:%S.%f')[:-3]} [{timestamp:6.2f}s] {key}: {value}")
            
            print(f"\n[Imaging Client State Changes: {len(imaging_monitor.states)}]")
            for timestamp, key, value in imaging_monitor.states:
                dt = datetime.fromtimestamp(start_time + timestamp)
                print(f"  {dt.strftime('%H:%M:%S.%f')[:-3]} [{timestamp:6.2f}s] {key}: {value}")
            
            # Final connection check
            print(f"\n[Final State After {monitoring_duration}s]")
            print(f"  Client connected: {client.is_connected}")
            print(f"  Imaging client connected: {imaging_client.is_connected}")
            
            # Verify recovery
            if client.is_connected and imaging_client.is_connected:
                print("\n✅ SUCCESS: Both clients recovered after restart")
                
                # Try to get device state to verify full recovery
                try:
                    device_state = await asyncio.wait_for(client.send_and_recv(GetDeviceState()), timeout=5.0)
                    if device_state and device_state.result:
                        print(f"   Device state confirmed: {device_state.result}")
                except asyncio.TimeoutError:
                    print(f"   Unable to get device state (timeout)")
            else:
                print("\n⚠️  WARNING: Not all clients recovered")
                if not client.is_connected:
                    print("   - Regular client still disconnected")
                if not imaging_client.is_connected:
                    print("   - Imaging client still disconnected")
            
        except Exception as e:
            print(f"\n❌ Test failed with error: {e}")
            raise
        
        print("\n" + "="*80)
        print("TEST COMPLETED")
        print("="*80)


class TestDisconnectScenarios:
    """Test scenarios for handling disconnections."""
    
    @pytest_asyncio.fixture
    async def client(self):
        """Create a client with monitoring capabilities."""
        event_bus = EventBus()
        client = SeestarClient(
            host=TELESCOPE_HOST,
            port=TELESCOPE_PORT,
            event_bus=event_bus,
            connection_timeout=5.0,
            read_timeout=10.0,
        )
        yield client
        # Cleanup - handle disconnected clients gracefully
        try:
            if client and client.is_connected:
                await client.disconnect()
        except Exception:
            pass  # Already disconnected or error during disconnect
    
    @pytest.mark.asyncio
    async def test_disconnect_during_command_series(self, client):
        """Test behavior when telescope disconnects during a series of commands."""
        print("\n" + "="*80)
        print("DISCONNECT DURING COMMAND SERIES TEST")
        print("="*80)
        
        monitor = ConnectionMonitor("Client")
        start_time = time.time()
        
        try:
            # Connect
            await client.connect()
            assert client.is_connected
            print("✅ Connected to telescope")
            
            # Send a series of commands
            print("\n[Sending Command Series]")
            commands_sent = 0
            commands_failed = 0
            
            for i in range(20):
                # Skip sending commands if disconnected (after restart)
                if not client.is_connected and i > 6:
                    print(f"  Command {i+1}: SKIPPED (disconnected)")
                    await asyncio.sleep(2.0)
                    
                    # Check if reconnected
                    current_time = time.time() - start_time
                    if monitor.record_state(current_time, "is_connected", client.is_connected):
                        monitor.print_change(current_time, "is_connected", client.is_connected)
                    continue
                    
                try:
                    # Send GetDeviceState command with timeout
                    response = await asyncio.wait_for(client.send_and_recv(GetDeviceState()), timeout=2.0)
                    if response and response.result:
                        commands_sent += 1
                        print(f"  Command {i+1}: SUCCESS")
                    else:
                        commands_failed += 1
                        print(f"  Command {i+1}: NO RESPONSE")
                    
                    # Monitor connection state
                    current_time = time.time() - start_time
                    if monitor.record_state(current_time, "is_connected", client.is_connected):
                        monitor.print_change(current_time, "is_connected", client.is_connected)
                    
                    # After command 5, restart to force disconnect
                    if i == 5:
                        print("\n⚠️  Sending restart to force disconnect...")
                        restart_cmd = PiReboot()
                        try:
                            await asyncio.wait_for(client.send_and_recv(restart_cmd), timeout=2.0)
                        except asyncio.TimeoutError:
                            pass  # Expected - device is restarting
                        print("   Restart command sent\n")
                    
                    await asyncio.sleep(2.0)  # Wait between commands
                    
                except Exception as e:
                    commands_failed += 1
                    print(f"  Command {i+1}: ERROR - {e}")
                    
                    current_time = time.time() - start_time
                    if monitor.record_state(current_time, "is_connected", client.is_connected):
                        monitor.print_change(current_time, "is_connected", client.is_connected)
            
            # Summary
            print(f"\n[Command Summary]")
            print(f"  Commands sent: {commands_sent}")
            print(f"  Commands failed: {commands_failed}")
            print(f"  Success rate: {(commands_sent/(commands_sent+commands_failed))*100:.1f}%")
            
        except Exception as e:
            print(f"\n❌ Test failed: {e}")
            raise


if __name__ == "__main__":
    # Allow running directly with python
    import sys
    pytest.main([__file__, "-xvs"] + sys.argv[1:])