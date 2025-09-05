"""Interactive mode with autocomplete and intellisense for scopinator CLI."""

import readline
import rlcompleter
import click
from typing import List, Optional, Dict, Any
from scopinator.util.logging_config import get_logger
logger = get_logger(__name__)


class ScopinatorCompleter:
    """Custom completer for scopinator interactive mode."""
    
    def __init__(self, cli_group):
        self.cli_group = cli_group
        self.commands = {}
        self.current_command = None
        self.parse_commands()
        
    def parse_commands(self):
        """Parse all available commands and their parameters."""
        for name, cmd in self.cli_group.commands.items():
            if name != 'interactive':  # Skip the interactive command itself
                self.commands[name] = {
                    'obj': cmd,
                    'params': [],
                    'options': {},
                    'help': cmd.help or cmd.short_help or ""
                }
                
                # Parse parameters and options
                for param in cmd.params:
                    if isinstance(param, click.Option):
                        opt_names = param.opts + param.secondary_opts
                        for opt_name in opt_names:
                            self.commands[name]['options'][opt_name] = {
                                'type': param.type,
                                'help': param.help or "",
                                'required': param.required,
                                'default': param.default,
                                'multiple': param.multiple,
                                'is_flag': param.is_flag
                            }
                    elif isinstance(param, click.Argument):
                        self.commands[name]['params'].append({
                            'name': param.name,
                            'type': param.type,
                            'required': param.required,
                            'nargs': param.nargs
                        })
    
    def get_command_hints(self, command: str) -> str:
        """Get parameter hints for a command."""
        if command not in self.commands:
            return ""
        
        cmd_info = self.commands[command]
        hints = []
        
        # Add required arguments
        for param in cmd_info['params']:
            param_str = f"<{param['name']}>"
            if not param.get('required', True):
                param_str = f"[{param['name']}]"
            hints.append(param_str)
        
        # Add key options
        important_opts = []
        for opt_name, opt_info in cmd_info['options'].items():
            if len(opt_name) <= 3:  # Short options
                if opt_info.get('required'):
                    important_opts.append(f"{opt_name} <value>")
                elif opt_info.get('is_flag'):
                    important_opts.append(f"[{opt_name}]")
        
        if important_opts:
            hints.extend(important_opts[:3])  # Show max 3 options
        
        return " ".join(hints) if hints else ""
    
    def complete(self, text: str, state: int) -> Optional[str]:
        """Readline completer function."""
        # Get the current line buffer
        buffer = readline.get_line_buffer()
        line = buffer.lstrip()
        
        # If we're at the beginning, complete command names
        if not line or line == text:
            matches = [cmd + ' ' for cmd in self.commands.keys() 
                      if cmd.startswith(text)]
            # Add special commands
            special = ['help', 'exit', 'quit', 'clear']
            matches.extend([s + ' ' for s in special if s.startswith(text)])
        else:
            # Parse what command we're working with
            parts = line.split()
            if parts:
                cmd_name = parts[0]
                
                # If this is a known command, provide option completion
                if cmd_name in self.commands:
                    matches = self.complete_command_options(cmd_name, text, parts)
                else:
                    matches = []
            else:
                matches = []
        
        # Return the state-th match
        if state < len(matches):
            return matches[state]
        return None
    
    def complete_command_options(self, cmd_name: str, text: str, parts: List[str]) -> List[str]:
        """Complete options for a specific command."""
        cmd_info = self.commands[cmd_name]
        matches = []
        
        # Get all option names that haven't been used yet
        used_options = set()
        for part in parts[1:]:
            if part.startswith('-'):
                used_options.add(part.split('=')[0])
        
        # Complete option names
        for opt_name in cmd_info['options'].keys():
            if opt_name not in used_options and opt_name.startswith(text):
                if cmd_info['options'][opt_name].get('is_flag'):
                    matches.append(opt_name + ' ')
                else:
                    matches.append(opt_name + '=')
        
        # If completing after an option that needs a value
        if len(parts) >= 2 and parts[-2].startswith('-'):
            opt_name = parts[-2].split('=')[0]
            if opt_name in cmd_info['options']:
                opt_info = cmd_info['options'][opt_name]
                # Provide type-specific suggestions
                if opt_info['type'] == click.INT:
                    matches = ['4700 ', '4800 ', '4900 ']  # Port suggestions
                elif isinstance(opt_info['type'], click.Choice):
                    matches = [c + ' ' for c in opt_info['type'].choices 
                              if c.startswith(text)]
        
        return matches


class InteractiveMode:
    """Enhanced interactive mode with autocomplete."""
    
    def __init__(self, cli_group, ctx):
        self.cli_group = cli_group
        self.ctx = ctx
        self.completer = ScopinatorCompleter(cli_group)
        self.setup_readline()
        
    def setup_readline(self):
        """Configure readline for autocomplete and history."""
        # Set up tab completion
        readline.set_completer(self.completer.complete)
        readline.parse_and_bind('tab: complete')
        
        # Set up history
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
        
        # Configure completion display
        readline.set_completer_delims(' \t\n=')
        readline.set_completion_display_matches_hook(self.display_matches)
    
    def display_matches(self, substitution: str, matches: List[str], longest_match_length: int):
        """Custom display for completion matches."""
        click.echo()
        if len(matches) > 1:
            # Group and display matches
            click.echo("Available completions:")
            for match in sorted(matches):
                # Clean up the match display
                display_match = match.rstrip()
                
                # Check if this is a command and add help text
                cmd_name = display_match.split()[0] if display_match else ""
                if cmd_name in self.completer.commands:
                    help_text = self.completer.commands[cmd_name]['help']
                    if help_text:
                        click.echo(f"  {display_match:<20} - {help_text[:50]}")
                    else:
                        click.echo(f"  {display_match}")
                else:
                    click.echo(f"  {display_match}")
        
        # Redisplay the prompt and current input
        click.echo()
        current_input = readline.get_line_buffer()
        click.echo(f"scopinator> {current_input}", nl=False)
    
    def show_command_help(self, cmd_name: str):
        """Show detailed help for a specific command."""
        if cmd_name in self.completer.commands:
            cmd_info = self.completer.commands[cmd_name]
            cmd = cmd_info['obj']
            
            click.echo(f"\n{click.style(cmd_name, bold=True)} - {cmd_info['help']}")
            
            # Show usage
            usage_parts = [cmd_name]
            hints = self.completer.get_command_hints(cmd_name)
            if hints:
                usage_parts.append(hints)
            click.echo(f"Usage: {' '.join(usage_parts)}")
            
            # Show parameters
            if cmd_info['params']:
                click.echo("\nArguments:")
                for param in cmd_info['params']:
                    param_line = f"  {param['name']}"
                    if param['type']:
                        param_line += f" ({param['type'].name})"
                    if not param.get('required', True):
                        param_line += " [optional]"
                    click.echo(param_line)
            
            # Show options
            if cmd_info['options']:
                click.echo("\nOptions:")
                for opt_name, opt_info in cmd_info['options'].items():
                    if opt_name.startswith('--'):
                        opt_line = f"  {opt_name}"
                        if not opt_info.get('is_flag'):
                            opt_line += f" <{opt_info['type'].name if hasattr(opt_info['type'], 'name') else 'value'}>"
                        if opt_info['help']:
                            opt_line += f" - {opt_info['help']}"
                        click.echo(opt_line)
            click.echo()
        else:
            click.echo(f"Unknown command: {cmd_name}")
    
    def run(self):
        """Run the interactive mode loop."""
        click.echo("Welcome to Scopinator Interactive Mode!")
        click.echo("Type 'help' for commands, Tab for autocomplete, 'exit' to quit.\n")
        
        while True:
            try:
                # Use readline-enabled input
                command = input(click.style("scopinator> ", fg='green', bold=True))
                
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
                    self.show_general_help()
                    continue
                elif command.lower().startswith('help '):
                    # Help for specific command
                    cmd_name = command[5:].strip()
                    self.show_command_help(cmd_name)
                    continue
                
                # Parse and execute command
                self.execute_command(command)
                    
            except (KeyboardInterrupt, EOFError):
                click.echo("\nGoodbye!")
                break
            except Exception as e:
                logger.error(f"Interactive mode error: {e}")
                click.echo(f"Error: {e}")
    
    def show_general_help(self):
        """Show general help information."""
        click.echo("\n" + click.style("Available Commands:", bold=True))
        
        # Group commands by category
        categories = {
            'Discovery': ['discover'],
            'Connection': ['connect', 'status'],
            'Control': ['park', 'goto'],
            'Imaging': ['stream'],
            'System': ['version', 'help', 'clear', 'exit']
        }
        
        for category, cmds in categories.items():
            click.echo(f"\n{click.style(category, fg='cyan')}:")
            for cmd_name in cmds:
                if cmd_name in self.completer.commands:
                    cmd_info = self.completer.commands[cmd_name]
                    hints = self.completer.get_command_hints(cmd_name)
                    usage = f"{cmd_name} {hints}".strip()
                    click.echo(f"  {usage:<30} - {cmd_info['help'][:40]}")
                elif cmd_name in ['help', 'clear', 'exit']:
                    helps = {
                        'help': 'Show this help or help for a command',
                        'clear': 'Clear the screen',
                        'exit': 'Exit interactive mode'
                    }
                    click.echo(f"  {cmd_name:<30} - {helps[cmd_name]}")
        
        click.echo(f"\n{click.style('Tips:', bold=True)}")
        click.echo("  • Use Tab for command and option completion")
        click.echo("  • Use arrow keys to navigate command history")  
        click.echo("  • Type 'help <command>' for detailed command help")
        click.echo()
    
    def execute_command(self, command: str):
        """Execute a command in the CLI."""
        args = command.split()
        if not args:
            return
            
        cmd_name = args[0]
        cmd_args = args[1:]
        
        # Find and invoke the command
        cmd = self.cli_group.commands.get(cmd_name)
        if cmd and cmd_name != 'interactive':
            try:
                # Create a new context for the command
                sub_ctx = click.Context(cmd, parent=self.ctx, info_name=cmd_name)
                sub_ctx.obj = self.ctx.obj  # Pass along the context object
                
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
                similar = [c for c in self.completer.commands.keys() 
                          if c.startswith(cmd_name[:2])]
                if similar:
                    click.echo(f"Did you mean: {', '.join(similar[:3])}?")