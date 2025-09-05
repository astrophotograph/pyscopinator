"""Simple interactive mode with working autocomplete for scopinator CLI."""

import readline
import click
from typing import List, Optional
from scopinator.util.logging_config import get_logger
logger = get_logger(__name__)


class SimpleCompleter:
    """Simple tab completer for scopinator."""
    
    def __init__(self, cli_group):
        self.cli_group = cli_group
        # Build list of all command names
        self.commands = list(cli_group.commands.keys())
        if 'interactive' in self.commands:
            self.commands.remove('interactive')
        # Add special commands
        self.commands.extend(['help', 'exit', 'quit', 'clear'])
        self.matches = []
        
    def complete(self, text, state):
        """Return the next possible completion for text."""
        # Debug output (comment out in production)
        # import sys
        # print(f"\n[DEBUG] complete called: text='{text}', state={state}", file=sys.stderr)
        
        if state == 0:
            # This is a new completion request, build the match list
            line = readline.get_line_buffer()
            begin = readline.get_begidx()
            end = readline.get_endidx()
            
            # Get the text before the cursor
            before_cursor = line[:end]
            
            # Check if we're completing the first word (command)
            if ' ' not in before_cursor.strip():
                # Complete command names
                if text:
                    self.matches = [cmd for cmd in self.commands if cmd.startswith(text.lower())]
                else:
                    self.matches = self.commands[:]
            else:
                # We're completing arguments/options for a command
                parts = before_cursor.split()
                cmd_name = parts[0] if parts else ""
                
                if cmd_name in self.cli_group.commands:
                    # Get the command object
                    cmd = self.cli_group.commands[cmd_name]
                    
                    # Build list of available options
                    options = []
                    for param in cmd.params:
                        if isinstance(param, click.Option):
                            options.extend(param.opts)
                            options.extend(param.secondary_opts)
                    
                    # Filter options that start with the current text
                    if text:
                        self.matches = [opt for opt in options if opt.startswith(text)]
                    else:
                        self.matches = options[:]
                elif cmd_name == 'help' and len(parts) == 1:
                    # Complete command names after 'help'
                    cmd_list = list(self.cli_group.commands.keys())
                    if text:
                        self.matches = [cmd for cmd in cmd_list if cmd.startswith(text.lower())]
                    else:
                        self.matches = cmd_list[:]
                else:
                    self.matches = []
            
            # Sort matches for consistent ordering
            self.matches.sort()
        
        # Return the state'th match
        try:
            return self.matches[state]
        except IndexError:
            return None


def setup_readline(completer):
    """Configure readline for autocompletion."""
    # Set our custom completer
    readline.set_completer(completer.complete)
    
    # Configure readline behavior - handle macOS libedit vs GNU readline
    import platform
    if platform.system() == 'Darwin' and 'libedit' in readline.__doc__:
        # macOS with libedit needs different binding
        readline.parse_and_bind("bind ^I rl_complete")
        # Also set the standard binding as fallback
        readline.parse_and_bind("tab: complete")
    else:
        # Standard GNU readline binding
        readline.parse_and_bind("tab: complete")
    
    # Additional bindings that might help
    readline.parse_and_bind("set show-all-if-ambiguous on")
    readline.parse_and_bind("set completion-ignore-case on")
    
    # Set word delimiters (what separates "words" for completion)
    readline.set_completer_delims(' \t\n;')
    
    # Load history if it exists
    import os
    histfile = os.path.expanduser('~/.scopinator_history')
    try:
        readline.read_history_file(histfile)
        readline.set_history_length(1000)
    except FileNotFoundError:
        pass
    
    # Save history on exit
    import atexit
    atexit.register(readline.write_history_file, histfile)


def run_interactive_mode(cli_group, ctx):
    """Run the interactive mode with autocomplete."""
    # Set up autocomplete
    completer = SimpleCompleter(cli_group)
    setup_readline(completer)
    
    # Debug info for autocomplete
    import platform
    is_macos = platform.system() == 'Darwin'
    is_libedit = 'libedit' in readline.__doc__ if readline.__doc__ else False
    
    click.echo("Welcome to Scopinator Interactive Mode!")
    click.echo("Type 'help' for commands, Tab for autocomplete, 'exit' to quit.")
    click.echo("Use arrow keys to navigate command history.")
    
    # Show autocomplete status
    if readline.get_completer():
        if is_macos and is_libedit:
            click.echo("📝 Note: On macOS, tab completion may require pressing Tab twice.")
        click.echo("")
    else:
        click.echo("⚠️  Warning: Autocomplete not configured properly")
        click.echo("")
    
    while True:
        try:
            # Use input() which works with readline
            prompt = click.style("scopinator> ", fg='green', bold=True)
            command = input(prompt)
            
            if not command:
                continue
            
            command = command.strip()
            
            # Handle special commands
            if command.lower() in ['exit', 'quit', 'q']:
                click.echo("Goodbye!")
                break
            elif command.lower() == 'clear':
                click.clear()
                continue
            elif command.lower() == 'help':
                show_help(cli_group)
                continue
            elif command.lower().startswith('help '):
                # Help for specific command
                cmd_name = command[5:].strip()
                show_command_help(cli_group, cmd_name)
                continue
            
            # Parse and execute command
            execute_command(cli_group, ctx, command)
                
        except (KeyboardInterrupt, EOFError):
            click.echo("\nGoodbye!")
            break
        except Exception as e:
            logger.error(f"Interactive mode error: {e}")
            click.echo(f"Error: {e}")


def show_help(cli_group):
    """Show general help information."""
    click.echo("\n" + click.style("Available Commands:", bold=True))
    
    # Group commands by category
    categories = {
        'Discovery': ['discover'],
        'Connection': ['connect', 'status'],
        'Control': ['park', 'goto'],
        'Imaging': ['stream'],
        'System': ['version']
    }
    
    for category, cmd_names in categories.items():
        click.echo(f"\n{click.style(category, fg='cyan')}:")
        for cmd_name in cmd_names:
            if cmd_name in cli_group.commands:
                cmd = cli_group.commands[cmd_name]
                help_text = (cmd.help or cmd.short_help or "")[:50]
                
                # Build usage hint
                usage_parts = [cmd_name]
                for param in cmd.params:
                    if isinstance(param, click.Argument):
                        usage_parts.append(f"<{param.name}>")
                
                usage = " ".join(usage_parts)
                click.echo(f"  {usage:<30} - {help_text}")
    
    # Add special commands
    click.echo(f"\n{click.style('Special Commands', fg='cyan')}:")
    click.echo(f"  {'help [command]':<30} - Show help (optionally for a command)")
    click.echo(f"  {'clear':<30} - Clear the screen")
    click.echo(f"  {'exit':<30} - Exit interactive mode")
    
    click.echo(f"\n{click.style('Tips:', bold=True)}")
    click.echo("  • Press Tab to autocomplete commands and options")
    click.echo("  • Use ↑/↓ arrow keys to navigate command history")
    click.echo("  • Type 'help <command>' for detailed command help")
    click.echo()


def show_command_help(cli_group, cmd_name):
    """Show detailed help for a specific command."""
    if cmd_name not in cli_group.commands:
        click.echo(f"Unknown command: {cmd_name}")
        return
    
    cmd = cli_group.commands[cmd_name]
    
    click.echo(f"\n{click.style(cmd_name, bold=True)} - {cmd.help or cmd.short_help or ''}")
    
    # Build usage
    usage_parts = [cmd_name]
    
    # Add arguments
    args = []
    for param in cmd.params:
        if isinstance(param, click.Argument):
            if param.required:
                args.append(f"<{param.name}>")
            else:
                args.append(f"[{param.name}]")
    
    if args:
        usage_parts.extend(args)
    
    click.echo(f"Usage: {' '.join(usage_parts)}")
    
    # Show arguments
    has_args = False
    for param in cmd.params:
        if isinstance(param, click.Argument):
            if not has_args:
                click.echo("\nArguments:")
                has_args = True
            arg_line = f"  {param.name}"
            if param.type:
                type_name = getattr(param.type, 'name', str(param.type))
                arg_line += f" ({type_name})"
            if not param.required:
                arg_line += " [optional]"
            click.echo(arg_line)
    
    # Show options
    has_opts = False
    for param in cmd.params:
        if isinstance(param, click.Option):
            if not has_opts:
                click.echo("\nOptions:")
                has_opts = True
            
            # Get the main option name
            opt_names = param.opts + param.secondary_opts
            opt_line = f"  {', '.join(opt_names)}"
            
            if not param.is_flag:
                type_name = getattr(param.type, 'name', 'value')
                opt_line += f" <{type_name}>"
            
            if param.help:
                opt_line += f" - {param.help}"
            
            if param.default is not None and not param.is_flag:
                opt_line += f" (default: {param.default})"
            
            click.echo(opt_line)
    
    click.echo()


def execute_command(cli_group, ctx, command):
    """Execute a command in the CLI."""
    args = command.split()
    if not args:
        return
        
    cmd_name = args[0]
    cmd_args = args[1:]
    
    # Find and invoke the command
    cmd = cli_group.commands.get(cmd_name)
    if cmd and cmd_name != 'interactive':
        try:
            # Create a new context for the command
            sub_ctx = click.Context(cmd, parent=ctx, info_name=cmd_name)
            sub_ctx.obj = ctx.obj  # Pass along the context object
            
            # Parse the arguments for the command
            parser = cmd.make_parser(sub_ctx)
            opts, args, order = parser.parse_args(args=cmd_args)
            
            # Invoke the command with parsed arguments
            sub_ctx.params = opts
            cmd.invoke(sub_ctx, **opts)
        except click.ClickException as e:
            e.show()
        except Exception as e:
            click.echo(f"Error: {e}")
    else:
        if cmd_name != 'interactive':
            click.echo(f"Unknown command: {cmd_name}. Type 'help' for available commands.")
            
            # Suggest similar commands
            similar = [c for c in cli_group.commands.keys() 
                      if c.startswith(cmd_name[:2]) and c != 'interactive']
            if similar:
                click.echo(f"Did you mean: {', '.join(similar[:3])}?")