"""Main CLI entry point for scopinator."""

import asyncio
import click
from loguru import logger
import sys


@click.group(invoke_without_command=True)
@click.option('--debug', is_flag=True, help='Enable debug logging')
@click.option('-i', '--interactive', is_flag=True, help='Start interactive mode')
@click.pass_context
def cli(ctx, debug, interactive):
    """Scopinator - Control and manage telescopes from the command line.
    
    Use 'scopinator interactive' or 'scopinator -i' to enter interactive mode.
    """
    if debug:
        logger.remove()
        logger.add(sys.stderr, level="DEBUG")
    else:
        logger.remove()
        logger.add(sys.stderr, level="INFO")
    
    ctx.ensure_object(dict)
    ctx.obj['debug'] = debug
    
    # Check if we should enter interactive mode
    if ctx.invoked_subcommand is None:
        if interactive:
            # Call the interactive command directly
            ctx.invoke(interactive_cmd)
        else:
            # Show help if no subcommand and not interactive
            click.echo(ctx.get_help())


@cli.command()
@click.option('--host', '-h', help='Telescope IP address or hostname')
@click.option('--port', '-p', default=4700, help='Port number (default: 4700)')
@click.option('--timeout', '-t', default=10.0, help='Discovery timeout in seconds')
@click.pass_context
def discover(ctx, host, port, timeout):
    """Discover available telescopes on the network."""
    from scopinator.cli.commands.discovery import discover_telescopes
    
    click.echo("🔍 Searching for telescopes...")
    
    async def run_discovery():
        if host:
            click.echo(f"Checking {host}:{port}...")
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
            telescopes = await discover_telescopes(timeout=timeout)
            return telescopes
    
    telescopes = asyncio.run(run_discovery())
    
    if not telescopes and not host:
        click.echo("No telescopes found. Make sure your telescope is powered on and connected to the network.")
    elif telescopes and not host:
        click.echo(f"\nFound {len(telescopes)} telescope(s):")
        for idx, (ip, port) in enumerate(telescopes, 1):
            click.echo(f"  {idx}. {ip}:{port}")


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
            
            # Get basic info
            device_state = await client.get_device_state()
            if device_state:
                click.echo(f"📡 Device State: {device_state}")
            
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
@click.pass_context
def status(ctx, host, port):
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
    
    async def get_status():
        client = SeestarClient(host=host, port=port)
        try:
            await client.connect()
            click.echo(f"📡 Connected to {host}:{port}\n")
            
            # Get various status information
            device_state = await client.get_device_state()
            view_state = await client.get_view_state()
            focus_position = await client.get_focuser_position()
            disk_info = await client.get_disk_volume()
            
            click.echo("🔭 Telescope Status:")
            click.echo("-" * 40)
            
            if device_state:
                click.echo(f"Device State: {device_state}")
            
            if view_state:
                click.echo(f"View State: {view_state}")
            
            if focus_position is not None:
                click.echo(f"Focus Position: {focus_position}")
            
            if disk_info:
                click.echo(f"Disk Space: {disk_info}")
            
            # Check current status from client
            status = client.status
            if status:
                if status.battery_capacity:
                    click.echo(f"Battery: {status.battery_capacity}%")
                if status.temp:
                    click.echo(f"Temperature: {status.temp}°C")
                if status.target_name:
                    click.echo(f"Target: {status.target_name}")
                if status.ra is not None and status.dec is not None:
                    click.echo(f"Coordinates: RA={status.ra:.4f}, Dec={status.dec:.4f}")
            
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
                
                # Wait a moment and check position
                await asyncio.sleep(2)
                coords = await client.get_equ_coord()
                if coords:
                    click.echo(f"📍 Current position: RA={coords.ra:.4f}, Dec={coords.dec:.4f}")
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
    """Enter interactive command mode with autocomplete."""
    from scopinator.cli.interactive_simple import run_interactive_mode
    
    # Run the interactive mode with working autocomplete
    run_interactive_mode(cli, ctx)


@cli.command()
@click.pass_context
def version(ctx):
    """Show scopinator version."""
    import scopinator
    from importlib.metadata import version
    try:
        v = version('scopinator')
        click.echo(f"Scopinator version: {v}")
    except:
        click.echo("Scopinator version: development")


if __name__ == '__main__':
    cli()