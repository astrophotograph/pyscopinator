#!/usr/bin/env python
"""Test script to verify streaming reconnection works after connection reset.

This tests that the imaging client properly restarts streaming after a
connection is interrupted and reconnected.
"""

import asyncio
import os
import sys
import time
from scopinator.seestar.imaging_client import SeestarImagingClient
from scopinator.util.logging_config import setup_logging

# Get telescope host from environment or use default
TELESCOPE_HOST = os.environ.get("TELESCOPE_HOST", "192.168.42.41")


async def test_streaming_reconnect():
    """Test streaming reconnection after connection reset."""
    
    print(f"Testing streaming reconnection with telescope at {TELESCOPE_HOST}")
    print("-" * 60)
    
    # Create imaging client
    client = SeestarImagingClient(host=TELESCOPE_HOST, port=4800)
    
    try:
        # Connect
        print("\n1. Connecting to imaging client...")
        await client.connect()
        print(f"   Connected: {client.is_connected}")
        print(f"   Client mode: {client.client_mode}")
        
        # Start streaming
        print("\n2. Starting streaming...")
        await client.start_streaming()
        await asyncio.sleep(2)  # Let it stabilize
        
        # Get a few frames
        print("\n3. Getting initial frames...")
        frame_count = 0
        async for image in client.get_next_image(camera_id=0):
            if image and image.image is not None:
                frame_count += 1
                print(f"   Frame {frame_count}: {image.image.shape}")
                if frame_count >= 3:
                    break
        
        print(f"\n✅ Initial streaming working - received {frame_count} frames")
        
        # Now simulate a connection interruption
        print("\n4. Simulating connection interruption...")
        print("   (This would normally happen during a telescope restart)")
        print("   Please wait while monitoring reconnection...")
        
        # Monitor for a period to see reconnection behavior
        # In a real scenario, you would trigger a telescope restart here
        monitor_duration = 30  # seconds
        monitor_start = time.time()
        last_connected = True
        frames_after_reconnect = 0
        reconnection_detected = False
        
        print(f"\n5. Monitoring for {monitor_duration} seconds...")
        print("   (During a real test, restart the telescope now)")
        
        while (time.time() - monitor_start) < monitor_duration:
            current_connected = client.is_connected
            
            # Detect disconnection
            if last_connected and not current_connected:
                print(f"\n   ❌ Disconnection detected at {time.time() - monitor_start:.1f}s")
                reconnection_detected = True
            
            # Detect reconnection
            if not last_connected and current_connected:
                print(f"   ✅ Reconnection detected at {time.time() - monitor_start:.1f}s")
                print("      Checking if streaming resumes...")
                
                # Try to get frames after reconnection
                await asyncio.sleep(2)  # Give it time to stabilize
                
                frame_timeout = 5  # seconds to wait for frames
                frame_start = time.time()
                
                async for image in client.get_next_image(camera_id=0):
                    if image and image.image is not None:
                        frames_after_reconnect += 1
                        print(f"      ✅ Frame received after reconnect: {image.image.shape}")
                        break
                    if (time.time() - frame_start) > frame_timeout:
                        print(f"      ⚠️ No frames received within {frame_timeout}s after reconnect")
                        break
            
            last_connected = current_connected
            
            # Show status periodically
            elapsed = time.time() - monitor_start
            if int(elapsed) % 5 == 0 and elapsed > 0:
                status_symbol = "🟢" if current_connected else "🔴"
                streaming_symbol = "📹" if client.status.is_streaming else "⏸️"
                print(f"   [{elapsed:3.0f}s] Status: {status_symbol} Connected: {current_connected}, {streaming_symbol} Streaming: {client.status.is_streaming}")
            
            await asyncio.sleep(0.5)
        
        # Summary
        print("\n" + "=" * 60)
        print("TEST SUMMARY")
        print("=" * 60)
        print(f"Initial frames received: {frame_count}")
        print(f"Reconnection detected: {reconnection_detected}")
        print(f"Frames after reconnect: {frames_after_reconnect}")
        
        if frames_after_reconnect > 0:
            print("\n✅ SUCCESS: Streaming properly resumed after reconnection!")
        elif not reconnection_detected:
            print("\n⚠️ No disconnection detected during test period.")
            print("   To fully test, restart the telescope during monitoring.")
        else:
            print("\n❌ FAILURE: Streaming did not resume after reconnection")
        
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Cleanup
        if client.is_connected:
            try:
                await client.disconnect()
            except:
                pass
    
    print("\nTest completed")


if __name__ == "__main__":
    # Configure logging
    debug = "--debug" in sys.argv
    trace = "--trace" in sys.argv
    setup_logging(debug=debug, trace=trace)
    
    # Run test
    asyncio.run(test_streaming_reconnect())