"""Main CLI entry point for scopinator."""

import asyncio
import click
from loguru import logger
import sys


@click.group(invoke_without_command=True)
@click.option('--debug', is_flag=True, help='Enable debug logging')
@click.pass_context
def cli(ctx, debug):
    """Scopinator - Control and manage telescopes from the command line.
    
    Use 'scopinator repl' to enter interactive mode with autocompletion.
    """
    if debug:
        logger.remove()
        logger.add(sys.stderr, level="DEBUG")
    else:
        logger.remove()
        logger.add(sys.stderr, level="INFO")
    
    ctx.ensure_object(dict)
    ctx.obj['debug'] = debug
    
    # Show help if no subcommand
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())

# Register the enhanced REPL command
from scopinator.cli.repl_enhanced import register_enhanced_repl
register_enhanced_repl(cli)


@cli.command()
@click.option('--host', '-h', help='Telescope IP address or hostname')
@click.option('--port', '-p', default=4700, help='Port number (default: 4700)')
@click.option('--timeout', '-t', default=5.0, help='Discovery timeout in seconds (default: 5)')
@click.pass_context
def discover(ctx, host, port, timeout):
    """Discover available telescopes on the network."""
    from scopinator.cli.commands.discovery import discover_telescopes
    import time
    
    async def run_discovery():
        if host:
            click.echo(f"🔍 Checking {host}:{port}...")
            from scopinator.seestar.connection import SeestarConnection
            conn = SeestarConnection(host=host, port=port)
            try:
                await asyncio.wait_for(conn.open(), timeout=timeout)
                click.echo(f"✅ Found telescope at {host}:{port}")
                await conn.close()
                return [(host, port)]
            except Exception as e:
                click.echo(f"❌ No telescope found at {host}:{port}: {e}")
                return []
        else:
            # Show progress while discovering
            click.echo(f"🔍 Searching for telescopes on the network (timeout: {timeout}s)...")
            click.echo("   This may take a few seconds...")
            
            start_time = time.time()
            telescopes = await discover_telescopes(timeout=timeout)
            elapsed = time.time() - start_time
            
            click.echo(f"   Search completed in {elapsed:.1f} seconds")
            return telescopes
    
    telescopes = asyncio.run(run_discovery())
    
    if not telescopes and not host:
        click.echo("\n❌ No telescopes found.")
        click.echo("   Make sure your telescope is:")
        click.echo("   • Powered on")
        click.echo("   • Connected to the same network")
        click.echo("   • Not already connected to another app")
        click.echo("\n   Try specifying the IP directly: scopinator discover --host <IP>")
    elif telescopes and not host:
        click.echo(f"\n✅ Found {len(telescopes)} telescope(s):")
        for idx, (ip, port) in enumerate(telescopes, 1):
            click.echo(f"  {idx}. {ip}:{port}")
        click.echo("\nTo connect: scopinator connect <IP>")


@cli.command()
@click.argument('host')
@click.option('--port', '-p', default=4700, type=int, help='Port number (default: 4700)')
@click.option('--timeout', '-t', default=10.0, help='Connection timeout in seconds')
@click.pass_context
def connect(ctx, host, port, timeout):
    """Connect to a telescope and save connection info."""
    from scopinator.seestar.client import SeestarClient
    
    # Ensure context exists
    if not ctx.obj:
        ctx.obj = {}
    
    async def test_connection():
        client = SeestarClient(host=host, port=port)
        try:
            await client.connect()
            click.echo(f"✅ Successfully connected to telescope at {host}:{port}")
            
            # Save connection info to context
            ctx.obj['host'] = host
            ctx.obj['port'] = port
            
            # Get basic info from status
            if client.status:
                if client.status.battery_capacity:
                    click.echo(f"🔋 Battery: {client.status.battery_capacity}%")
                if client.status.temp:
                    click.echo(f"🌡️ Temperature: {client.status.temp}°C")
            
            await client.disconnect()
            return True
        except Exception as e:
            click.echo(f"❌ Failed to connect: {e}")
            return False
    
    success = asyncio.run(test_connection())
    if success:
        click.echo(f"\nConnection saved. Use other commands to control the telescope.")


@cli.command()
@click.option('--host', '-h', help='Telescope IP (uses saved connection if not provided)')
@click.option('--port', '-p', type=int, help='Port number')
@click.option('--detailed', '-d', is_flag=True, help='Show detailed device information')
@click.pass_context
def status(ctx, host, port, detailed):
    """Get current telescope status."""
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
    
    async def get_status():
        client = SeestarClient(host=host, port=port)
        try:
            await client.connect()
            click.echo(f"📡 Connected to {host}:{port}\n")
            
            # Get comprehensive device state if detailed flag is set
            if detailed:
                device_response = await client.send_and_recv(GetDeviceState())
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
            
            # Always show basic status from SeestarStatus
            click.echo("📊 Current Status:")
            click.echo("-" * 40)
            
            status = client.status
            if status:
                # Basic info
                if status.battery_capacity is not None:
                    icon = "🔋" if status.battery_capacity > 20 else "🪫"
                    click.echo(f"{icon} Battery: {status.battery_capacity}%")
                if status.charger_status:
                    click.echo(f"⚡ Charger: {status.charger_status}")
                if status.temp is not None:
                    click.echo(f"🌡️ Temperature: {status.temp}°C")
                
                # Target & Position
                if status.target_name:
                    click.echo(f"🎯 Target: {status.target_name}")
                if status.ra is not None and status.dec is not None:
                    click.echo(f"📍 Coordinates: RA={status.ra:.4f}°, Dec={status.dec:.4f}°")
                if status.dist_deg is not None:
                    click.echo(f"📏 Distance to target: {status.dist_deg:.2f}°")
                
                # Imaging
                if status.stacked_frame > 0 or status.dropped_frame > 0:
                    click.echo(f"📸 Frames: {status.stacked_frame} stacked, {status.dropped_frame} dropped")
                if status.gain is not None:
                    click.echo(f"📊 Gain: {status.gain}")
                if status.lp_filter:
                    click.echo(f"🔴 LP Filter: Active")
                
                # Focus
                if status.focus_position is not None:
                    click.echo(f"🔍 Focus Position: {status.focus_position}")
                
                # Storage
                if status.freeMB is not None and status.totalMB is not None:
                    used_percent = ((status.totalMB - status.freeMB) / status.totalMB * 100) if status.totalMB > 0 else 0
                    click.echo(f"💾 Storage: {status.freeMB:,} MB free / {status.totalMB:,} MB total ({used_percent:.1f}% used)")
                
                # Stage/Mode
                if status.stage:
                    click.echo(f"🎬 Stage: {status.stage}")
                
                # Pattern monitoring (if configured)
                if status.pattern_match_file:
                    icon = "✅" if status.pattern_match_found else "❌"
                    click.echo(f"{icon} Pattern Monitor: {'Found' if status.pattern_match_found else 'Not found'}")
                    if status.pattern_match_last_check:
                        click.echo(f"   Last check: {status.pattern_match_last_check}")
            else:
                click.echo("No status information available")
            
            # Client mode
            if client.client_mode:
                click.echo(f"\n🎮 Client Mode: {client.client_mode}")
            
            await client.disconnect()
        except Exception as e:
            click.echo(f"❌ Error getting status: {e}")
    
    asyncio.run(get_status())


@cli.command()
@click.option('--host', '-h', help='Telescope IP (uses saved connection if not provided)')
@click.option('--port', '-p', type=int, help='Port number')
@click.pass_context
def park(ctx, host, port):
    """Park the telescope."""
    # Ensure context exists
    if not ctx.obj:
        ctx.obj = {}
    
    host = host or ctx.obj.get('host')
    port = port or ctx.obj.get('port', 4700)
    
    if not host:
        click.echo("❌ No telescope connection. Use 'connect' command first or provide --host")
        return
    
    from scopinator.seestar.client import SeestarClient
    from scopinator.seestar.commands.simple import ScopePark
    
    async def park_telescope():
        client = SeestarClient(host=host, port=port)
        try:
            await client.connect()
            click.echo(f"🔭 Parking telescope at {host}:{port}...")
            
            response = await client.send_command(ScopePark())
            if response:
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
    from scopinator.seestar.commands.parameterized import GotoTarget
    
    async def goto_target():
        client = SeestarClient(host=host, port=port)
        try:
            await client.connect()
            target_desc = name or f"RA={ra:.2f}, Dec={dec:.2f}"
            click.echo(f"🎯 Slewing to {target_desc}...")
            
            goto_cmd = GotoTarget(ra=ra, dec=dec, target_name=name)
            response = await client.send_command(goto_cmd)
            
            if response:
                click.echo(f"✅ Slewing to target initiated")
                
                # Wait a moment and check position from status
                await asyncio.sleep(2)
                if client.status and client.status.ra is not None and client.status.dec is not None:
                    click.echo(f"📍 Current position: RA={client.status.ra:.4f}, Dec={client.status.dec:.4f}")
            else:
                click.echo("⚠️ Goto command sent but no confirmation received")
            
            await client.disconnect()
        except Exception as e:
            click.echo(f"❌ Error executing goto: {e}")
    
    asyncio.run(goto_target())


@cli.command()
@click.option('--host', '-h', help='Telescope IP (uses saved connection if not provided)')
@click.option('--port', '-p', type=int, help='Port number')
@click.option('--duration', '-d', default=10, type=int, help='Stream duration in seconds')
@click.pass_context
def stream(ctx, host, port, duration):
    """Start live image streaming from the telescope."""
    # Ensure context exists
    if not ctx.obj:
        ctx.obj = {}
    
    host = host or ctx.obj.get('host')
    port = port or ctx.obj.get('port', 4700)
    
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
                click.echo(f"  Format: CalVer (YYYY.MM.PATCH)")
                click.echo(f"  Year: {parts[0]}, Month: {parts[1]}, Patch: {parts[2] if len(parts) > 2 else '0'}")
    except:
        # Fallback to package version if metadata not available
        try:
            from scopinator import __version__
            click.echo(f"Scopinator version: {__version__}")
            click.echo(f"  Format: CalVer (YYYY.MM.PATCH)")
        except:
            click.echo("Scopinator version: development")


if __name__ == '__main__':
    cli()