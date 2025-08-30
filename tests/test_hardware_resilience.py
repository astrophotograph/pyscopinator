"""Hardware integration tests for resilience and error recovery.

These tests simulate various network and connection issues to ensure
the telescope client handles them gracefully.

To run these tests:
1. Ensure telescope/mock is running on localhost:4700
2. Run: RUN_HARDWARE_TESTS=true pytest tests/test_hardware_resilience.py -v
"""

import asyncio
import pytest
import pytest_asyncio
import socket
import threading
import time
from datetime import datetime
import os
from unittest.mock import patch, AsyncMock, MagicMock

from scopinator.seestar.client import SeestarClient, SeestarStatus
from scopinator.seestar.connection import SeestarConnection
from scopinator.seestar.commands.simple import (
    GetTime,
    GetDeviceState,
    GetViewState,
    GetFocuserPosition,
    ScopeGetEquCoord,
    TestConnection,
)
from scopinator.seestar.commands.common import CommandResponse
from scopinator.util.eventbus import EventBus


# Configuration
TELESCOPE_HOST = os.environ.get("TELESCOPE_HOST", "localhost")
TELESCOPE_PORT = int(os.environ.get("TELESCOPE_PORT", "4700"))

# Mark all tests as hardware tests
pytestmark = [
    pytest.mark.hardware,
    pytest.mark.skipif(
        os.environ.get("RUN_HARDWARE_TESTS", "false").lower() != "true",
        reason="Hardware tests skipped (set RUN_HARDWARE_TESTS=true to run)"
    )
]


class TestDisconnectScenarios:
    """Test disconnect and reconnect scenarios during operations."""
    
    @pytest_asyncio.fixture
    async def client(self):
        """Create a client for testing."""
        event_bus = EventBus()
        client = SeestarClient(
            host=TELESCOPE_HOST,
            port=TELESCOPE_PORT,
            event_bus=event_bus,
            connection_timeout=2.0,
            read_timeout=5.0,
        )
        yield client
        # Cleanup
        if client.is_connected:
            try:
                await client.disconnect()
            except:
                pass
    
    @pytest.mark.asyncio
    async def test_disconnect_during_command_series(self, client):
        """Test handling disconnect while running a series of commands."""
        try:
            # Connect initially
            await client.connect()
            assert client.is_connected
            
            # Track successful commands
            successful_commands = 0
            failed_commands = 0
            
            # Create a list of commands to execute
            commands = [
                GetTime(),
                GetDeviceState(),
                GetViewState(),
                GetFocuserPosition(),
                ScopeGetEquCoord(),
                GetTime(),  # Repeat some
                GetDeviceState(),
                TestConnection(),
            ]
            
            # Execute commands and simulate disconnect midway
            for i, cmd in enumerate(commands):
                try:
                    # Simulate disconnect after 3 commands
                    if i == 3:
                        # Force close the connection
                        if client.connection and client.connection.writer:
                            client.connection.writer.close()
                            await asyncio.sleep(0.1)
                    
                    # Try to send command
                    response = await asyncio.wait_for(
                        client.send_and_recv(cmd),
                        timeout=2.0
                    )
                    
                    if response is not None:
                        successful_commands += 1
                    else:
                        failed_commands += 1
                        
                except asyncio.TimeoutError:
                    failed_commands += 1
                except Exception as e:
                    failed_commands += 1
                    # Connection might be recovering
                    await asyncio.sleep(0.5)
            
            # We should have some successful and some failed commands
            assert successful_commands > 0, "Should have some successful commands before disconnect"
            assert failed_commands > 0, "Should have some failed commands after disconnect"
            
            # Connection should attempt to recover
            await asyncio.sleep(3.0)  # Give time for reconnection
            
            # Try one more command to see if it recovered
            try:
                response = await asyncio.wait_for(
                    client.send_and_recv(GetTime()),
                    timeout=5.0
                )
                if response:
                    print(f"Connection recovered successfully")
            except:
                print(f"Connection did not recover automatically")
                
        except (ConnectionError, OSError) as e:
            pytest.skip(f"Hardware not available: {e}")
    
    @pytest.mark.asyncio
    async def test_reconnect_after_network_interruption(self, client):
        """Test automatic reconnection after network interruption."""
        try:
            # Connect initially
            await client.connect()
            assert client.is_connected
            
            # Send initial command to verify connection
            response = await client.send_and_recv(GetTime())
            assert response is not None
            
            # Simulate network interruption by closing socket
            if client.connection and client.connection.writer:
                # Get the underlying socket
                transport = client.connection.writer.transport
                if hasattr(transport, '_sock'):
                    sock = transport._sock
                    # Force close the socket
                    sock.close()
            
            # Wait a moment for the client to detect disconnection
            await asyncio.sleep(1.0)
            
            # The connection should be detected as broken
            # Try to send command - should trigger reconnection
            reconnect_started = False
            for attempt in range(5):
                try:
                    response = await asyncio.wait_for(
                        client.send_and_recv(GetTime()),
                        timeout=3.0
                    )
                    if response:
                        reconnect_started = True
                        break
                except:
                    await asyncio.sleep(2.0)
            
            assert reconnect_started or not client.connection.is_connected(), \
                "Should either reconnect or detect disconnection"
                
        except (ConnectionError, OSError) as e:
            pytest.skip(f"Hardware not available: {e}")
    
    @pytest.mark.asyncio
    async def test_multiple_disconnects_recovery(self, client):
        """Test recovery from multiple disconnections."""
        try:
            await client.connect()
            assert client.is_connected
            
            disconnect_count = 0
            recovery_count = 0
            
            for round in range(3):
                # Send some commands
                try:
                    response = await client.send_and_recv(GetTime())
                    if response:
                        recovery_count += 1
                except:
                    pass
                
                # Force disconnect
                if client.connection and client.connection.writer:
                    client.connection.writer.close()
                    disconnect_count += 1
                    
                # Wait for recovery
                await asyncio.sleep(3.0)
                
                # Try to use connection again
                try:
                    response = await asyncio.wait_for(
                        client.send_and_recv(TestConnection()),
                        timeout=5.0
                    )
                    if response is not None:
                        recovery_count += 1
                except:
                    pass
            
            # Should have handled multiple disconnects
            assert disconnect_count == 3
            assert recovery_count >= 2, "Should recover from at least some disconnects"
            
        except (ConnectionError, OSError) as e:
            pytest.skip(f"Hardware not available: {e}")


class TestSlowConnection:
    """Test behavior with slow network connections."""
    
    @pytest_asyncio.fixture
    async def slow_client(self):
        """Create a client with longer timeouts for slow connection testing."""
        event_bus = EventBus()
        client = SeestarClient(
            host=TELESCOPE_HOST,
            port=TELESCOPE_PORT,
            event_bus=event_bus,
            connection_timeout=10.0,  # Longer timeout
            read_timeout=15.0,        # Longer read timeout
            write_timeout=10.0,       # Longer write timeout
        )
        yield client
        if client.is_connected:
            try:
                await client.disconnect()
            except:
                pass
    
    @pytest.mark.asyncio
    async def test_slow_response_handling(self, slow_client):
        """Test handling of slow responses from telescope."""
        try:
            # Patch the connection to add delays
            original_read = SeestarConnection.read
            
            async def slow_read(self):
                # Add artificial delay
                await asyncio.sleep(2.0)
                return await original_read(self)
            
            with patch.object(SeestarConnection, 'read', slow_read):
                await slow_client.connect()
                assert slow_client.is_connected
                
                # Commands should still work, just slower
                start_time = time.time()
                response = await slow_client.send_and_recv(GetTime())
                elapsed = time.time() - start_time
                
                assert response is not None
                assert elapsed >= 2.0, "Should have delay from slow connection"
                assert elapsed < 20.0, "Should not timeout with proper settings"
                
        except (ConnectionError, OSError) as e:
            pytest.skip(f"Hardware not available: {e}")
    
    @pytest.mark.asyncio
    async def test_slow_connection_establishment(self):
        """Test connecting to telescope with slow network."""
        event_bus = EventBus()
        
        # Create a proxy that delays connection
        class SlowConnectionProxy:
            def __init__(self, target_host, target_port, delay=3.0):
                self.target_host = target_host
                self.target_port = target_port
                self.delay = delay
                self.proxy_port = 14700  # Use different port for proxy
                self.server = None
                self.running = False
            
            async def start(self):
                """Start the slow proxy server."""
                self.running = True
                self.server = await asyncio.start_server(
                    self.handle_client,
                    'localhost',
                    self.proxy_port
                )
                
            async def handle_client(self, client_reader, client_writer):
                """Handle proxy connection with delay."""
                # Add delay before connecting to target
                await asyncio.sleep(self.delay)
                
                try:
                    # Connect to actual telescope
                    target_reader, target_writer = await asyncio.open_connection(
                        self.target_host,
                        self.target_port
                    )
                    
                    # Relay data between client and target
                    async def relay(reader, writer):
                        while self.running:
                            try:
                                data = await reader.read(4096)
                                if not data:
                                    break
                                writer.write(data)
                                await writer.drain()
                            except:
                                break
                    
                    # Start relaying in both directions
                    await asyncio.gather(
                        relay(client_reader, target_writer),
                        relay(target_reader, client_writer)
                    )
                    
                except Exception as e:
                    print(f"Proxy error: {e}")
                finally:
                    client_writer.close()
                    await client_writer.wait_closed()
            
            async def stop(self):
                """Stop the proxy server."""
                self.running = False
                if self.server:
                    self.server.close()
                    await self.server.wait_closed()
        
        # Start slow proxy
        proxy = SlowConnectionProxy(TELESCOPE_HOST, TELESCOPE_PORT, delay=2.0)
        await proxy.start()
        
        try:
            # Connect through slow proxy
            client = SeestarClient(
                host='localhost',
                port=14700,  # Connect to proxy
                event_bus=event_bus,
                connection_timeout=10.0,  # Must be longer than proxy delay
            )
            
            start_time = time.time()
            await client.connect()
            connect_time = time.time() - start_time
            
            assert client.is_connected
            assert connect_time >= 2.0, "Connection should be delayed by proxy"
            assert connect_time < 15.0, "Connection should not timeout"
            
            # Verify connection works
            response = await client.send_and_recv(TestConnection())
            assert response is not None or response == ""
            
            await client.disconnect()
            
        except (ConnectionError, OSError) as e:
            pytest.skip(f"Hardware or proxy not available: {e}")
        finally:
            await proxy.stop()
    
    @pytest.mark.asyncio
    async def test_command_timeout_recovery(self, slow_client):
        """Test recovery from command timeouts."""
        try:
            await slow_client.connect()
            assert slow_client.is_connected
            
            # Set very short timeout for commands
            slow_client.text_protocol.response_timeout = 0.5
            
            timeout_count = 0
            success_count = 0
            
            # Try multiple commands with short timeout
            for i in range(5):
                try:
                    response = await slow_client.send_and_recv(GetTime())
                    if response:
                        success_count += 1
                except asyncio.TimeoutError:
                    timeout_count += 1
                    # Increase timeout after failures
                    if timeout_count >= 2:
                        slow_client.text_protocol.response_timeout = 5.0
                
                await asyncio.sleep(0.5)
            
            # Should have some timeouts and then recover
            assert timeout_count >= 2, "Should have some timeouts with short timeout"
            assert success_count >= 1, "Should succeed after timeout adjustment"
            
            # Connection should still be alive
            assert slow_client.is_connected
            
        except (ConnectionError, OSError) as e:
            pytest.skip(f"Hardware not available: {e}")


class TestNetworkConditions:
    """Test various network conditions and failures."""
    
    @pytest_asyncio.fixture
    async def client(self):
        """Create a client for testing."""
        event_bus = EventBus()
        client = SeestarClient(
            host=TELESCOPE_HOST,
            port=TELESCOPE_PORT,
            event_bus=event_bus,
        )
        yield client
        if client.is_connected:
            try:
                await client.disconnect()
            except:
                pass
    
    @pytest.mark.asyncio
    async def test_packet_loss_simulation(self, client):
        """Test behavior with simulated packet loss."""
        try:
            # Patch read to occasionally fail
            original_read = client.connection.read
            read_count = [0]
            
            async def lossy_read():
                read_count[0] += 1
                # Fail every 3rd read
                if read_count[0] % 3 == 0:
                    return None  # Simulate lost packet
                return await original_read()
            
            await client.connect()
            client.connection.read = lossy_read
            
            # Send multiple commands
            success_count = 0
            fail_count = 0
            
            for _ in range(10):
                try:
                    response = await asyncio.wait_for(
                        client.send_and_recv(TestConnection()),
                        timeout=3.0
                    )
                    if response is not None:
                        success_count += 1
                    else:
                        fail_count += 1
                except:
                    fail_count += 1
                
                await asyncio.sleep(0.5)
            
            # Should handle some packet loss
            assert success_count > 0, "Should have some successful commands despite packet loss"
            assert fail_count > 0, "Should detect some failures from packet loss"
            
        except (ConnectionError, OSError) as e:
            pytest.skip(f"Hardware not available: {e}")
    
    @pytest.mark.asyncio
    async def test_connection_reset_during_read(self, client):
        """Test handling of connection reset during read operation."""
        try:
            await client.connect()
            assert client.is_connected
            
            # Start a long-running command
            command_task = asyncio.create_task(
                client.send_and_recv(GetDeviceState())
            )
            
            # Wait a moment then reset connection
            await asyncio.sleep(0.5)
            
            # Force connection reset
            if client.connection.reader:
                client.connection.reader.feed_eof()
            
            # Command should fail or timeout
            try:
                response = await asyncio.wait_for(command_task, timeout=5.0)
            except (asyncio.TimeoutError, ConnectionError):
                # Expected behavior
                pass
            
            # Give time for reconnection
            await asyncio.sleep(3.0)
            
            # Should be able to send new commands after recovery
            # (may need to reconnect manually depending on implementation)
            if not client.connection.is_connected():
                await client.connection.open()
            
            response = await client.send_and_recv(TestConnection())
            # Response might be None but shouldn't crash
            
        except (ConnectionError, OSError) as e:
            pytest.skip(f"Hardware not available: {e}")
    
    @pytest.mark.asyncio
    async def test_rapid_connect_disconnect(self, client):
        """Test rapid connection and disconnection cycles."""
        try:
            for cycle in range(5):
                # Connect
                await client.connect()
                assert client.is_connected
                
                # Send quick command
                try:
                    await asyncio.wait_for(
                        client.send_and_recv(TestConnection()),
                        timeout=2.0
                    )
                except:
                    pass  # Might fail during rapid cycling
                
                # Disconnect immediately
                await client.disconnect()
                assert not client.is_connected
                
                # Very short pause
                await asyncio.sleep(0.1)
            
            # Final connection should work normally
            await client.connect()
            response = await client.send_and_recv(GetTime())
            assert response is not None
            
        except (ConnectionError, OSError) as e:
            pytest.skip(f"Hardware not available: {e}")


class TestConcurrentOperations:
    """Test concurrent operations and thread safety."""
    
    @pytest_asyncio.fixture
    async def client(self):
        """Create a client for testing."""
        event_bus = EventBus()
        client = SeestarClient(
            host=TELESCOPE_HOST,
            port=TELESCOPE_PORT,
            event_bus=event_bus,
        )
        try:
            await client.connect()
            yield client
        except (ConnectionError, OSError) as e:
            pytest.skip(f"Hardware not available: {e}")
        finally:
            if client.is_connected:
                await client.disconnect()
    
    @pytest.mark.asyncio
    async def test_concurrent_commands(self, client):
        """Test sending multiple commands concurrently."""
        # Create multiple command tasks
        tasks = [
            client.send_and_recv(GetTime()),
            client.send_and_recv(GetDeviceState()),
            client.send_and_recv(GetViewState()),
            client.send_and_recv(GetFocuserPosition()),
            client.send_and_recv(ScopeGetEquCoord()),
        ]
        
        # Execute concurrently
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Check results
        success_count = sum(1 for r in results if r is not None and not isinstance(r, Exception))
        error_count = sum(1 for r in results if isinstance(r, Exception))
        
        assert success_count > 0, "Should have some successful concurrent commands"
        assert error_count < len(tasks), "Not all commands should fail"
    
    @pytest.mark.asyncio
    async def test_disconnect_during_concurrent_operations(self, client):
        """Test disconnect while multiple operations are in progress."""
        
        async def long_operation():
            """Simulate a long-running operation."""
            try:
                # Multiple commands in sequence
                for _ in range(10):
                    await client.send_and_recv(GetTime())
                    await asyncio.sleep(0.5)
                return "completed"
            except Exception as e:
                return f"failed: {e}"
        
        # Start multiple long operations
        tasks = [
            asyncio.create_task(long_operation()),
            asyncio.create_task(long_operation()),
            asyncio.create_task(long_operation()),
        ]
        
        # Wait a bit then disconnect
        await asyncio.sleep(2.0)
        await client.disconnect()
        
        # Wait for tasks to complete/fail
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Some tasks should have failed due to disconnect
        failed = [r for r in results if isinstance(r, str) and "failed" in r]
        assert len(failed) > 0, "Some operations should fail due to disconnect"


# Utility function to check if hardware is available
async def is_hardware_available():
    """Check if hardware is available for testing."""
    try:
        conn = SeestarConnection(
            host=TELESCOPE_HOST,
            port=TELESCOPE_PORT,
            connection_timeout=2.0,
        )
        await conn.open()
        await conn.close()
        return True
    except Exception:
        return False