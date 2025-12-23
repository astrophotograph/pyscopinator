#!/usr/bin/env python3
"""Test script for Alpaca camera image capture.

Usage:
    python scripts/test_alpaca_camera.py [host] [port]

Example:
    python scripts/test_alpaca_camera.py 192.168.42.93 32323
"""

import asyncio
import logging
import sys
import time
from pathlib import Path

# Add src to path for development
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from scopinator.v2.backends.alpaca import AlpacaBackend
from scopinator.v2.core.types import ExposureSettings

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


async def test_alpaca_camera(host: str, port: int):
    """Test Alpaca camera connection and image capture."""

    logger.info(f"Connecting to Alpaca server at {host}:{port}...")

    backend = AlpacaBackend(host=host, port=port)

    try:
        # Connect to the server
        await backend.connect()
        logger.info("Connected to Alpaca server")

        # Discover devices
        logger.info("Discovering devices...")
        devices = await backend.discover_devices()
        logger.info(f"Found devices: {devices}")

        if not devices.get("camera"):
            logger.error("No camera found!")
            return

        camera_id = devices["camera"][0]
        logger.info(f"Using camera: {camera_id}")

        # Get camera
        camera = await backend.get_camera(camera_id)
        await camera.connect()
        logger.info("Camera connected")

        # Get capabilities
        logger.info("Querying camera capabilities...")
        caps = await camera.get_capabilities()
        logger.info(f"  Sensor size: {caps.sensor_width}x{caps.sensor_height}")
        logger.info(f"  Max binning: {caps.max_bin_x}x{caps.max_bin_y}")
        logger.info(f"  Pixel size: {caps.pixel_size_x}x{caps.pixel_size_y} um")
        logger.info(f"  Color sensor: {caps.is_color}")

        # Get initial status
        status = await camera.get_status()
        logger.info(f"Camera state: {status.state}")
        logger.info(f"Temperature: {status.temperature}")

        # Check if image already ready
        logger.info("Checking if image already ready...")
        if await camera.is_image_ready():
            logger.info("Image already ready from previous exposure")
        else:
            logger.info("No image ready, starting new exposure...")

            # Start exposure with 2x2 binning for faster download
            settings = ExposureSettings(
                duration_seconds=1.0,
                light=True,
                bin_x=2,
                bin_y=2,
            )

            logger.info(f"Starting {settings.duration_seconds}s exposure with {settings.bin_x}x{settings.bin_y} binning...")
            start_time = time.time()
            await camera.start_exposure(settings)

            # Poll for completion
            logger.info("Waiting for exposure to complete...")
            poll_count = 0
            while True:
                await asyncio.sleep(0.5)
                poll_count += 1

                try:
                    is_exposing = await camera.is_exposing()
                    is_ready = await camera.is_image_ready()
                    status = await camera.get_status()

                    elapsed = time.time() - start_time
                    logger.info(f"  [{elapsed:.1f}s] exposing={is_exposing}, ready={is_ready}, state={status.state}, progress={status.exposure_progress:.0%}")

                    if is_ready:
                        logger.info(f"Image ready after {elapsed:.1f}s")
                        break

                    if poll_count > 60:  # 30 second timeout
                        logger.error("Timeout waiting for exposure!")
                        return

                except Exception as e:
                    logger.warning(f"  Poll error: {e}")

        # Download image
        logger.info("Downloading image (this may take a while for large images)...")
        download_start = time.time()

        try:
            image_data = await camera.get_image()
            download_time = time.time() - download_start

            logger.info(f"Image downloaded in {download_time:.1f}s")
            logger.info(f"  Size: {image_data.width}x{image_data.height}")
            logger.info(f"  Data: {len(image_data.data)} bytes")
            logger.info(f"  Bit depth: {image_data.bit_depth}")

            # Save as raw data for inspection
            output_path = Path(__file__).parent / "test_image.raw"
            with open(output_path, "wb") as f:
                f.write(image_data.data)
            logger.info(f"Saved raw data to {output_path}")

            # Try to convert to PNG
            try:
                import numpy as np
                from PIL import Image
                import struct

                num_pixels = image_data.width * image_data.height
                expected_bytes = num_pixels * 2

                if len(image_data.data) == expected_bytes:
                    pixels = struct.unpack(f">{num_pixels}H", image_data.data)
                    # Alpaca uses width as first dimension
                    frame = np.array(pixels, dtype=np.uint16).reshape((image_data.width, image_data.height)).T

                    # Auto-stretch
                    min_val = np.percentile(frame, 1)
                    max_val = np.percentile(frame, 99)
                    if max_val > min_val:
                        frame = ((frame - min_val) / (max_val - min_val) * 255).clip(0, 255).astype(np.uint8)
                    else:
                        frame = (frame / 256).astype(np.uint8)

                    img = Image.fromarray(frame, mode='L')
                    png_path = Path(__file__).parent / "test_image.png"
                    img.save(png_path)
                    logger.info(f"Saved PNG to {png_path}")
                else:
                    logger.warning(f"Data size mismatch: got {len(image_data.data)}, expected {expected_bytes}")

            except ImportError:
                logger.info("PIL/numpy not available, skipping PNG conversion")
            except Exception as e:
                logger.error(f"Failed to convert to PNG: {e}")

        except Exception as e:
            logger.error(f"Failed to download image: {e}", exc_info=True)

        # Disconnect camera
        await camera.disconnect()
        logger.info("Camera disconnected")

    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
    finally:
        await backend.disconnect()
        logger.info("Disconnected from Alpaca server")


def main():
    host = sys.argv[1] if len(sys.argv) > 1 else "192.168.42.93"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 32323

    logger.info(f"Testing Alpaca camera at {host}:{port}")
    asyncio.run(test_alpaca_camera(host, port))


if __name__ == "__main__":
    main()
