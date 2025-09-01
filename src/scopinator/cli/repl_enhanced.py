"""Enhanced REPL mode with custom help and exit commands."""

import click
from click_repl import repl as click_repl
from prompt_toolkit.history import FileHistory
import os
import sys


def custom_repl(ctx, **kwargs):
    """
    Enhanced REPL wrapper that adds startup instructions and custom commands.
    
    Args:
        ctx: Click Context object (not a Group)
    """
    # Get the group from the context
    group = ctx.command if isinstance(ctx.command, click.Group) else ctx.parent.command
    
    # Create a custom group that includes help and exit commands  
    @group.command(name='help')
    @click.pass_context
    def help_command(ctx):
        """Show available commands and how to use them."""
        parent_ctx = ctx.parent or ctx
        
        click.echo("\n" + click.style("Available Commands:", bold=True))
        
        # Group commands by category
        categories = {
            'Discovery': ['discover'],
            'Connection': ['connect', 'status', 'test-connection'],
            'Control': ['park', 'goto', 'coordinates', 'start-autofocus', 'stop-autofocus', 'start-solve'],
            'Imaging': ['stream', 'camera-info', 'camera-state', 'stack-info', 'stack-setting'],
            'Information': ['disk-volume', 'get-time', 'user-location', 'focus-position', 'solve-result', 
                          'device-state', 'get-setting', 'view-state'],
            'Filter Wheel': ['wheel-state', 'wheel-position', 'wheel-setting'],
            'System': ['version', 'repl', 'interactive', 'reboot'],
            'REPL': ['help', 'exit', 'clear']
        }
        
        for category, cmd_names in categories.items():
            commands_found = []
            for cmd_name in cmd_names:
                if cmd_name in parent_ctx.command.commands:
                    cmd = parent_ctx.command.commands[cmd_name]
                    help_text = (cmd.help or cmd.short_help or "")[:50]
                    commands_found.append((cmd_name, help_text))
                elif cmd_name in ['help', 'exit', 'clear']:
                    # Add descriptions for REPL-specific commands
                    helps = {
                        'help': 'Show this help message',
                        'exit': 'Exit the REPL',
                        'clear': 'Clear the screen'
                    }
                    commands_found.append((cmd_name, helps.get(cmd_name, '')))
            
            if commands_found:
                click.echo(f"\n{click.style(category, fg='cyan')}:")
                for name, desc in commands_found:
                    click.echo(f"  {name:<20} - {desc}")
        
        click.echo(f"\n{click.style('Tips:', bold=True)}")
        click.echo("  • Type a command name followed by --help for detailed help")
        click.echo("  • Use Tab for command completion")
        click.echo("  • Use arrow keys to navigate command history")
        click.echo("  • Type 'exit' or press Ctrl+D to quit")
        click.echo()
    
    @group.command(name='exit')
    def exit_command():
        """Exit the REPL."""
        click.echo("Goodbye!")
        from click_repl import exit as repl_exit
        repl_exit()
    
    @group.command(name='clear')
    def clear_command():
        """Clear the screen."""
        click.clear()
    
    # Show startup instructions
    click.echo(click.style("\n🔭 Scopinator REPL Mode", fg='green', bold=True))
    click.echo("=" * 40)
    click.echo("Welcome to the Scopinator interactive REPL!")
    click.echo("\nQuick Start:")
    click.echo("  • Type 'help' to see available commands")
    click.echo("  • Type '<command> --help' for command details")
    click.echo("  • Press Tab for command completion")
    click.echo("  • Type 'exit' or press Ctrl+D to quit")
    click.echo("\nExamples:")
    click.echo("  discover --host 192.168.1.100")
    click.echo("  connect 192.168.1.100")
    click.echo("  status")
    click.echo("  goto 83.633 -5.391 --name 'Orion Nebula'")
    click.echo("=" * 40)
    click.echo()
    
    # Set up history file
    history_file = os.path.expanduser('~/.scopinator_repl_history')
    
    # Configure prompt
    prompt_kwargs = {
        'history': FileHistory(history_file),
    }
    prompt_kwargs.update(kwargs)
    
    # Start the REPL with the context
    try:
        click_repl(ctx, prompt_kwargs=prompt_kwargs)
    except (EOFError, KeyboardInterrupt):
        click.echo("\nGoodbye!")
        sys.exit(0)


def register_enhanced_repl(group):
    """
    Register an enhanced REPL command with the CLI group.
    """
    @group.command(name='repl')
    @click.pass_context
    def repl_command(ctx):
        """Start an interactive REPL session with autocomplete."""
        # Pass the context to custom_repl
        custom_repl(ctx)
    
    return group