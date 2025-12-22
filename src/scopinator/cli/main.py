"""Main CLI entry point for scopinator."""

import asyncio
import click
import sys
import json
import os

from scopinator.seestar.commands.imaging import BeginStreaming
from scopinator.seestar.commands.parameterized import IscopeStartView
from scopinator.util.logging_config import setup_logging, get_logger


@click.group(invoke_without_command=True)
@click.option('--debug', is_flag=True, help='Enable debug logging (shows detailed connection info)')
@click.option('--trace', is_flag=True, help='Enable trace logging (most verbose, shows all internal operations)')
@click.option('--quiet', is_flag=True, help='Reduce logging to warnings and errors only')
@click.option('--log-level', type=click.Choice(['TRACE', 'DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'], case_sensitive=False),
              help='Set explicit log level (overrides other flags)')
@click.option('--protocol', '-P', type=click.Choice(['seestar', 'alpaca', 'indi', 'auto']),
              default='auto', help='Protocol to use (default: auto-detect)')
@click.option('--profile', '-p', help='Use a saved profile by name')
@click.pass_context
def cli(ctx, debug, trace, quiet, log_level, protocol, profile):
    """Scopinator - Control and manage telescopes from the command line.

    Use 'scopinator repl' to enter interactive mode with autocompletion.

    Logging can be controlled via:
    - CLI flags: --debug, --trace, --quiet, --log-level
    - Environment variables: SCOPINATOR_DEBUG=true, SCOPINATOR_TRACE=true, SCOPINATOR_LOG_LEVEL=DEBUG

    Protocol selection:
    - Use --protocol to specify which protocol to use (seestar, alpaca, indi)
    - Use --profile to load a saved telescope profile
    """
    # Configure logging based on flags and environment
    setup_logging(debug=debug, trace=trace, quiet=quiet, level=log_level)

    # Get a logger for the CLI
    logger = get_logger(__name__)

    ctx.ensure_object(dict)
    ctx.obj['debug'] = debug
    ctx.obj['trace'] = trace
    ctx.obj['quiet'] = quiet
    ctx.obj['log_level'] = log_level
    ctx.obj['logger'] = logger
    ctx.obj['protocol'] = protocol
    ctx.obj['profile_name'] = profile

    # Load profile if specified
    if profile:
        from scopinator.cli.commands.profile import load_profile
        loaded_profile = load_profile(profile)
        if loaded_profile:
            ctx.obj['profile'] = loaded_profile
            logger.debug(f"Loaded profile: {profile}")
        else:
            click.echo(f"Warning: Profile '{profile}' not found", err=True)

    # Show help if no subcommand
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())

# Register the enhanced REPL command
from scopinator.cli.repl_enhanced import register_enhanced_repl
register_enhanced_repl(cli)

# Register profile management commands
from scopinator.cli.commands.profile import profile as profile_group
cli.add_command(profile_group)


@cli.command()
@click.option('--host', '-h', help='Telescope IP address or hostname')
@click.option('--port', '-p', type=int, help='Port number (default depends on protocol)')
@click.option('--timeout', '-t', default=5.0, help='Discovery timeout in seconds (default: 5)')
@click.pass_context
def discover(ctx, host, port, timeout):
    """Discover available telescopes on the network.

    Supports discovery for multiple protocols:
    - Seestar: Uses mDNS/broadcast discovery
    - Alpaca: Uses UDP broadcast on port 32227, then queries management API
    - INDI: Connects to INDI server and lists devices

    Examples:
      scopinator discover                              # Discover Seestar devices
      scopinator --protocol alpaca discover            # Discover Alpaca servers on network
      scopinator --protocol alpaca discover -h 192.168.1.100  # Query specific Alpaca server
    """
    from scopinator.cli.protocol_helper import get_protocol_and_connection, DEFAULT_PORTS
    import time

    # Ensure context exists
    if not ctx.obj:
        ctx.obj = {}

    # Get protocol
    protocol = ctx.obj.get('protocol', 'auto')
    if protocol == 'auto':
        protocol = 'seestar'  # Default to seestar for discovery

    async def run_discovery():
        if host:
            # Check specific host
            final_port = port or DEFAULT_PORTS.get(protocol, 4700)
            click.echo(f"🔍 Checking {host}:{final_port} ({protocol})...")

            if protocol == "seestar":
                from scopinator.seestar.connection import SeestarConnection
                conn = SeestarConnection(host=host, port=final_port)
                try:
                    await asyncio.wait_for(conn.open(), timeout=timeout)
                    click.echo(f"✅ Found Seestar at {host}:{final_port}")
                    await conn.close()
                    return [{"type": "seestar", "host": host, "port": final_port}]
                except Exception as e:
                    click.echo(f"❌ No telescope found at {host}:{final_port}: {e}")
                    return []

            elif protocol == "alpaca":
                import aiohttp
                from scopinator.v2.backends.alpaca.discovery import AlpacaDiscovery
                try:
                    async with aiohttp.ClientSession() as session:
                        base_url = f"http://{host}:{final_port}"
                        discovery = AlpacaDiscovery(session, base_url, timeout=timeout)
                        devices = await discovery.get_configured_devices()
                        if devices:
                            total = sum(len(d) for d in devices.values())
                            click.echo(f"✅ Found {total} Alpaca device(s) at {host}:{final_port}")
                            result = []
                            for device_type, device_list in devices.items():
                                for d in device_list:
                                    result.append({
                                        "type": "alpaca",
                                        "host": host,
                                        "port": final_port,
                                        "device_type": device_type,
                                        "device_name": d.get("DeviceName", ""),
                                        "device_number": d.get("DeviceNumber", 0),
                                    })
                            return result
                        else:
                            click.echo(f"❌ No Alpaca devices found at {host}:{final_port}")
                            return []
                except Exception as e:
                    click.echo(f"❌ Error discovering Alpaca devices: {e}")
                    return []

            elif protocol == "indi":
                from scopinator.v2.backends.indi import INDIBackend
                try:
                    backend = INDIBackend(host=host, port=final_port)
                    await backend.connect()
                    devices = await backend.discover_devices()
                    await backend.disconnect()
                    if devices:
                        click.echo(f"✅ Found INDI devices at {host}:{final_port}")
                        return [{"type": "indi", "host": host, "port": final_port, "devices": devices}]
                    else:
                        click.echo(f"❌ No INDI devices found at {host}:{final_port}")
                        return []
                except Exception as e:
                    click.echo(f"❌ Error discovering INDI devices: {e}")
                    return []

        else:
            # Network discovery
            if protocol == "seestar":
                from scopinator.cli.commands.discovery import discover_telescopes
                click.echo(f"🔍 Searching for Seestar telescopes on the network (timeout: {timeout}s)...")
                click.echo("   This may take a few seconds...")

                start_time = time.time()
                telescopes = await discover_telescopes(timeout=timeout)
                elapsed = time.time() - start_time

                click.echo(f"   Search completed in {elapsed:.1f} seconds")
                return [{"type": "seestar", "host": ip, "port": p} for ip, p in telescopes]

            elif protocol == "alpaca":
                from scopinator.v2.backends.alpaca.discovery import discover_alpaca_servers, AlpacaDiscovery
                click.echo(f"🔍 Searching for Alpaca servers on the network (timeout: {timeout}s)...")
                click.echo("   Broadcasting to UDP port 32227...")

                start_time = time.time()
                servers = await discover_alpaca_servers(timeout=timeout)
                elapsed = time.time() - start_time

                click.echo(f"   Search completed in {elapsed:.1f} seconds")

                if not servers:
                    return []

                # For each discovered server, query its devices
                result = []
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    for server in servers:
                        server_host = server.get("host")
                        alpaca_port = server.get("AlpacaPort", 11111)
                        click.echo(f"   Found server at {server_host}:{alpaca_port}, querying devices...")

                        try:
                            discovery = AlpacaDiscovery(session, f"http://{server_host}:{alpaca_port}", timeout=5.0)
                            devices = await discovery.get_configured_devices()
                            for device_type, device_list in devices.items():
                                for d in device_list:
                                    result.append({
                                        "type": "alpaca",
                                        "host": server_host,
                                        "port": alpaca_port,
                                        "device_type": device_type,
                                        "device_name": d.get("DeviceName", ""),
                                        "device_number": d.get("DeviceNumber", 0),
                                    })
                        except Exception as e:
                            click.echo(f"   ⚠️ Could not query devices on {server_host}:{alpaca_port}: {e}")

                return result

            else:
                click.echo(f"⚠️ Network discovery is not supported for {protocol}.")
                click.echo(f"   Please specify --host")
                return []

    devices = asyncio.run(run_discovery())

    if not devices and not host:
        click.echo("\n❌ No telescopes found.")
        click.echo("   Make sure your telescope is:")
        click.echo("   • Powered on")
        click.echo("   • Connected to the same network")
        click.echo("   • Not already connected to another app")
        click.echo("\n   Try specifying the IP directly: scopinator discover --host <IP>")
    elif devices and not host:
        click.echo(f"\n✅ Found {len(devices)} device(s):")
        for idx, device in enumerate(devices, 1):
            device_type = device.get('type', 'unknown')
            device_host = device.get('host', 'unknown')
            device_port = device.get('port', '')
            click.echo(f"  {idx}. {device_type}: {device_host}:{device_port}")
            if device.get('device_name'):
                click.echo(f"     Name: {device['device_name']}")
            if device.get('device_type'):
                click.echo(f"     Type: {device['device_type']}")
        # Show appropriate connect command
        if protocol == "alpaca" and devices:
            first_port = devices[0].get('port', 11111)
            click.echo(f"\nTo connect: scopinator --protocol alpaca connect <IP> -p {first_port}")
        else:
            click.echo(f"\nTo connect: scopinator --protocol {protocol} connect <IP>")


@cli.command()
@click.argument('host')
@click.option('--port', '-p', type=int, help='Port number (default depends on protocol)')
@click.option('--timeout', '-t', default=10.0, help='Connection timeout in seconds')
@click.pass_context
def connect(ctx, host, port, timeout):
    """Connect to a telescope and save connection info.

    Supports multiple protocols via the global --protocol option:
      scopinator --protocol alpaca connect localhost
      scopinator --protocol indi connect localhost
      scopinator connect 192.168.1.100  # defaults to seestar
    """
    from scopinator.cli.protocol_helper import get_protocol_and_connection, create_client

    # Ensure context exists
    if not ctx.obj:
        ctx.obj = {}

    # Get protocol and resolve port
    protocol, _, resolved_port = get_protocol_and_connection(ctx, host, port)
    final_port = port if port else resolved_port

    async def test_connection():
        try:
            client = await asyncio.wait_for(
                create_client(protocol, host, final_port),
                timeout=timeout
            )

            click.echo(f"✅ Successfully connected to telescope at {host}:{final_port}")
            click.echo(f"   Protocol: {protocol}")

            # Save connection info to context
            ctx.obj['host'] = host
            ctx.obj['port'] = final_port
            ctx.obj['protocol'] = protocol

            # Try to get status info (non-fatal if fails)
            try:
                status = await client.get_status()

                if status.get('battery'):
                    click.echo(f"   Battery: {status['battery']}%")
                if status.get('temperature'):
                    click.echo(f"   Temperature: {status['temperature']}C")
                if status.get('ra') is not None and status.get('dec') is not None:
                    click.echo(f"   Position: RA {status['ra']:.4f}, Dec {status['dec']:.4f}")
            except Exception:
                pass  # Status retrieval is optional

            await client.disconnect()
            return True

        except asyncio.TimeoutError:
            click.echo(f"Connection timed out after {timeout}s")
            return False
        except Exception as e:
            click.echo(f"Failed to connect: {e}")
            return False

    success = asyncio.run(test_connection())
    if success:
        # Persist connection state to disk
        from scopinator.cli.connection_state import save_connection_state
        save_connection_state(protocol, host, final_port)
        click.echo("\nConnection saved. Use other commands to control the telescope.")


@cli.command()
def disconnect():
    """Clear saved connection state.

    This removes the saved connection info, requiring you to
    specify --host again or use 'connect' to save new info.
    """
    from scopinator.cli.connection_state import clear_connection_state, load_connection_state

    state = load_connection_state()
    if state:
        clear_connection_state()
        click.echo(f"Cleared connection to {state.get('host')}:{state.get('port')} ({state.get('protocol')})")
    else:
        click.echo("No saved connection to clear.")


@cli.command()
@click.option('--host', '-h', help='Telescope IP (uses saved connection if not provided)')
@click.option('--port', '-p', type=int, help='Port number')
@click.option('--detailed', '-d', is_flag=True, help='Show detailed device information')
@click.pass_context
def status(ctx, host, port, detailed):
    """Get current telescope status.

    Works with all supported protocols (Seestar, Alpaca, INDI).
    Use --protocol to specify which protocol to use.
    """
    from scopinator.cli.protocol_helper import (
        get_protocol_and_connection,
        create_client,
        require_host,
    )

    # Ensure context exists
    if not ctx.obj:
        ctx.obj = {}

    # Get protocol and connection info
    protocol, resolved_host, resolved_port = get_protocol_and_connection(ctx, host, port)
    final_host = host or resolved_host
    final_port = port or resolved_port

    require_host(final_host, ctx)

    async def get_status():
        try:
            client = await create_client(protocol, final_host, final_port)
            click.echo(f"📡 Connected to {final_host}:{final_port} ({protocol})\n")

            # For Seestar, show detailed device state if requested
            if protocol == "seestar" and detailed and client._seestar_client:
                from scopinator.seestar.commands.simple import GetDeviceState
                seestar = client._seestar_client

                device_response = await seestar.send_and_recv(GetDeviceState())
                if device_response and device_response.result:
                    device_state = device_response.result

                    # Device Information
                    if 'device' in device_state:
                        click.echo("🔭 Device Information:")
                        click.echo("-" * 40)
                        dev = device_state['device']
                        click.echo(f"Model: {dev.get('name', 'N/A')}")
                        click.echo(f"Serial: {dev.get('id', 'N/A')}")
                        click.echo(f"Firmware: {dev.get('app_ver', 'N/A')}")
                        click.echo(f"System Version: {dev.get('pi_ver', 'N/A')}")
                        click.echo()

                    # Power & Temperature
                    if 'pi_status' in device_state:
                        click.echo("⚡ Power & Temperature:")
                        click.echo("-" * 40)
                        pi = device_state['pi_status']
                        click.echo(f"Battery: {pi.get('battery_capacity', 'N/A')}%")
                        click.echo(f"Charger: {pi.get('charger_status', 'N/A')}")
                        click.echo(f"Charging: {'Yes' if pi.get('charge_online') else 'No'}")
                        click.echo(f"Temperature: {pi.get('temp', 'N/A')}°C")
                        click.echo(f"Battery Temp: {pi.get('battery_temp', 'N/A')}°C")
                        click.echo(f"Over Temperature: {'Yes' if pi.get('is_overtemp') else 'No'}")
                        click.echo()

                    # Storage
                    if 'storage' in device_state:
                        click.echo("💾 Storage:")
                        click.echo("-" * 40)
                        storage = device_state['storage']
                        click.echo(f"Current Storage: {storage.get('cur_storage', 'N/A')}")
                        if 'storage_volume' in storage:
                            for vol in storage['storage_volume']:
                                click.echo(f"  {vol.get('name', 'N/A')}: {vol.get('freeMB', 0):,} MB free / {vol.get('totalMB', 0):,} MB total ({vol.get('used_percent', 0)}% used)")
                        click.echo()

                    # Network
                    if 'station' in device_state:
                        click.echo("📶 Network:")
                        click.echo("-" * 40)
                        station = device_state['station']
                        if station.get('ssid'):
                            click.echo(f"WiFi SSID: {station.get('ssid', 'N/A')}")
                        if station.get('ip'):
                            click.echo(f"IP Address: {station.get('ip', 'N/A')}")
                        if station.get('sig_lev') is not None:
                            click.echo(f"Signal Level: {station.get('sig_lev', 'N/A')} dBm")
                        click.echo()

                    # Mount
                    if 'mount' in device_state:
                        click.echo("🎯 Mount:")
                        click.echo("-" * 40)
                        mount = device_state['mount']
                        click.echo(f"Tracking: {'Yes' if mount.get('tracking') else 'No'}")
                        click.echo(f"Equatorial Mode: {'Yes' if mount.get('equ_mode') else 'No'}")
                        click.echo(f"Move Type: {mount.get('move_type', 'N/A')}")
                        click.echo()

                    # Focuser
                    if 'focuser' in device_state:
                        click.echo("🔍 Focuser:")
                        click.echo("-" * 40)
                        focuser = device_state['focuser']
                        click.echo(f"Position: {focuser.get('step', 'N/A')} / {focuser.get('max_step', 'N/A')}")
                        click.echo(f"State: {focuser.get('state', 'N/A')}")
                        click.echo()

                    # Balance Sensor
                    if 'balance_sensor' in device_state:
                        click.echo("⚖️ Balance Sensor:")
                        click.echo("-" * 40)
                        sensor = device_state['balance_sensor']
                        if 'data' in sensor:
                            data = sensor['data']
                            click.echo(f"Angle: {data.get('angle', 'N/A')}°")
                            click.echo(f"X: {data.get('x', 'N/A')}, Y: {data.get('y', 'N/A')}, Z: {data.get('z', 'N/A')}")
                        click.echo()

            # Show status using unified interface
            click.echo("📊 Current Status:")
            click.echo("-" * 40)

            status_data = await client.get_status()

            # Display common status fields
            if status_data.get('battery') is not None:
                icon = "🔋" if status_data['battery'] > 20 else "🪫"
                click.echo(f"{icon} Battery: {status_data['battery']}%")
            if status_data.get('temperature') is not None:
                click.echo(f"🌡️ Temperature: {status_data['temperature']}°C")
            if status_data.get('ra') is not None and status_data.get('dec') is not None:
                click.echo(f"📍 Coordinates: RA={status_data['ra']:.4f}°, Dec={status_data['dec']:.4f}°")
            if status_data.get('alt') is not None and status_data.get('az') is not None:
                click.echo(f"🧭 Alt/Az: Alt={status_data['alt']:.2f}°, Az={status_data['az']:.2f}°")
            if status_data.get('tracking'):
                click.echo(f"🎯 Tracking: {status_data['tracking']}")
            if status_data.get('slew_state'):
                click.echo(f"🔄 Slew State: {status_data['slew_state']}")
            if status_data.get('target_name'):
                click.echo(f"🎯 Target: {status_data['target_name']}")
            if status_data.get('stacked_frames'):
                click.echo(f"📸 Stacked Frames: {status_data['stacked_frames']}")

            # Seestar-specific detailed status
            if protocol == "seestar" and client._seestar_client:
                seestar_status = client._seestar_client.status
                if seestar_status:
                    if seestar_status.charger_status:
                        click.echo(f"⚡ Charger: {seestar_status.charger_status}")
                    if seestar_status.dist_deg is not None:
                        click.echo(f"📏 Distance to target: {seestar_status.dist_deg:.2f}°")
                    if seestar_status.stacked_frame > 0 or seestar_status.dropped_frame > 0:
                        click.echo(f"📸 Frames: {seestar_status.stacked_frame} stacked, {seestar_status.dropped_frame} dropped")
                    if seestar_status.gain is not None:
                        click.echo(f"📊 Gain: {seestar_status.gain}")
                    if seestar_status.lp_filter:
                        click.echo("🔴 LP Filter: Active")
                    if seestar_status.focus_position is not None:
                        click.echo(f"🔍 Focus Position: {seestar_status.focus_position}")
                    if seestar_status.freeMB is not None and seestar_status.totalMB is not None:
                        used_percent = ((seestar_status.totalMB - seestar_status.freeMB) / seestar_status.totalMB * 100) if seestar_status.totalMB > 0 else 0
                        click.echo(f"💾 Storage: {seestar_status.freeMB:,} MB free / {seestar_status.totalMB:,} MB total ({used_percent:.1f}% used)")
                    if seestar_status.stage:
                        click.echo(f"🎬 Stage: {seestar_status.stage}")

                # Client mode
                if client._seestar_client.client_mode:
                    click.echo(f"\n🎮 Client Mode: {client._seestar_client.client_mode}")

            await client.disconnect()

        except Exception as e:
            click.echo(f"❌ Error getting status: {e}")

    asyncio.run(get_status())


@cli.command()
@click.option('--host', '-h', help='Telescope IP (uses saved connection if not provided)')
@click.option('--port', '-p', type=int, help='Port number')
@click.pass_context
def park(ctx, host, port):
    """Park the telescope.

    Works with all supported protocols (Seestar, Alpaca, INDI).
    """
    from scopinator.cli.protocol_helper import (
        get_protocol_and_connection,
        create_client,
        require_host,
    )

    # Ensure context exists
    if not ctx.obj:
        ctx.obj = {}

    # Get protocol and connection info
    protocol, resolved_host, resolved_port = get_protocol_and_connection(ctx, host, port)
    final_host = host or resolved_host
    final_port = port or resolved_port

    require_host(final_host, ctx)

    async def park_telescope():
        try:
            client = await create_client(protocol, final_host, final_port)
            click.echo(f"🔭 Parking telescope at {final_host}:{final_port} ({protocol})...")

            success = await client.park()
            if success:
                click.echo("✅ Telescope parked successfully")
            else:
                click.echo("⚠️ Park command sent but no confirmation received")

            await client.disconnect()
        except Exception as e:
            click.echo(f"❌ Error parking telescope: {e}")

    asyncio.run(park_telescope())


@cli.command()
@click.argument('ra', type=float)
@click.argument('dec', type=float)
@click.option('--host', '-h', help='Telescope IP (uses saved connection if not provided)')
@click.option('--port', '-p', type=int, help='Port number')
@click.option('--name', '-n', help='Target name')
@click.pass_context
def goto(ctx, ra, dec, host, port, name):
    """Go to specific RA/Dec coordinates.

    RA: Right Ascension in degrees (0-360)
    DEC: Declination in degrees (-90 to 90)

    Works with all supported protocols (Seestar, Alpaca, INDI).

    Examples:
      scopinator goto 83.63 22.01 --name "Orion Nebula"
      scopinator --protocol alpaca goto 83.63 22.01 -h localhost
    """
    from scopinator.cli.protocol_helper import (
        get_protocol_and_connection,
        create_client,
        require_host,
    )

    # Ensure context exists
    if not ctx.obj:
        ctx.obj = {}

    # Get protocol and connection info
    protocol, resolved_host, resolved_port = get_protocol_and_connection(ctx, host, port)
    final_host = host or resolved_host
    final_port = port or resolved_port

    require_host(final_host, ctx)

    async def goto_target():
        try:
            client = await create_client(protocol, final_host, final_port)
            target_desc = name or f"RA={ra:.2f}, Dec={dec:.2f}"
            click.echo(f"🎯 Slewing to {target_desc} ({protocol})...")

            success = await client.goto(ra, dec, name)

            if success:
                click.echo("✅ Slewing to target initiated")

                # Wait a moment and check position
                await asyncio.sleep(2)
                status = await client.get_status()
                if status.get('ra') is not None and status.get('dec') is not None:
                    click.echo(f"📍 Current position: RA={status['ra']:.4f}°, Dec={status['dec']:.4f}°")
            else:
                click.echo("⚠️ Goto command sent but no confirmation received")

            await client.disconnect()
        except Exception as e:
            click.echo(f"❌ Error executing goto: {e}")

    asyncio.run(goto_target())


@cli.command()
@click.option('--host', '-h', help='Telescope IP (uses saved connection if not provided)')
@click.option('--port', '-p', type=int, help='Port number (default: 4800 for imaging)')
@click.option('--duration', '-d', default=10, type=int, help='Stream duration in seconds')
@click.pass_context
def stream(ctx, host, port, duration):
    """Start live image streaming from the telescope."""
    # Ensure context exists
    if not ctx.obj:
        ctx.obj = {}
    
    host = host or ctx.obj.get('host')
    port = port or 4800  # Imaging client uses port 4800
    
    if not host:
        click.echo("❌ No telescope connection. Use 'connect' command first or provide --host")
        return
    
    from scopinator.seestar.imaging_client import SeestarImagingClient
    
    async def start_stream():
        client = SeestarImagingClient(host=host, port=port)
        try:
            await client.connect()
            click.echo(f"📹 Starting image stream from {host}:{port}")
            click.echo(f"Streaming for {duration} seconds...")
            
            await client.begin_streaming()
            
            # Stream for specified duration
            start_time = asyncio.get_event_loop().time()
            while (asyncio.get_event_loop().time() - start_time) < duration:
                await asyncio.sleep(1)
                status = client.status
                if status.stacked_frame > 0:
                    click.echo(f"📊 Frames: {status.stacked_frame} stacked, {status.dropped_frame} dropped")
            
            await client.stop_streaming()
            click.echo("✅ Streaming stopped")
            
            await client.disconnect()
        except Exception as e:
            click.echo(f"❌ Error during streaming: {e}")
    
    asyncio.run(start_stream())


@cli.command(name='interactive')
@click.pass_context  
def interactive_cmd(ctx):
    """Enter enhanced interactive mode with intellisense and autocomplete."""
    from scopinator.cli.interactive_simple import run_interactive_mode
    
    # Run our custom interactive mode with intellisense
    run_interactive_mode(cli, ctx)


@cli.command()
@click.pass_context
def version(ctx):
    """Show scopinator version."""
    try:
        from importlib.metadata import version
        v = version('scopinator')
        click.echo(f"Scopinator version: {v}")
        # Show CalVer format explanation
        if '.' in v:
            parts = v.split('.')
            if len(parts) >= 2 and parts[0].isdigit() and int(parts[0]) >= 2024:
                click.echo("  Format: CalVer (YYYY.MM.PATCH)")
                click.echo(f"  Year: {parts[0]}, Month: {parts[1]}, Patch: {parts[2] if len(parts) > 2 else '0'}")
    except:
        # Fallback to package version if metadata not available
        try:
            from scopinator import __version__
            click.echo(f"Scopinator version: {__version__}")
            click.echo("  Format: CalVer (YYYY.MM.PATCH)")
        except:
            click.echo("Scopinator version: development")


# ============= Simple commands without parameters =============

@cli.command(name='camera-info')
@click.option('--host', '-h', help='Telescope IP (uses saved connection if not provided)')
@click.option('--port', '-p', type=int, help='Port number')
@click.pass_context
def camera_info(ctx, host, port):
    """Get camera information (chip size, pixel size, etc)."""
    # Ensure context exists
    if not ctx.obj:
        ctx.obj = {}
    
    host = host or ctx.obj.get('host')
    port = port or ctx.obj.get('port', 4700)
    
    if not host:
        click.echo("❌ No telescope connection. Use 'connect' command first or provide --host")
        return
    
    from scopinator.seestar.client import SeestarClient
    from scopinator.seestar.commands.simple import GetCameraInfo
    
    async def get_camera_info():
        client = SeestarClient(host=host, port=port)
        try:
            await client.connect()
            response = await client.send_and_recv(GetCameraInfo())
            if response and response.result:
                info = response.result
                click.echo("📷 Camera Information:")
                click.echo("-" * 40)
                if 'chip_size' in info:
                    # Handle both tuple and dict formats
                    if isinstance(info['chip_size'], (list, tuple)):
                        click.echo(f"Chip Size: {info['chip_size'][0]}x{info['chip_size'][1]}")
                    else:
                        click.echo(f"Chip Size: {info['chip_size']['width']}x{info['chip_size']['height']}")
                if 'pixel_size_um' in info:
                    click.echo(f"Pixel Size: {info['pixel_size_um']} μm")
                if 'unity_gain' in info:
                    click.echo(f"Unity Gain: {info['unity_gain']}")
                if 'debayer_pattern' in info:
                    click.echo(f"Debayer Pattern: {info['debayer_pattern']}")
                if 'has_cooler' in info:
                    click.echo(f"Has Cooler: {'Yes' if info['has_cooler'] else 'No'}")
                if 'is_color' in info:
                    click.echo(f"Color Camera: {'Yes' if info['is_color'] else 'No'}")
                if 'is_usb3_host' in info:
                    click.echo(f"USB3 Host: {'Yes' if info['is_usb3_host'] else 'No'}")
            await client.disconnect()
        except Exception as e:
            click.echo(f"❌ Error getting camera info: {e}")
    
    asyncio.run(get_camera_info())


@cli.command(name='disk-volume')
@click.option('--host', '-h', help='Telescope IP (uses saved connection if not provided)')
@click.option('--port', '-p', type=int, help='Port number')
@click.pass_context
def disk_volume(ctx, host, port):
    """Get disk volume information."""
    # Ensure context exists
    if not ctx.obj:
        ctx.obj = {}
    
    host = host or ctx.obj.get('host')
    port = port or ctx.obj.get('port', 4700)
    
    if not host:
        click.echo("❌ No telescope connection. Use 'connect' command first or provide --host")
        return
    
    from scopinator.seestar.client import SeestarClient
    from scopinator.seestar.commands.simple import GetDiskVolume
    
    async def get_disk_volume():
        client = SeestarClient(host=host, port=port)
        try:
            await client.connect()
            response = await client.send_and_recv(GetDiskVolume())
            if response and response.result:
                info = response.result
                click.echo("💾 Disk Volume:")
                click.echo("-" * 40)
                if 'freeMB' in info and 'totalMB' in info:
                    free_mb = info['freeMB']
                    total_mb = info['totalMB']
                    used_mb = total_mb - free_mb
                    used_percent = (used_mb / total_mb * 100) if total_mb > 0 else 0
                    click.echo(f"Free: {free_mb:,} MB")
                    click.echo(f"Total: {total_mb:,} MB")
                    click.echo(f"Used: {used_mb:,} MB ({used_percent:.1f}%)")
            await client.disconnect()
        except Exception as e:
            click.echo(f"❌ Error getting disk volume: {e}")
    
    asyncio.run(get_disk_volume())


@cli.command(name='get-time')
@click.option('--host', '-h', help='Telescope IP (uses saved connection if not provided)')
@click.option('--port', '-p', type=int, help='Port number')
@click.pass_context
def get_time(ctx, host, port):
    """Get current time from the telescope."""
    # Ensure context exists
    if not ctx.obj:
        ctx.obj = {}
    
    host = host or ctx.obj.get('host')
    port = port or ctx.obj.get('port', 4700)
    
    if not host:
        click.echo("❌ No telescope connection. Use 'connect' command first or provide --host")
        return
    
    from scopinator.seestar.client import SeestarClient
    from scopinator.seestar.commands.simple import GetTime
    
    async def get_telescope_time():
        client = SeestarClient(host=host, port=port)
        try:
            await client.connect()
            response = await client.send_and_recv(GetTime())
            if response and response.result:
                t = response.result
                click.echo("🕐 Telescope Time:")
                click.echo("-" * 40)
                if all(k in t for k in ['year', 'mon', 'day', 'hour', 'min', 'sec']):
                    click.echo(f"Date: {t['year']:04d}-{t['mon']:02d}-{t['day']:02d}")
                    click.echo(f"Time: {t['hour']:02d}:{t['min']:02d}:{t['sec']:02d}")
                if 'time_zone' in t:
                    click.echo(f"Timezone: {t['time_zone']}")
            await client.disconnect()
        except Exception as e:
            click.echo(f"❌ Error getting time: {e}")
    
    asyncio.run(get_telescope_time())


@cli.command(name='user-location')
@click.option('--host', '-h', help='Telescope IP (uses saved connection if not provided)')
@click.option('--port', '-p', type=int, help='Port number')
@click.pass_context
def user_location(ctx, host, port):
    """Get user location from the telescope."""
    # Ensure context exists
    if not ctx.obj:
        ctx.obj = {}
    
    host = host or ctx.obj.get('host')
    port = port or ctx.obj.get('port', 4700)
    
    if not host:
        click.echo("❌ No telescope connection. Use 'connect' command first or provide --host")
        return
    
    from scopinator.seestar.client import SeestarClient
    from scopinator.seestar.commands.simple import GetUserLocation
    
    async def get_user_location():
        client = SeestarClient(host=host, port=port)
        try:
            await client.connect()
            response = await client.send_and_recv(GetUserLocation())
            if response and response.result:
                location = response.result
                click.echo("📍 User Location:")
                click.echo("-" * 40)
                if 'lat' in location and 'lon' in location:
                    click.echo(f"Latitude: {location['lat']:.6f}°")
                    click.echo(f"Longitude: {location['lon']:.6f}°")
            await client.disconnect()
        except Exception as e:
            click.echo(f"❌ Error getting user location: {e}")
    
    asyncio.run(get_user_location())


@cli.command(name='focus-position')
@click.option('--host', '-h', help='Telescope IP (uses saved connection if not provided)')
@click.option('--port', '-p', type=int, help='Port number')
@click.pass_context
def focus_position(ctx, host, port):
    """Get current focuser position."""
    # Ensure context exists
    if not ctx.obj:
        ctx.obj = {}
    
    host = host or ctx.obj.get('host')
    port = port or ctx.obj.get('port', 4700)
    
    if not host:
        click.echo("❌ No telescope connection. Use 'connect' command first or provide --host")
        return
    
    from scopinator.seestar.client import SeestarClient
    from scopinator.seestar.commands.simple import GetFocuserPosition
    
    async def get_focus_position():
        client = SeestarClient(host=host, port=port)
        try:
            await client.connect()
            response = await client.send_and_recv(GetFocuserPosition())
            if response and response.result is not None:
                focus = response.result
                click.echo("🔍 Focuser Position:")
                click.echo("-" * 40)
                # Handle both integer response and dict response
                if isinstance(focus, (int, float)):
                    click.echo(f"Current Position: {focus}")
                elif isinstance(focus, dict):
                    if 'step' in focus:
                        click.echo(f"Current Position: {focus['step']}")
                    if 'max_step' in focus:
                        click.echo(f"Maximum Position: {focus['max_step']}")
                    if 'state' in focus:
                        click.echo(f"State: {focus['state']}")
                    if 'position' in focus:
                        click.echo(f"Current Position: {focus['position']}")
            await client.disconnect()
        except Exception as e:
            click.echo(f"❌ Error getting focus position: {e}")
    
    asyncio.run(get_focus_position())


@cli.command(name='coordinates')
@click.option('--host', '-h', help='Telescope IP (uses saved connection if not provided)')
@click.option('--port', '-p', type=int, help='Port number')
@click.option('--type', '-t', type=click.Choice(['equ', 'radec', 'horiz', 'all']), default='all', help='Coordinate type to get')
@click.pass_context
def coordinates(ctx, host, port, type):
    """Get telescope coordinates (equatorial, RA/Dec, or horizontal)."""
    # Ensure context exists
    if not ctx.obj:
        ctx.obj = {}
    
    host = host or ctx.obj.get('host')
    port = port or ctx.obj.get('port', 4700)
    
    if not host:
        click.echo("❌ No telescope connection. Use 'connect' command first or provide --host")
        return
    
    from scopinator.seestar.client import SeestarClient
    from scopinator.seestar.commands.simple import ScopeGetEquCoord, ScopeGetRaDecCoord, ScopeGetHorizCoord
    
    async def get_coordinates():
        client = SeestarClient(host=host, port=port)
        try:
            await client.connect()
            
            click.echo("📐 Telescope Coordinates:")
            click.echo("-" * 40)
            
            if type in ['equ', 'all']:
                response = await client.send_and_recv(ScopeGetEquCoord())
                if response and response.result:
                    coords = response.result
                    if 'ra' in coords and 'dec' in coords:
                        # RA is returned in hours, convert to degrees for display
                        ra_deg = coords['ra'] * 15.0
                        click.echo(f"Equatorial: RA={ra_deg:.4f}°, Dec={coords['dec']:.4f}°")
            
            if type in ['radec', 'all']:
                response = await client.send_and_recv(ScopeGetRaDecCoord())
                if response and response.result:
                    coords = response.result
                    if 'ra' in coords and 'dec' in coords:
                        click.echo(f"RA/Dec: RA={coords['ra']:.4f}, Dec={coords['dec']:.4f}")
            
            if type in ['horiz', 'all']:
                response = await client.send_and_recv(ScopeGetHorizCoord())
                if response and response.result:
                    coords = response.result
                    if 'az' in coords and 'alt' in coords:
                        click.echo(f"Horizontal: Az={coords['az']:.4f}°, Alt={coords['alt']:.4f}°")
            
            await client.disconnect()
        except Exception as e:
            click.echo(f"❌ Error getting coordinates: {e}")
    
    asyncio.run(get_coordinates())


@cli.command(name='start-autofocus')
@click.option('--host', '-h', help='Telescope IP (uses saved connection if not provided)')
@click.option('--port', '-p', type=int, help='Port number')
@click.pass_context
def start_autofocus(ctx, host, port):
    """Start automatic focusing."""
    # Ensure context exists
    if not ctx.obj:
        ctx.obj = {}
    
    host = host or ctx.obj.get('host')
    port = port or ctx.obj.get('port', 4700)
    
    if not host:
        click.echo("❌ No telescope connection. Use 'connect' command first or provide --host")
        return
    
    from scopinator.seestar.client import SeestarClient
    from scopinator.seestar.commands.simple import StartAutoFocus
    
    async def start_af():
        client = SeestarClient(host=host, port=port)
        try:
            await client.connect()
            click.echo("🔍 Starting autofocus...")
            response = await client.send_and_recv(StartAutoFocus())
            if response:
                click.echo("✅ Autofocus started")
            else:
                click.echo("⚠️ Autofocus command sent but no confirmation received")
            await client.disconnect()
        except Exception as e:
            click.echo(f"❌ Error starting autofocus: {e}")
    
    asyncio.run(start_af())


@cli.command(name='stop-autofocus')
@click.option('--host', '-h', help='Telescope IP (uses saved connection if not provided)')
@click.option('--port', '-p', type=int, help='Port number')
@click.pass_context
def stop_autofocus(ctx, host, port):
    """Stop automatic focusing."""
    # Ensure context exists
    if not ctx.obj:
        ctx.obj = {}
    
    host = host or ctx.obj.get('host')
    port = port or ctx.obj.get('port', 4700)
    
    if not host:
        click.echo("❌ No telescope connection. Use 'connect' command first or provide --host")
        return
    
    from scopinator.seestar.client import SeestarClient
    from scopinator.seestar.commands.simple import StopAutoFocus
    
    async def stop_af():
        client = SeestarClient(host=host, port=port)
        try:
            await client.connect()
            click.echo("🔍 Stopping autofocus...")
            response = await client.send_and_recv(StopAutoFocus())
            if response:
                click.echo("✅ Autofocus stopped")
            else:
                click.echo("⚠️ Stop autofocus command sent but no confirmation received")
            await client.disconnect()
        except Exception as e:
            click.echo(f"❌ Error stopping autofocus: {e}")
    
    asyncio.run(stop_af())


@cli.command(name='start-solve')
@click.option('--host', '-h', help='Telescope IP (uses saved connection if not provided)')
@click.option('--port', '-p', type=int, help='Port number')
@click.pass_context
def start_solve(ctx, host, port):
    """Start plate solving."""
    # Ensure context exists
    if not ctx.obj:
        ctx.obj = {}
    
    host = host or ctx.obj.get('host')
    port = port or ctx.obj.get('port', 4700)
    
    if not host:
        click.echo("❌ No telescope connection. Use 'connect' command first or provide --host")
        return
    
    from scopinator.seestar.client import SeestarClient
    from scopinator.seestar.commands.simple import StartSolve
    
    async def start_solving():
        client = SeestarClient(host=host, port=port)
        try:
            await client.connect()
            click.echo("🔭 Starting plate solve...")
            response = await client.send_and_recv(StartSolve())
            if response:
                click.echo("✅ Plate solving started")
            else:
                click.echo("⚠️ Solve command sent but no confirmation received")
            await client.disconnect()
        except Exception as e:
            click.echo(f"❌ Error starting solve: {e}")
    
    asyncio.run(start_solving())


@cli.command(name='solve-result')
@click.option('--host', '-h', help='Telescope IP (uses saved connection if not provided)')
@click.option('--port', '-p', type=int, help='Port number')
@click.option('--last', is_flag=True, help='Get last solve result instead of current')
@click.pass_context
def solve_result(ctx, host, port, last):
    """Get plate solve result."""
    # Ensure context exists
    if not ctx.obj:
        ctx.obj = {}
    
    host = host or ctx.obj.get('host')
    port = port or ctx.obj.get('port', 4700)
    
    if not host:
        click.echo("❌ No telescope connection. Use 'connect' command first or provide --host")
        return
    
    from scopinator.seestar.client import SeestarClient
    from scopinator.seestar.commands.simple import GetSolveResult, GetLastSolveResult
    
    async def get_solve_result():
        client = SeestarClient(host=host, port=port)
        try:
            await client.connect()
            command = GetLastSolveResult() if last else GetSolveResult()
            response = await client.send_and_recv(command)
            if response and response.result:
                result = response.result
                result_type = "Last Solve" if last else "Current Solve"
                click.echo(f"🔭 {result_type} Result:")
                click.echo("-" * 40)
                if 'ra' in result and 'dec' in result:
                    click.echo(f"Coordinates: RA={result['ra']:.4f}, Dec={result['dec']:.4f}")
                if 'pixel_scale' in result:
                    click.echo(f"Pixel Scale: {result['pixel_scale']:.2f} arcsec/pixel")
                if 'rotation' in result:
                    click.echo(f"Rotation: {result['rotation']:.2f}°")
                if 'success' in result:
                    status = "✅ Success" if result['success'] else "❌ Failed"
                    click.echo(f"Status: {status}")
            await client.disconnect()
        except Exception as e:
            click.echo(f"❌ Error getting solve result: {e}")
    
    asyncio.run(get_solve_result())


@cli.command(name='test-connection')
@click.option('--host', '-h', help='Telescope IP (uses saved connection if not provided)')
@click.option('--port', '-p', type=int, help='Port number')
@click.pass_context
def test_connection(ctx, host, port):
    """Test connection to the telescope."""
    # Ensure context exists
    if not ctx.obj:
        ctx.obj = {}
    
    host = host or ctx.obj.get('host')
    port = port or ctx.obj.get('port', 4700)
    
    if not host:
        click.echo("❌ No telescope connection. Use 'connect' command first or provide --host")
        return
    
    from scopinator.seestar.client import SeestarClient
    from scopinator.seestar.commands.simple import TestConnection
    
    async def test_conn():
        client = SeestarClient(host=host, port=port)
        try:
            await client.connect()
            click.echo(f"🔌 Testing connection to {host}:{port}...")
            response = await client.send_and_recv(TestConnection())
            if response:
                click.echo("✅ Connection test successful")
            else:
                click.echo("❌ Connection test failed")
            await client.disconnect()
        except Exception as e:
            click.echo(f"❌ Error testing connection: {e}")
    
    asyncio.run(test_conn())


@cli.command(name='camera-state')
@click.option('--host', '-h', help='Telescope IP (uses saved connection if not provided)')
@click.option('--port', '-p', type=int, help='Port number')
@click.pass_context
def camera_state(ctx, host, port):
    """Get current camera state."""
    # Ensure context exists
    if not ctx.obj:
        ctx.obj = {}
    
    host = host or ctx.obj.get('host')
    port = port or ctx.obj.get('port', 4700)
    
    if not host:
        click.echo("❌ No telescope connection. Use 'connect' command first or provide --host")
        return
    
    from scopinator.seestar.client import SeestarClient
    from scopinator.seestar.commands.simple import GetCameraState
    
    async def get_camera_state():
        client = SeestarClient(host=host, port=port)
        try:
            await client.connect()
            response = await client.send_and_recv(GetCameraState())
            if response and response.result:
                state = response.result
                click.echo("📷 Camera State:")
                click.echo("-" * 40)
                if 'state' in state:
                    click.echo(f"State: {state['state']}")
                if 'name' in state:
                    click.echo(f"Name: {state['name']}")
                if 'path' in state:
                    click.echo(f"Path: {state['path']}")
            await client.disconnect()
        except Exception as e:
            click.echo(f"❌ Error getting camera state: {e}")
    
    asyncio.run(get_camera_state())


@cli.command(name='device-state')
@click.option('--host', '-h', help='Telescope IP (uses saved connection if not provided)')
@click.option('--port', '-p', type=int, help='Port number')
@click.option('--keys', '-k', multiple=True, help='Specific keys to retrieve (e.g., device, pi_status, mount)')
@click.option('--all', 'show_all', is_flag=True, help='Show all available data without filtering')
@click.option('--json', 'as_json', is_flag=True, help='Output raw JSON data')
@click.pass_context
def device_state(ctx, host, port, keys, show_all, as_json):
    """Get comprehensive device state information."""
    # Ensure context exists
    if not ctx.obj:
        ctx.obj = {}
    
    host = host or ctx.obj.get('host')
    port = port or ctx.obj.get('port', 4700)
    
    if not host:
        click.echo("❌ No telescope connection. Use 'connect' command first or provide --host")
        return
    
    from scopinator.seestar.client import SeestarClient
    from scopinator.seestar.commands.simple import GetDeviceState
    
    async def get_device_state():
        client = SeestarClient(host=host, port=port)
        try:
            await client.connect()
            # If specific keys requested, use them
            if keys:
                cmd = GetDeviceState(params={"keys": list(keys)})
            else:
                cmd = GetDeviceState()
            
            response = await client.send_and_recv(cmd)
            if response and response.result:
                state = response.result
                
                # Output as JSON if requested
                if as_json:
                    click.echo(json.dumps(state, indent=2))
                    await client.disconnect()
                    return
                click.echo("📱 Device State:")
                click.echo("-" * 40)
                
                # Show device info if present
                if 'device' in state:
                    dev = state['device']
                    click.echo("\n🔭 Device:")
                    if 'name' in dev:
                        click.echo(f"  Name: {dev['name']}")
                    if 'firmware_ver_string' in dev:
                        click.echo(f"  Firmware: {dev['firmware_ver_string']}")
                    if 'sn' in dev:
                        click.echo(f"  Serial: {dev['sn']}")
                    if 'product_model' in dev:
                        click.echo(f"  Model: {dev['product_model']}")
                
                # Show pi_status if present
                if 'pi_status' in state:
                    pi = state['pi_status']
                    click.echo("\n⚡ Status:")
                    if 'battery_capacity' in pi:
                        click.echo(f"  Battery: {pi['battery_capacity']}%")
                    if 'temp' in pi:
                        click.echo(f"  Temperature: {pi['temp']}°C")
                    if 'charger_status' in pi:
                        click.echo(f"  Charger: {pi['charger_status']}")
                
                # Show mount if present
                if 'mount' in state:
                    mount = state['mount']
                    click.echo("\n🎯 Mount:")
                    if 'tracking' in mount:
                        click.echo(f"  Tracking: {'Yes' if mount['tracking'] else 'No'}")
                    if 'equ_mode' in mount:
                        click.echo(f"  Equatorial Mode: {'Yes' if mount['equ_mode'] else 'No'}")
                
                # Show focuser if present
                if 'focuser' in state:
                    focuser = state['focuser']
                    click.echo("\n🔍 Focuser:")
                    if 'step' in focuser:
                        click.echo(f"  Position: {focuser['step']}")
                    if 'max_step' in focuser:
                        click.echo(f"  Max Position: {focuser['max_step']}")
                    if 'state' in focuser:
                        click.echo(f"  State: {focuser['state']}")
                
                # Show storage if present
                if 'storage' in state:
                    storage = state['storage']
                    click.echo("\n💾 Storage:")
                    if 'cur_storage' in storage:
                        click.echo(f"  Current: {storage['cur_storage']}")
                    if 'storage_volume' in storage:
                        for vol in storage['storage_volume']:
                            if 'name' in vol:
                                click.echo(f"  {vol['name']}: {vol.get('freeMB', 0):,} MB free")
                
                # Show all data if requested
                if show_all:
                    click.echo("\n📋 All Device State Data:")
                    click.echo("-" * 40)
                    
                    # Show any sections not already displayed
                    shown_keys = {'device', 'pi_status', 'mount', 'focuser', 'storage'}
                    for key in sorted(state.keys()):
                        if key not in shown_keys:
                            click.echo(f"\n{key}:")
                            value = state[key]
                            if isinstance(value, dict):
                                for k, v in value.items():
                                    click.echo(f"  {k}: {v}")
                            elif isinstance(value, list):
                                for i, item in enumerate(value):
                                    if isinstance(item, dict):
                                        click.echo(f"  [{i}]:")
                                        for k, v in item.items():
                                            click.echo(f"    {k}: {v}")
                                    else:
                                        click.echo(f"  [{i}]: {item}")
                            else:
                                click.echo(f"  {value}")
                else:
                    # Show any other keys
                    shown_keys = {'device', 'pi_status', 'mount', 'focuser', 'storage'}
                    other_keys = set(state.keys()) - shown_keys
                    if other_keys:
                        click.echo(f"\n📊 Other data available: {', '.join(sorted(other_keys))}")
                        click.echo("  Use --keys to retrieve specific sections or --all to see everything")
                    
            await client.disconnect()
        except Exception as e:
            click.echo(f"❌ Error getting device state: {e}")
    
    asyncio.run(get_device_state())


@cli.command(name='get-setting')
@click.option('--host', '-h', help='Telescope IP (uses saved connection if not provided)')
@click.option('--port', '-p', type=int, help='Port number')
@click.option('--all', 'show_all', is_flag=True, help='Show all settings with raw values')
@click.option('--json', 'as_json', is_flag=True, help='Output raw JSON data')
@click.pass_context
def get_setting(ctx, host, port, show_all, as_json):
    """Get telescope settings."""
    # Ensure context exists
    if not ctx.obj:
        ctx.obj = {}
    
    host = host or ctx.obj.get('host')
    port = port or ctx.obj.get('port', 4700)
    
    if not host:
        click.echo("❌ No telescope connection. Use 'connect' command first or provide --host")
        return
    
    from scopinator.seestar.client import SeestarClient
    from scopinator.seestar.commands.simple import GetSetting
    
    async def get_settings():
        client = SeestarClient(host=host, port=port)
        try:
            await client.connect()
            response = await client.send_and_recv(GetSetting())
            if response and response.result:
                settings = response.result
                
                # Output as JSON if requested
                if as_json:
                    click.echo(json.dumps(settings, indent=2))
                    await client.disconnect()
                    return
                click.echo("⚙️ Telescope Settings:")
                click.echo("-" * 40)
                
                # Display settings in organized groups
                if 'lang' in settings:
                    click.echo(f"Language: {settings['lang']}")
                if 'temp_unit' in settings:
                    click.echo(f"Temperature Unit: {settings['temp_unit']}")
                if 'beep_volume' in settings:
                    click.echo(f"Beep Volume: {settings['beep_volume']}")
                
                # Auto settings
                click.echo("\n🔄 Auto Settings:")
                if 'auto_power_off' in settings:
                    click.echo(f"  Auto Power Off: {'Enabled' if settings['auto_power_off'] else 'Disabled'}")
                if 'auto_af' in settings:
                    click.echo(f"  Auto Focus: {'Enabled' if settings['auto_af'] else 'Disabled'}")
                if 'auto_3ppa_calib' in settings:
                    click.echo(f"  Auto 3PPA Calibration: {'Enabled' if settings['auto_3ppa_calib'] else 'Disabled'}")
                
                # Stack settings
                if 'stack_lenhance' in settings:
                    click.echo("\n📸 Stack Settings:")
                    click.echo(f"  Light Enhancement: {'Enabled' if settings['stack_lenhance'] else 'Disabled'}")
                if 'stack_after_goto' in settings:
                    click.echo(f"  Stack After Goto: {'Enabled' if settings['stack_after_goto'] else 'Disabled'}")
                
                # Heater settings
                if 'heater_enable' in settings:
                    click.echo("\n🌡️ Heater Settings:")
                    click.echo(f"  Heater: {'Enabled' if settings['heater_enable'] else 'Disabled'}")
                if 'expt_heater_enable' in settings:
                    click.echo(f"  Expert Heater: {'Enabled' if settings['expt_heater_enable'] else 'Disabled'}")
                
                # Other settings
                if 'focal_pos' in settings:
                    click.echo(f"\n🔍 Focal Position: {settings['focal_pos']}")
                if 'factory_focal_pos' in settings:
                    click.echo(f"Factory Focal Position: {settings['factory_focal_pos']}")
                
                # Show all settings if requested
                if show_all:
                    click.echo("\n📋 All Settings (raw values):")
                    click.echo("-" * 40)
                    for key, value in sorted(settings.items()):
                        # Format the value based on type
                        if isinstance(value, bool):
                            value_str = "Enabled" if value else "Disabled"
                        elif isinstance(value, dict):
                            value_str = str(value)
                        elif isinstance(value, list):
                            value_str = str(value)
                        else:
                            value_str = str(value)
                        click.echo(f"  {key}: {value_str}")
                else:
                    # Show count of total settings
                    click.echo(f"\n📊 Total settings available: {len(settings)}")
                    click.echo("   Use --all to see all raw values")
                    
            await client.disconnect()
        except Exception as e:
            click.echo(f"❌ Error getting settings: {e}")
    
    asyncio.run(get_settings())


@cli.command(name='view-state')
@click.option('--host', '-h', help='Telescope IP (uses saved connection if not provided)')
@click.option('--port', '-p', type=int, help='Port number')
@click.option('--json', 'as_json', is_flag=True, help='Output raw JSON data')
@click.pass_context
def view_state(ctx, host, port, as_json):
    """Get current view state."""
    # Ensure context exists
    if not ctx.obj:
        ctx.obj = {}
    
    host = host or ctx.obj.get('host')
    port = port or ctx.obj.get('port', 4700)
    
    if not host:
        click.echo("❌ No telescope connection. Use 'connect' command first or provide --host")
        return
    
    from scopinator.seestar.client import SeestarClient
    from scopinator.seestar.commands.simple import GetViewState
    
    async def get_view_state():
        client = SeestarClient(host=host, port=port)
        try:
            await client.connect()
            response = await client.send_and_recv(GetViewState())
            if response and response.result:
                state = response.result
                
                # Output as JSON if requested
                if as_json:
                    click.echo(json.dumps(state, indent=2))
                else:
                    click.echo("👁️ View State:")
                    click.echo("-" * 40)
                    
                    # Handle nested View structure
                    if 'View' in state:
                        view = state['View']
                        if 'state' in view:
                            click.echo(f"State: {view['state']}")
                        if 'stage' in view:
                            click.echo(f"Stage: {view['stage']}")
                        if 'target_name' in view:
                            click.echo(f"Target: {view['target_name']}")
                        if 'target_ra_dec' in view:
                            ra, dec = view['target_ra_dec']
                            click.echo(f"Coordinates: RA={ra:.4f}, Dec={dec:.4f}")
                        if 'mode' in view:
                            click.echo(f"Mode: {view['mode']}")
                        if 'target_type' in view:
                            click.echo(f"Target Type: {view['target_type']}")
                        if 'lp_filter' in view:
                            click.echo(f"LP Filter: {'Yes' if view['lp_filter'] else 'No'}")
                        if 'lapse_ms' in view:
                            lapse_sec = view['lapse_ms'] / 1000
                            click.echo(f"Elapsed Time: {lapse_sec:.1f} seconds")
                        
                        # Show RTSP info if present
                        if 'RTSP' in view:
                            rtsp = view['RTSP']
                            click.echo("\nRTSP Stream:")
                            if 'state' in rtsp:
                                click.echo(f"  State: {rtsp['state']}")
                            if 'port' in rtsp:
                                click.echo(f"  Port: {rtsp['port']}")
                    else:
                        # Fallback for flat structure
                        if 'view_state' in state:
                            click.echo(f"State: {state['view_state']}")
                        if 'stage' in state:
                            click.echo(f"Stage: {state['stage']}")
                        if 'target_name' in state:
                            click.echo(f"Target: {state['target_name']}")
                        if 'ra' in state and 'dec' in state:
                            click.echo(f"Coordinates: RA={state['ra']:.4f}, Dec={state['dec']:.4f}")
                        if 'mode' in state:
                            click.echo(f"Mode: {state['mode']}")
            await client.disconnect()
        except Exception as e:
            click.echo(f"❌ Error getting view state: {e}")
    
    asyncio.run(get_view_state())


@cli.command(name='stack-info')
@click.option('--host', '-h', help='Telescope IP (uses saved connection if not provided)')
@click.option('--port', '-p', type=int, help='Port number')
@click.option('--json', 'as_json', is_flag=True, help='Output raw JSON data')
@click.pass_context
def stack_info(ctx, host, port, as_json):
    """Get stack information."""
    # Ensure context exists
    if not ctx.obj:
        ctx.obj = {}
    
    host = host or ctx.obj.get('host')
    port = port or ctx.obj.get('port', 4700)
    
    if not host:
        click.echo("❌ No telescope connection. Use 'connect' command first or provide --host")
        return
    
    from scopinator.seestar.client import SeestarClient
    from scopinator.seestar.commands.simple import GetStackInfo
    
    async def get_stack_info():
        client = SeestarClient(host=host, port=port)
        try:
            await client.connect()
            response = await client.send_and_recv(GetStackInfo())
            if response and response.result:
                info = response.result
                
                # Output as JSON if requested
                if as_json:
                    click.echo(json.dumps(info, indent=2))
                else:
                    click.echo("📚 Stack Information:")
                    click.echo("-" * 40)
                    if 'stacked_frame' in info:
                        click.echo(f"Stacked Frames: {info['stacked_frame']}")
                    if 'dropped_frame' in info:
                        click.echo(f"Dropped Frames: {info['dropped_frame']}")
                    if 'total_exp_time' in info:
                        click.echo(f"Total Exposure Time: {info['total_exp_time']} ms")
                    if 'stack_count' in info:
                        click.echo(f"Stack Count: {info['stack_count']}")
                    
                    # Show all other fields
                    shown_keys = {'stacked_frame', 'dropped_frame', 'total_exp_time', 'stack_count'}
                    for key in sorted(info.keys()):
                        if key not in shown_keys:
                            click.echo(f"{key}: {info[key]}")
            await client.disconnect()
        except Exception as e:
            click.echo(f"❌ Error getting stack info: {e}")
    
    asyncio.run(get_stack_info())


@cli.command(name='stack-setting')
@click.option('--host', '-h', help='Telescope IP (uses saved connection if not provided)')
@click.option('--port', '-p', type=int, help='Port number')
@click.option('--json', 'as_json', is_flag=True, help='Output raw JSON data')
@click.pass_context
def stack_setting(ctx, host, port, as_json):
    """Get stack settings."""
    # Ensure context exists
    if not ctx.obj:
        ctx.obj = {}
    
    host = host or ctx.obj.get('host')
    port = port or ctx.obj.get('port', 4700)
    
    if not host:
        click.echo("❌ No telescope connection. Use 'connect' command first or provide --host")
        return
    
    from scopinator.seestar.client import SeestarClient
    from scopinator.seestar.commands.simple import GetStackSetting
    
    async def get_stack_setting():
        client = SeestarClient(host=host, port=port)
        try:
            await client.connect()
            response = await client.send_and_recv(GetStackSetting())
            if response and response.result:
                settings = response.result
                
                # Output as JSON if requested
                if as_json:
                    click.echo(json.dumps(settings, indent=2))
                else:
                    click.echo("📸 Stack Settings:")
                    click.echo("-" * 40)
                    for key, value in sorted(settings.items()):
                        if isinstance(value, bool):
                            value_str = "Enabled" if value else "Disabled"
                        else:
                            value_str = str(value)
                        click.echo(f"{key}: {value_str}")
            await client.disconnect()
        except Exception as e:
            click.echo(f"❌ Error getting stack settings: {e}")
    
    asyncio.run(get_stack_setting())


@cli.command(name='wheel-state')
@click.option('--host', '-h', help='Telescope IP (uses saved connection if not provided)')
@click.option('--port', '-p', type=int, help='Port number')
@click.option('--json', 'as_json', is_flag=True, help='Output raw JSON data')
@click.pass_context
def wheel_state(ctx, host, port, as_json):
    """Get filter wheel state."""
    # Ensure context exists
    if not ctx.obj:
        ctx.obj = {}
    
    host = host or ctx.obj.get('host')
    port = port or ctx.obj.get('port', 4700)
    
    if not host:
        click.echo("❌ No telescope connection. Use 'connect' command first or provide --host")
        return
    
    from scopinator.seestar.client import SeestarClient
    from scopinator.seestar.commands.simple import GetWheelState
    
    async def get_wheel_state():
        client = SeestarClient(host=host, port=port)
        try:
            await client.connect()
            response = await client.send_and_recv(GetWheelState())
            if response and response.result:
                state = response.result
                
                # Output as JSON if requested
                if as_json:
                    click.echo(json.dumps(state, indent=2))
                else:
                    click.echo("☸️ Filter Wheel State:")
                    click.echo("-" * 40)
                    if 'state' in state:
                        click.echo(f"State: {state['state']}")
                    if 'position' in state:
                        click.echo(f"Position: {state['position']}")
                    if 'filter' in state:
                        click.echo(f"Current Filter: {state['filter']}")
                    
                    # Show all other fields
                    shown_keys = {'state', 'position', 'filter'}
                    for key in sorted(state.keys()):
                        if key not in shown_keys:
                            click.echo(f"{key}: {state[key]}")
            await client.disconnect()
        except Exception as e:
            click.echo(f"❌ Error getting wheel state: {e}")
    
    asyncio.run(get_wheel_state())


@cli.command(name='wheel-position')
@click.option('--host', '-h', help='Telescope IP (uses saved connection if not provided)')
@click.option('--port', '-p', type=int, help='Port number')
@click.option('--json', 'as_json', is_flag=True, help='Output raw JSON data')
@click.pass_context
def wheel_position(ctx, host, port, as_json):
    """Get filter wheel position."""
    # Ensure context exists
    if not ctx.obj:
        ctx.obj = {}
    
    host = host or ctx.obj.get('host')
    port = port or ctx.obj.get('port', 4700)
    
    if not host:
        click.echo("❌ No telescope connection. Use 'connect' command first or provide --host")
        return
    
    from scopinator.seestar.client import SeestarClient
    from scopinator.seestar.commands.simple import GetWheelPosition
    
    async def get_wheel_position():
        client = SeestarClient(host=host, port=port)
        try:
            await client.connect()
            response = await client.send_and_recv(GetWheelPosition())
            if response and response.result is not None:
                position = response.result
                
                # Output as JSON if requested
                if as_json:
                    click.echo(json.dumps({"position": position}, indent=2))
                else:
                    click.echo("☸️ Filter Wheel Position:")
                    click.echo("-" * 40)
                    # Handle both integer response and dict response
                    if isinstance(position, (int, float)):
                        click.echo(f"Current Position: {position}")
                    elif isinstance(position, dict):
                        for key, value in position.items():
                            click.echo(f"{key}: {value}")
            await client.disconnect()
        except Exception as e:
            click.echo(f"❌ Error getting wheel position: {e}")
    
    asyncio.run(get_wheel_position())


@cli.command(name='wheel-setting')
@click.option('--host', '-h', help='Telescope IP (uses saved connection if not provided)')
@click.option('--port', '-p', type=int, help='Port number')
@click.option('--json', 'as_json', is_flag=True, help='Output raw JSON data')
@click.pass_context
def wheel_setting(ctx, host, port, as_json):
    """Get filter wheel settings."""
    # Ensure context exists
    if not ctx.obj:
        ctx.obj = {}
    
    host = host or ctx.obj.get('host')
    port = port or ctx.obj.get('port', 4700)
    
    if not host:
        click.echo("❌ No telescope connection. Use 'connect' command first or provide --host")
        return
    
    from scopinator.seestar.client import SeestarClient
    from scopinator.seestar.commands.simple import GetWheelSetting
    
    async def get_wheel_setting():
        client = SeestarClient(host=host, port=port)
        try:
            await client.connect()
            response = await client.send_and_recv(GetWheelSetting())
            if response and response.result:
                settings = response.result
                
                # Output as JSON if requested
                if as_json:
                    click.echo(json.dumps(settings, indent=2))
                else:
                    click.echo("☸️ Filter Wheel Settings:")
                    click.echo("-" * 40)
                    for key, value in sorted(settings.items()):
                        if isinstance(value, bool):
                            value_str = "Enabled" if value else "Disabled"
                        else:
                            value_str = str(value)
                        click.echo(f"{key}: {value_str}")
            await client.disconnect()
        except Exception as e:
            click.echo(f"❌ Error getting wheel settings: {e}")
    
    asyncio.run(get_wheel_setting())


@cli.command(name='capture-video')
@click.option('--host', '-h', help='Telescope IP (uses saved connection if not provided)')
@click.option('--port', '-p', type=int, help='Port number')
@click.option('--duration', '-d', type=float, help='Duration in seconds to capture')
@click.option('--frames', '-f', type=int, help='Number of frames to capture')
@click.option('--output', '-o', help='Output file path (MP4 format). If not specified, uses temp file')
@click.option('--fps', type=int, default=30, help='Frames per second for output video (default: 30)')
@click.option('--rtsp-port', type=int, default=4554, help='RTSP port (default: 4554)')
@click.option('--force-rtsp', is_flag=True, help='Force use of RTSP even if in Stack/ContinuousExposure mode')
@click.pass_context
def capture_video(ctx, host, port, duration, frames, output, fps, rtsp_port, force_rtsp):
    """Capture video stream from the telescope.
    
    Specify either --duration OR --frames, not both.
    If no output file is specified, a temporary file will be created.
    
    The command automatically detects the imaging mode:
    - In Stack/ContinuousExposure mode: captures frames from the imaging system
    - In other modes or with --force-rtsp: captures directly from RTSP stream
    """
    # Ensure context exists
    if not ctx.obj:
        ctx.obj = {}
    
    host = host or ctx.obj.get('host')
    port = port or ctx.obj.get('port', 4700)
    
    if not host:
        click.echo("❌ No telescope connection. Use 'connect' command first or provide --host")
        return
    
    if duration and frames:
        click.echo("❌ Please specify either --duration or --frames, not both")
        return
    
    if not duration and not frames:
        click.echo("❌ Please specify either --duration or --frames")
        return
    
    from pathlib import Path
    import cv2
    from datetime import datetime
    
    from scopinator.seestar.rtspclient import RtspClient
    from scopinator.seestar.imaging_client import SeestarImagingClient
    
    # Generate output filename if not provided
    if not output:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output = f"scopinator_capture_{timestamp}.mp4"
        click.echo(f"📹 Using output file: {output}")
    
    output_path = Path(output)
    
    async def capture_from_imaging_client():
        """Capture frames from the imaging client when in Stack/ContinuousExposure mode."""
        client = SeestarImagingClient(host=host, port=4800)  # Imaging client uses port 4800
        writer = None
        frames_written = 0
        
        try:
            await client.connect()
            click.echo(f"✅ Connected to imaging client at {host}:4800")
            click.echo(f"📷 Client mode: {client.client_mode}")
            
            # Initialize video writer
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            
            # Start capture
            if duration:
                click.echo(f"🎬 Recording for {duration} seconds at {fps} fps...")
                target_frames = int(duration * fps)
            else:
                click.echo(f"🎬 Recording {frames} frames at {fps} fps...")
                target_frames = frames
            
            start_time = asyncio.get_event_loop().time()
            last_progress = 0
            last_frame_time = start_time
            frame_interval = 1.0 / fps
            
            # Start fetching images
            async for image in client.get_next_image(camera_id=0):
                if image and image.image is not None:
                    # Initialize writer with first frame dimensions
                    if writer is None:
                        height, width = image.image.shape[:2]
                        writer = cv2.VideoWriter(str(output_path), fourcc, fps, (width, height))
                        if not writer.isOpened():
                            click.echo("❌ Failed to open video writer")
                            return
                    
                    # Convert RGB to BGR for OpenCV (image is already in RGB from imaging client)
                    if len(image.image.shape) == 3:
                        bgr_frame = cv2.cvtColor(image.image, cv2.COLOR_RGB2BGR)
                    else:
                        # Grayscale image
                        bgr_frame = cv2.cvtColor(image.image, cv2.COLOR_GRAY2BGR)
                    
                    writer.write(bgr_frame)
                    frames_written += 1
                    
                    # Show progress every 10%
                    progress = int((frames_written / target_frames) * 10) * 10
                    if progress > last_progress:
                        click.echo(f"   Progress: {progress}% ({frames_written}/{target_frames} frames)")
                        click.echo(f"   Stacked: {client.status.stacked_frame}, Dropped: {client.status.dropped_frame}")
                        last_progress = progress
                    
                    # Check if we've captured enough frames
                    if frames_written >= target_frames:
                        break
                    
                    # Control frame rate
                    current_time = asyncio.get_event_loop().time()
                    time_to_wait = frame_interval - (current_time - last_frame_time)
                    if time_to_wait > 0:
                        await asyncio.sleep(time_to_wait)
                    last_frame_time = current_time
            
            elapsed = asyncio.get_event_loop().time() - start_time
            
            click.echo("✅ Recording complete!")
            click.echo(f"   Duration: {elapsed:.1f} seconds")
            click.echo(f"   Frames captured: {frames_written}")
            click.echo(f"   Output file: {output_path.absolute()}")
            if output_path.exists():
                click.echo(f"   File size: {output_path.stat().st_size / 1024 / 1024:.1f} MB")
            
            await client.disconnect()
            
        except Exception as e:
            click.echo(f"❌ Error capturing from imaging client: {e}")
            import traceback
            traceback.print_exc()
        finally:
            if writer is not None:
                writer.release()
    
    async def capture_from_rtsp():
        """Capture directly from RTSP stream."""
        try:
            # Setup RTSP client
            rtsp_url = f"rtsp://{host}:{rtsp_port}/stream"
            click.echo(f"📡 Connecting to RTSP stream at {rtsp_url}...")
            
            # Initialize video writer
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            writer = None
            frames_written = 0
            
            with RtspClient(rtsp_url) as rtsp_client:
                # Wait for stream to open
                await rtsp_client.finish_opening()
                
                if not rtsp_client.is_opened():
                    click.echo("❌ Failed to open RTSP stream")
                    return
                
                click.echo("✅ Connected to RTSP stream")
                
                # Get first frame to determine dimensions
                first_frame = None
                while first_frame is None and rtsp_client.is_opened():
                    first_frame = rtsp_client.read()
                    if first_frame is None:
                        await asyncio.sleep(0.1)
                
                if first_frame is None:
                    click.echo("❌ Could not read frame from stream")
                    return
                
                height, width = first_frame.shape[:2]
                writer = cv2.VideoWriter(str(output_path), fourcc, fps, (width, height))
                
                if not writer.isOpened():
                    click.echo("❌ Failed to open video writer")
                    return
                
                # Write first frame
                # Convert RGB back to BGR for OpenCV
                bgr_frame = cv2.cvtColor(first_frame, cv2.COLOR_RGB2BGR)
                writer.write(bgr_frame)
                frames_written += 1
                
                # Start capture
                if duration:
                    click.echo(f"🎬 Recording for {duration} seconds at {fps} fps...")
                    target_frames = int(duration * fps)
                else:
                    click.echo(f"🎬 Recording {frames} frames at {fps} fps...")
                    target_frames = frames
                
                start_time = asyncio.get_event_loop().time()
                last_progress = 0
                
                while rtsp_client.is_opened() and frames_written < target_frames:
                    frame = rtsp_client.read()
                    if frame is not None:
                        # Convert RGB to BGR for OpenCV
                        bgr_frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                        writer.write(bgr_frame)
                        frames_written += 1
                        
                        # Show progress every 10%
                        progress = int((frames_written / target_frames) * 10) * 10
                        if progress > last_progress:
                            click.echo(f"   Progress: {progress}% ({frames_written}/{target_frames} frames)")
                            last_progress = progress
                    
                    # Control frame rate
                    await asyncio.sleep(1.0 / fps)
                
                elapsed = asyncio.get_event_loop().time() - start_time
                
                click.echo("✅ Recording complete!")
                click.echo(f"   Duration: {elapsed:.1f} seconds")
                click.echo(f"   Frames captured: {frames_written}")
                click.echo(f"   Output file: {output_path.absolute()}")
                if output_path.exists():
                    click.echo(f"   File size: {output_path.stat().st_size / 1024 / 1024:.1f} MB")
                
        except Exception as e:
            click.echo(f"❌ Error capturing from RTSP: {e}")
            import traceback
            traceback.print_exc()
        finally:
            if writer is not None:
                writer.release()
    
    async def capture_video_stream():
        """Main capture function that determines which method to use."""
        if not force_rtsp:
            # Try to connect with imaging client first to check mode
            client = SeestarImagingClient(host=host, port=4800)  # Imaging client uses port 4800
            try:
                await client.connect()
                mode = client.client_mode
                await client.disconnect()
                
                if mode in ["Stack", "ContinuousExposure"]:
                    click.echo(f"🔍 Detected {mode} mode - using imaging client for capture")
                    await capture_from_imaging_client()
                else:
                    click.echo(f"🔍 Detected {mode or 'Idle'} mode - using RTSP stream for capture")
                    await capture_from_rtsp()
            except Exception as e:
                click.echo(f"⚠️ Could not detect imaging mode: {e}")
                click.echo("📡 Falling back to RTSP stream")
                await capture_from_rtsp()
        else:
            click.echo("📡 Using RTSP stream (forced)")
            await capture_from_rtsp()
    
    asyncio.run(capture_video_stream())


@cli.command(name='monitor')
@click.option('--host', '-h', help='Telescope IP (uses saved connection if not provided)')
@click.option('--port', '-p', type=int, help='Port number')
@click.option('--timeout', '-t', type=float, help='Timeout in seconds (default: continuous monitoring)')
@click.option('--count', '-c', type=int, help='Number of messages to capture before stopping')
@click.option('--json', 'as_json', is_flag=True, help='Output raw JSON messages')
@click.option('--pretty', is_flag=True, help='Pretty print JSON messages (default when not using --json)')
@click.option('--include', '-i', multiple=True, help='Include only these event types (can be used multiple times)')
@click.option('--exclude', '-e', multiple=True, help='Exclude these event types (can be used multiple times)')
@click.option('--exec', 'exec_commands', multiple=True, help='Execute command after connecting (can be used multiple times)')
@click.option('--exec-delay', type=float, default=1.0, help='Delay in seconds before executing commands (default: 1.0)')
@click.pass_context
def monitor(ctx, host, port, timeout, count, as_json, pretty, include, exclude, exec_commands, exec_delay):
    """Monitor all incoming messages from the telescope.
    
    Keeps the connection open and displays all messages received from the telescope.
    By default, pretty-prints the messages. Use --json for raw JSON output.
    
    Event Filtering:
        Use --include/-i to show only specific event types
        Use --exclude/-e to hide specific event types
        Common event types: PiStatus, Stack, Annotate, FocuserMove, View, AutoGoto
    
    Command Execution:
        Use --exec to run commands after connecting (can be used multiple times)
        Available commands: status, park, autofocus-start, autofocus-stop, solve-start, 
                          goto:<ra>,<dec>, focus:<position>, test-connection
    
    Examples:
        scopinator monitor --host 192.168.1.100              # Monitor continuously
        scopinator monitor --timeout 30                      # Monitor for 30 seconds  
        scopinator monitor --count 10                        # Capture 10 messages
        scopinator monitor --json                            # Output raw JSON
        scopinator monitor -i Stack -i Annotate              # Only show Stack and Annotate events
        scopinator monitor -e PiStatus                       # Hide PiStatus events
        scopinator monitor --exec status --exec autofocus-start  # Run commands after connecting
        scopinator monitor --exec "goto:180.5,45.2"          # Go to coordinates then monitor
    """
    # Ensure context exists
    if not ctx.obj:
        ctx.obj = {}
    
    host = host or ctx.obj.get('host')
    port = port or ctx.obj.get('port', 4700)
    
    if not host:
        click.echo("❌ No telescope connection. Use 'connect' command first or provide --host")
        return
    
    from scopinator.seestar.client import SeestarClient
    from scopinator.seestar.commands.responses import TelescopeMessageParser
    import time
    
    async def execute_command(client, command: str):
        """Execute a command on the connected client."""
        click.echo(f"⚡ Executing: {command}")
        
        try:
            # Parse and execute different command types
            if command == "status":
                from scopinator.seestar.commands.simple import GetDeviceState
                response = await client.send_and_recv(GetDeviceState())
                if response and response.result:
                    click.echo("   ✅ Status retrieved")
            elif command == "park":
                from scopinator.seestar.commands.simple import ScopePark
                response = await client.send_and_recv(ScopePark())
                click.echo("   ✅ Park command sent")
            elif command == "autofocus-start":
                from scopinator.seestar.commands.simple import StartAutoFocus
                response = await client.send_and_recv(StartAutoFocus())
                click.echo("   ✅ Autofocus started")
            elif command == "autofocus-stop":
                from scopinator.seestar.commands.simple import StopAutoFocus
                response = await client.send_and_recv(StopAutoFocus())
                click.echo("   ✅ Autofocus stopped")
            elif command == "solve-start":
                from scopinator.seestar.commands.simple import StartSolve
                response = await client.send_and_recv(StartSolve())
                click.echo("   ✅ Plate solve started")
            elif command.startswith("goto:"):
                # Parse goto coordinates
                coords = command[5:].split(',')
                if len(coords) == 2:
                    ra = float(coords[0].strip())
                    dec = float(coords[1].strip())
                    from scopinator.seestar.commands.parameterized import GotoTarget
                    response = await client.send_and_recv(GotoTarget(ra=ra, dec=dec))
                    click.echo(f"   ✅ Goto RA={ra}, Dec={dec} initiated")
                else:
                    click.echo(f"   ❌ Invalid goto format. Use: goto:RA,DEC")
            elif command.startswith("focus:"):
                # Parse focus position
                position = int(command[6:].strip())
                from scopinator.seestar.commands.parameterized import MoveFocuser, MoveFocuserParameters
                response = await client.send_and_recv(MoveFocuser(params=MoveFocuserParameters(step=position)))
                click.echo(f"   ✅ Focus position set to {position}")
            elif command == "test-connection":
                from scopinator.seestar.commands.simple import TestConnection
                response = await client.send_and_recv(TestConnection())
                click.echo("   ✅ Connection test successful")
            else:
                click.echo(f"   ❌ Unknown command: {command}")
        except Exception as e:
            click.echo(f"   ❌ Error executing {command}: {e}")
    
    async def monitor_messages():
        client = SeestarClient(host=host, port=port)
        last_processed_index = 0  # Track the last processed message index
        messages_displayed = 0    # Count of messages actually displayed
        messages_filtered = 0     # Count of filtered messages
        start_time = time.time()
        end_time = start_time + timeout if timeout else None
        
        # Convert filter lists to sets for faster lookup
        include_set = set(include) if include else None
        exclude_set = set(exclude) if exclude else set()
        
        try:
            await client.connect()
            click.echo(f"🔭 Connected to telescope at {host}:{port}")
            
            # Execute commands if provided
            if exec_commands:
                click.echo(f"⏳ Waiting {exec_delay} seconds before executing commands...")
                await asyncio.sleep(exec_delay)
                click.echo("🚀 Executing commands:")
                for cmd in exec_commands:
                    await execute_command(client, cmd)
                click.echo("-" * 60)
            
            click.echo("📡 Monitoring messages...")
            
            if timeout:
                click.echo(f"   Timeout: {timeout} seconds")
            if count:
                click.echo(f"   Message limit: {count}")
            if include_set:
                click.echo(f"   Including only: {', '.join(include)}")
            if exclude_set:
                click.echo(f"   Excluding: {', '.join(exclude)}")
            click.echo(f"   Output format: {'JSON' if as_json else 'Pretty print'}")
            click.echo("-" * 60)
            
            # Clear existing message history
            client.message_history.clear()
            
            while client.is_connected:
                # Check if we should stop
                if end_time and time.time() >= end_time:
                    click.echo(f"\n⏱️ Timeout reached ({timeout} seconds)")
                    break
                    
                if count and messages_displayed >= count:
                    click.echo(f"\n✅ Captured {count} messages")
                    break
                
                # Check for new messages  
                current_history_size = len(client.message_history)
                if current_history_size > last_processed_index:
                    # Process new messages
                    for i in range(last_processed_index, current_history_size):
                        msg = client.message_history[i]
                        
                        # Only show received messages (not sent)
                        if msg.direction == "received":
                            # Determine if we should show this message based on filters
                            should_show = True
                            event_type = None
                            
                            # Try to extract event type for filtering
                            try:
                                import json as json_lib
                                msg_obj = json_lib.loads(msg.message)
                                
                                # Check for Event messages
                                if "Event" in msg_obj:
                                    event_type = msg_obj.get("Event")
                                # Check for response messages with method
                                elif "method" in msg_obj:
                                    event_type = msg_obj.get("method", "").split(".")[-1]  # Get last part of method
                                # Check for jsonrpc responses
                                elif "jsonrpc" in msg_obj and "id" in msg_obj:
                                    event_type = "Response"
                                    
                            except Exception:
                                # If we can't parse it, treat it as Unknown type
                                event_type = "Unknown"
                            
                            # Apply filters
                            if event_type:
                                # If include list is specified, only show if event_type is in it
                                if include_set is not None:
                                    should_show = event_type in include_set
                                # If exclude list is specified, don't show if event_type is in it
                                elif exclude_set:
                                    should_show = event_type not in exclude_set
                            
                            if not should_show:
                                messages_filtered += 1
                                continue  # Skip this message
                            
                            messages_displayed += 1
                            
                            if as_json:
                                # Raw JSON output
                                click.echo(msg.message)
                            else:
                                # Pretty print format
                                click.echo(f"\n[{msg.timestamp}] Message #{messages_displayed}")
                                if event_type:
                                    click.echo(f"Event Type: {event_type}")
                                click.echo("-" * 40)
                                
                                try:
                                    # Parse the message for better display
                                    parsed = TelescopeMessageParser.parse_message(msg.message, msg.timestamp)
                                    parsed_dict = parsed.model_dump()
                                    
                                    # Display based on message type
                                    if 'event_type' in parsed_dict:
                                        # Event message
                                        click.echo("Type: EVENT")
                                        click.echo(f"Event: {parsed_dict.get('event_type', 'Unknown')}")
                                        if 'data' in parsed_dict and parsed_dict['data']:
                                            click.echo("Data:")
                                            import json as json_lib
                                            formatted = json_lib.dumps(parsed_dict['data'], indent=2)
                                            for line in formatted.split('\n'):
                                                click.echo(f"  {line}")
                                    elif 'method' in parsed_dict:
                                        # Response message
                                        click.echo("Type: RESPONSE")
                                        click.echo(f"Method: {parsed_dict.get('method', 'Unknown')}")
                                        click.echo(f"ID: {parsed_dict.get('id', 'N/A')}")
                                        if 'result' in parsed_dict and parsed_dict['result']:
                                            click.echo("Result:")
                                            import json as json_lib
                                            formatted = json_lib.dumps(parsed_dict['result'], indent=2)
                                            for line in formatted.split('\n'):
                                                click.echo(f"  {line}")
                                    else:
                                        # Unknown/raw message
                                        click.echo("Type: RAW")
                                        import json as json_lib
                                        try:
                                            msg_obj = json_lib.loads(msg.message)
                                            formatted = json_lib.dumps(msg_obj, indent=2)
                                            for line in formatted.split('\n'):
                                                click.echo(f"  {line}")
                                        except Exception:
                                            click.echo(f"  {msg.message}")
                                            
                                except Exception:
                                    # Fallback to raw display if parsing fails
                                    click.echo("Type: UNPARSED")
                                    click.echo(f"Raw: {msg.message}")
                            
                            # Check if we should stop after this message
                            if count and messages_displayed >= count:
                                break
                    
                    # Update the last processed index
                    last_processed_index = current_history_size
                
                # Small delay to avoid busy waiting
                await asyncio.sleep(0.1)
            
            # Summary
            elapsed = time.time() - start_time
            total_messages = messages_displayed + messages_filtered
            click.echo("\n" + "=" * 60)
            click.echo("📊 Monitoring Summary:")
            click.echo(f"   Duration: {elapsed:.1f} seconds")
            click.echo(f"   Messages received: {total_messages}")
            click.echo(f"   Messages displayed: {messages_displayed}")
            if messages_filtered > 0:
                click.echo(f"   Messages filtered: {messages_filtered}")
            if total_messages > 0:
                rate = total_messages / elapsed
                click.echo(f"   Message rate: {rate:.2f} messages/second")
            
            await client.disconnect()
            
        except KeyboardInterrupt:
            click.echo("\n\n⚠️ Monitoring interrupted by user")
            await client.disconnect()
        except Exception as e:
            click.echo(f"\n❌ Error during monitoring: {e}")
            if client.is_connected:
                await client.disconnect()
    
    asyncio.run(monitor_messages())


@cli.command(name='stream-images')
@click.option('--host', '-h', help='Telescope IP (uses saved connection if not provided)')
@click.option('--port', '-p', type=int, help='Port number')
@click.option('--duration', '-d', type=float, help='Duration in seconds (default: continuous)')
@click.option('--count', '-c', type=int, help='Number of images to capture before stopping')
@click.option('--json', 'as_json', is_flag=True, help='Output statistics as JSON')
@click.option('--save', '-s', help='Directory to save images or video file path (e.g., /tmp/images or /tmp/output.mp4)')
@click.option('--save-video', is_flag=True, help='Save as video file (MP4) instead of individual images')
@click.option('--fps', type=float, default=10.0, help='Video frame rate when saving as video (default: 10 fps)')
@click.option('--camera-id', type=int, default=0, help='Camera ID (default: 0)')
@click.option('--show-events', is_flag=True, help='Display other telescope events and messages')
@click.option('--event-filter', multiple=True, help='Filter events to show (can be used multiple times)')
@click.option('--compact', is_flag=True, help='Use compact one-line display format')
@click.option('--scenery', is_flag=True, help='Use scenery mode (IscopeStartView) instead of BeginStreaming')
@click.option('--verbose-rtsp', is_flag=True, help='Show RTSP/H.264 decoder warnings (normally suppressed)')
@click.pass_context
def stream_images(ctx, host, port, duration, count, as_json, save, save_video, fps, camera_id, show_events, event_filter, compact, scenery, verbose_rtsp):
    """Stream images from the telescope and display statistics.
    
    Starts both a regular client and imaging client, begins streaming,
    and continuously fetches images while displaying statistics about each frame.
    
    Statistics include:
    - Image dimensions (width x height)
    - Image size in bytes
    - Time since last image
    - Frame rate
    - Stack/drop counts
    
    With --show-events, also displays telescope events like:
    - PiStatus updates (temperature, battery)
    - Stack events
    - Focus changes
    - Mode changes
    
    Examples:
        scopinator stream-images --host 192.168.1.100    # Stream continuously
        scopinator stream-images --duration 30           # Stream for 30 seconds
        scopinator stream-images --count 10              # Capture 10 images
        scopinator stream-images --json                  # Output stats as JSON
        scopinator stream-images --save /tmp/images      # Save images to directory
        scopinator stream-images --save /tmp/output.mp4 --save-video  # Save as video
        scopinator stream-images --show-events           # Show all events
        scopinator stream-images --show-events --event-filter Stack  # Show only Stack events
        scopinator stream-images --compact               # Compact one-line display
        scopinator stream-images --scenery               # Use scenery mode instead of BeginStreaming
    """
    # Ensure context exists
    if not ctx.obj:
        ctx.obj = {}
    
    host = host or ctx.obj.get('host')
    port = port or ctx.obj.get('port', 4700)
    
    if not host:
        click.echo("❌ No telescope connection. Use 'connect' command first or provide --host")
        return
    
    from scopinator.seestar.client import SeestarClient
    from scopinator.seestar.imaging_client import SeestarImagingClient
    from scopinator.util.eventbus import EventBus
    from pathlib import Path
    from datetime import datetime
    import time
    import numpy as np
    import os
    
    # Enable verbose RTSP mode if requested
    if verbose_rtsp:
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "loglevel;warning"
        os.environ["OPENCV_LOG_LEVEL"] = "WARNING"
        if not as_json:
            click.echo("🔊 RTSP verbose mode enabled (H.264 warnings will be shown)")
    
    async def stream_images_task():
        # Create a shared event bus for both clients
        event_bus = EventBus()
        
        # Create both clients with correct ports
        # Regular client uses port 4700, imaging client uses port 4800
        client = SeestarClient(host=host, port=port, event_bus=event_bus)
        imaging_client = SeestarImagingClient(host=host, port=4800, event_bus=event_bus)
        
        images_received = 0
        last_image_time = None
        last_message_check = 0
        start_time = time.time()
        end_time = start_time + duration if duration else None
        save_path = None
        video_writer = None
        event_filter_set = set(event_filter) if event_filter else None
        
        # Setup save path (directory for images or file for video)
        if save:
            save_path = Path(save)
            if save_video:
                # Video file - ensure parent directory exists
                save_path.parent.mkdir(parents=True, exist_ok=True)
                if not save_path.suffix:
                    save_path = save_path.with_suffix('.mp4')
                click.echo(f"💾 Will save video to: {save_path}")
            else:
                # Directory for images
                save_path.mkdir(parents=True, exist_ok=True)
                click.echo(f"💾 Saving images to: {save_path}")
        
        try:
            # Connect both clients
            click.echo(f"🔭 Connecting to telescope...")
            click.echo(f"   Regular client: {host}:{port}")
            click.echo(f"   Imaging client: {host}:4800")
            await client.connect()
            await imaging_client.connect()
            click.echo("✅ Connected both clients")
            
            # Check current mode
            click.echo(f"📷 Current mode: {imaging_client.client_mode or 'Unknown'}")
            
            # Start streaming based on mode
            if scenery:
                click.echo("🎬 Starting scenery view (IscopeStartView)...")
                from scopinator.seestar.commands.parameterized import IscopeStartView, IscopeStartViewParams, IscopeStopView
                
                # Send IscopeStartView command with scenery mode
                start_view_cmd = IscopeStartView(
                    params=IscopeStartViewParams(
                        mode="scenery",
                        target_name="Scenery Stream"
                    )
                )
                response = await client.send_and_recv(start_view_cmd)
                if response and response.result:
                    click.echo("✅ Scenery view started")
                else:
                    click.echo("⚠️ Scenery view command sent but no confirmation")
            else:
                click.echo("🎬 Starting image stream (BeginStreaming)...")
                await client.scope_view()
                await imaging_client.start_streaming()
            
            await asyncio.sleep(1)  # Give it a moment to start
            
            if not as_json:
                mode_str = "compact mode" if compact else "verbose mode"
                click.echo(f"📊 Streaming images ({mode_str})...")
                if show_events:
                    click.echo("📡 Showing events" + (f" (filtered: {', '.join(event_filter)})" if event_filter_set else ""))
                if compact:
                    click.echo("Format: [Time] #Num | WxHxC | Size | Δt | FPS | S:stacked D:dropped [pixel info]")
                click.echo("-" * 60)
            
            # Helper function to display events
            def display_event(msg, msg_type="EVENT"):
                """Display an event message if show_events is enabled."""
                if not show_events or as_json:
                    return
                    
                try:
                    import json as json_lib
                    msg_obj = json_lib.loads(msg.message) if hasattr(msg, 'message') else msg
                    
                    # Extract event type
                    event_type = None
                    if isinstance(msg_obj, dict):
                        if "Event" in msg_obj:
                            event_type = msg_obj.get("Event")
                        elif "method" in msg_obj:
                            event_type = msg_obj.get("method", "").split(".")[-1]
                    
                    # Apply filter
                    if event_filter_set and event_type and event_type not in event_filter_set:
                        return
                    
                    timestamp = datetime.now().strftime('%H:%M:%S')
                    
                    if compact:
                        # Compact one-line event display
                        event_data = ""
                        if event_type == "PiStatus":
                            battery = msg_obj.get("battery_capacity", "?")
                            temp = msg_obj.get("temp", "?")
                            event_data = f" 🔋{battery}% 🌡️{temp}°C"
                        elif event_type == "Stack":
                            stacked = msg_obj.get("stacked_frame", "?")
                            state = msg_obj.get("state", "?")
                            event_data = f" stack:{stacked} state:{state}"
                        elif event_type == "FocuserMove":
                            pos = msg_obj.get("position", "?")
                            event_data = f" pos:{pos}"
                        click.echo(f"[{timestamp}] EVENT: {event_type or 'Unknown'}{event_data}")
                    else:
                        # Verbose event display
                        click.echo(f"\n💫 [{timestamp}.{datetime.now().strftime('%f')[:3]}] {msg_type}: {event_type or 'Unknown'}")
                        
                        # Show key details based on event type
                        if event_type == "PiStatus" and "Timestamp" in msg_obj:
                            if "battery_capacity" in msg_obj:
                                click.echo(f"   🔋 Battery: {msg_obj['battery_capacity']}%")
                            if "temp" in msg_obj:
                                click.echo(f"   🌡️ Temp: {msg_obj['temp']}°C")
                        elif event_type == "Stack":
                            if "stacked_frame" in msg_obj:
                                click.echo(f"   📚 Stacked: {msg_obj['stacked_frame']}")
                            if "state" in msg_obj:
                                click.echo(f"   State: {msg_obj['state']}")
                        elif event_type == "FocuserMove":
                            if "position" in msg_obj:
                                click.echo(f"   🔍 Position: {msg_obj['position']}")
                        else:
                            # Show a compact version of the data
                            if isinstance(msg_obj, dict) and "result" in msg_obj:
                                result = msg_obj["result"]
                                if isinstance(result, dict) and len(result) > 0:
                                    # Show first few key-value pairs
                                    items = list(result.items())[:3]
                                    for k, v in items:
                                        click.echo(f"   {k}: {v}")
                except Exception:
                    pass  # Silently ignore parse errors
            
            # Start fetching images
            async for image in imaging_client.get_next_image(camera_id=camera_id):
                # Check for new events/messages from the regular client
                if show_events and not as_json:
                    current_history_size = len(client.message_history)
                    if current_history_size > last_message_check:
                        # Process new messages
                        for i in range(last_message_check, current_history_size):
                            msg = client.message_history[i]
                            if msg.direction == "received":
                                display_event(msg)
                        last_message_check = current_history_size
                
                if image and image.image is not None:
                    images_received += 1
                    current_time = time.time()
                    
                    # Calculate statistics
                    height, width = image.image.shape[:2]
                    channels = image.image.shape[2] if len(image.image.shape) > 2 else 1
                    bytes_size = image.image.nbytes
                    
                    # Time calculations
                    time_since_last = None
                    fps = None
                    if last_image_time:
                        time_since_last = current_time - last_image_time
                        fps = 1.0 / time_since_last if time_since_last > 0 else 0
                    
                    elapsed = current_time - start_time
                    avg_fps = images_received / elapsed if elapsed > 0 else 0
                    
                    # Get status from imaging client
                    status = imaging_client.status
                    
                    if as_json:
                        # JSON output
                        stats = {
                            "image_number": images_received,
                            "timestamp": datetime.now().isoformat(),
                            "dimensions": {"width": width, "height": height, "channels": channels},
                            "bytes": bytes_size,
                            "time_since_last": time_since_last,
                            "fps": fps,
                            "avg_fps": avg_fps,
                            "elapsed": elapsed,
                            "stacked_frames": status.stacked_frame,
                            "dropped_frames": status.dropped_frame,
                            "skipped_frames": status.skipped_frame,
                        }
                        import json as json_lib
                        click.echo(json_lib.dumps(stats))
                    elif compact:
                        # Compact one-line output
                        timestamp = datetime.now().strftime('%H:%M:%S')
                        size_mb = bytes_size/1024/1024
                        ms_since = f"{time_since_last*1000:.0f}ms" if time_since_last else "----"
                        fps_str = f"{fps:.1f}" if fps else "----"
                        pixel_info = ""
                        if channels == 1:
                            pixel_info = f" [{np.min(image.image)}-{np.max(image.image)}]"
                        else:
                            # Show just the average brightness for RGB
                            avg_r = np.mean(image.image[:,:,0])
                            avg_g = np.mean(image.image[:,:,1]) if channels > 1 else 0
                            avg_b = np.mean(image.image[:,:,2]) if channels > 2 else 0
                            pixel_info = f" RGB[{avg_r:.0f},{avg_g:.0f},{avg_b:.0f}]"
                        
                        click.echo(f"[{timestamp}] #{images_received:04d} | {width}x{height}x{channels} | {size_mb:.1f}MB | Δt:{ms_since:>7s} | FPS:{fps_str:>5s} | S:{status.stacked_frame:3d} D:{status.dropped_frame:2d}{pixel_info}")
                    else:
                        # Pretty print output
                        click.echo(f"\n📸 Image #{images_received}")
                        click.echo(f"   Timestamp: {datetime.now().strftime('%H:%M:%S.%f')[:-3]}")
                        click.echo(f"   Dimensions: {width}x{height}x{channels}")
                        click.echo(f"   Size: {bytes_size:,} bytes ({bytes_size/1024/1024:.2f} MB)")
                        if time_since_last:
                            click.echo(f"   Time since last: {time_since_last*1000:.1f} ms")
                            click.echo(f"   Current FPS: {fps:.2f}")
                        click.echo(f"   Average FPS: {avg_fps:.2f}")
                        click.echo(f"   Frames: {status.stacked_frame} stacked, {status.dropped_frame} dropped, {status.skipped_frame} skipped")
                        
                        # Show image stats
                        if channels == 1:
                            click.echo(f"   Pixel range: [{np.min(image.image)}, {np.max(image.image)}]")
                        else:
                            for i, color in enumerate(['R', 'G', 'B'][:channels]):
                                click.echo(f"   {color} range: [{np.min(image.image[:,:,i])}, {np.max(image.image[:,:,i])}]")
                    
                    # Save image if requested
                    if save_path:
                        if save_video:
                            # Save to video file
                            if video_writer is None:
                                # Initialize video writer on first frame
                                import cv2
                                # Ensure we're using integer dimensions and valid fps
                                vid_width = int(width)
                                vid_height = int(height)
                                vid_fps = float(fps) if fps and fps > 0 else 10.0
                                
                                # Choose codec based on file extension
                                file_ext = save_path.suffix.lower()
                                if file_ext == '.avi':
                                    # Use MJPG for AVI files
                                    fourcc = cv2.VideoWriter_fourcc(*'MJPG')
                                    codec_name = 'MJPG'
                                else:
                                    # Use H.264 for MP4 files (more compatible than mp4v)
                                    # Try different H.264 codec identifiers
                                    try:
                                        fourcc = cv2.VideoWriter_fourcc(*'avc1')  # H.264 codec
                                        codec_name = 'avc1 (H.264)'
                                    except:
                                        fourcc = cv2.VideoWriter_fourcc(*'h264')
                                        codec_name = 'h264'
                                
                                if not as_json:
                                    click.echo(f"   🎬 Initializing video writer: {vid_width}x{vid_height} @ {vid_fps} fps")
                                    click.echo(f"      Output: {save_path} (codec: {codec_name})")
                                
                                video_writer = cv2.VideoWriter(str(save_path), fourcc, vid_fps, (vid_width, vid_height))
                                if not video_writer.isOpened():
                                    # Try fallback codecs
                                    fallback_codecs = [
                                        ('mp4v', 'MPEG-4'),
                                        ('XVID', 'Xvid'),
                                        ('MJPG', 'Motion JPEG'),
                                    ]
                                    
                                    for codec, name in fallback_codecs:
                                        if not as_json:
                                            click.echo(f"   ⚠️ {codec_name} failed, trying {name}...")
                                        fourcc = cv2.VideoWriter_fourcc(*codec)
                                        video_writer = cv2.VideoWriter(str(save_path), fourcc, vid_fps, (vid_width, vid_height))
                                        if video_writer.isOpened():
                                            if not as_json:
                                                click.echo(f"   ✅ Video writer opened with {name} codec")
                                            break
                                    
                                    if not video_writer.isOpened():
                                        click.echo(f"❌ Failed to open video writer for {save_path}")
                                        click.echo(f"   Dimensions: {vid_width}x{vid_height}, FPS: {vid_fps}")
                                        video_writer = None
                                else:
                                    if not as_json:
                                        click.echo(f"   ✅ Video writer initialized successfully")
                            
                            if video_writer:
                                # Convert image to BGR for OpenCV (assuming input is RGB)
                                if len(image.image.shape) == 3:
                                    bgr_frame = cv2.cvtColor(image.image.astype(np.uint8), cv2.COLOR_RGB2BGR)
                                else:
                                    # Grayscale - convert to BGR
                                    bgr_frame = cv2.cvtColor(image.image.astype(np.uint8), cv2.COLOR_GRAY2BGR)
                                video_writer.write(bgr_frame)
                                
                                if not as_json and images_received % 10 == 0:
                                    click.echo(f"   💾 Video: {images_received} frames written")
                        else:
                            # Save as individual image
                            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
                            filename = save_path / f"image_{timestamp}.npy"
                            np.save(filename, image.image)
                            if not as_json:
                                click.echo(f"   💾 Saved: {filename.name}")
                    
                    last_image_time = current_time
                    
                    # Check if we should stop
                    if end_time and current_time >= end_time:
                        if not as_json:
                            click.echo(f"\n⏱️ Duration reached ({duration} seconds)")
                        break
                    
                    if count and images_received >= count:
                        if not as_json:
                            click.echo(f"\n✅ Captured {count} images")
                        break
                
                # Small delay to avoid busy loop
                await asyncio.sleep(0.001)
            
            # Stop streaming based on mode
            if not as_json:
                click.echo("\n🛑 Stopping stream...")
            
            if scenery:
                # Stop scenery view
                from scopinator.seestar.commands.parameterized import IscopeStopView, StopStage
                stop_view_cmd = IscopeStopView(params={"stage": StopStage.STACK})
                response = await client.send_and_recv(stop_view_cmd)
                if response:
                    click.echo("✅ Scenery view stopped") if not as_json else None
            else:
                await imaging_client.stop_streaming()
            
            # Clean up video writer
            if video_writer:
                video_writer.release()
                if not as_json:
                    click.echo(f"✅ Video saved: {save_path} ({images_received} frames)")
            
            # Summary
            if not as_json:
                total_elapsed = time.time() - start_time
                click.echo("\n" + "=" * 60)
                click.echo("📊 Streaming Summary:")
                click.echo(f"   Duration: {total_elapsed:.1f} seconds")
                click.echo(f"   Images received: {images_received}")
                if images_received > 0:
                    avg_fps = images_received / total_elapsed
                    click.echo(f"   Average FPS: {avg_fps:.2f}")
                    click.echo(f"   Final frame counts: {imaging_client.status.stacked_frame} stacked, {imaging_client.status.dropped_frame} dropped")
                if save_path:
                    if save_video:
                        click.echo(f"   Video saved to: {save_path}")
                    else:
                        click.echo(f"   Images saved to: {save_path}")
            
            # Disconnect
            await imaging_client.disconnect()
            await client.disconnect()
            
        except KeyboardInterrupt:
            if not as_json:
                click.echo("\n\n⚠️ Streaming interrupted by user")
            
            # Clean up video writer
            if video_writer:
                video_writer.release()
                if not as_json:
                    click.echo(f"💾 Video saved: {save_path} ({images_received} frames)")
            
            try:
                if scenery:
                    from scopinator.seestar.commands.parameterized import IscopeStopView, StopStage
                    stop_view_cmd = IscopeStopView(params={"stage": StopStage.STACK})
                    await client.send_and_recv(stop_view_cmd)
                else:
                    await imaging_client.stop_streaming()
            except:
                pass
            await imaging_client.disconnect()
            await client.disconnect()
        except Exception as e:
            click.echo(f"\n❌ Error during streaming: {e}")
            import traceback
            traceback.print_exc()
            
            # Clean up video writer
            if video_writer:
                video_writer.release()
                if not as_json:
                    click.echo(f"💾 Video saved: {save_path} ({images_received} frames)")
            
            try:
                if scenery:
                    from scopinator.seestar.commands.parameterized import IscopeStopView, StopStage
                    stop_view_cmd = IscopeStopView(params={"stage": StopStage.STACK})
                    await client.send_and_recv(stop_view_cmd)
                else:
                    await imaging_client.stop_streaming()
            except:
                pass
            if imaging_client.is_connected:
                await imaging_client.disconnect()
            if client.is_connected:
                await client.disconnect()
    
    asyncio.run(stream_images_task())


@cli.command(name='reboot')
@click.option('--host', '-h', help='Telescope IP (uses saved connection if not provided)')
@click.option('--port', '-p', type=int, help='Port number')
@click.option('--confirm', is_flag=True, help='Confirm reboot without prompting')
@click.pass_context
def reboot(ctx, host, port, confirm):
    """Reboot the telescope (requires confirmation)."""
    # Ensure context exists
    if not ctx.obj:
        ctx.obj = {}
    
    host = host or ctx.obj.get('host')
    port = port or ctx.obj.get('port', 4700)
    
    if not host:
        click.echo("❌ No telescope connection. Use 'connect' command first or provide --host")
        return
    
    if not confirm:
        click.echo("⚠️  This will reboot the telescope!")
        if not click.confirm("Are you sure you want to continue?"):
            click.echo("Reboot cancelled")
            return
    
    from scopinator.seestar.client import SeestarClient
    from scopinator.seestar.commands.simple import PiReboot
    
    async def reboot_telescope():
        client = SeestarClient(host=host, port=port)
        try:
            await client.connect()
            click.echo(f"🔄 Rebooting telescope at {host}:{port}...")
            response = await client.send_and_recv(PiReboot())
            if response:
                click.echo("✅ Reboot command sent successfully")
                click.echo("   The telescope will restart. Wait a few minutes before reconnecting.")
            else:
                click.echo("⚠️ Reboot command sent but no confirmation received")
            await client.disconnect()
        except Exception as e:
            click.echo(f"❌ Error sending reboot command: {e}")
    
    asyncio.run(reboot_telescope())


if __name__ == '__main__':
    cli()