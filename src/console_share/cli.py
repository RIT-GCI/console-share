import click
import sys
from typing import Optional
from .config import Config
from .incus import get_instance, is_running, IncusError
from .proxy import Proxy, ProxyError

@click.group()
@click.option('--generate', is_flag=True, help='Generate config file based on current instances')
@click.pass_context
def cli(ctx, generate):
    """Console Share - Network proxy for Incus console and shell connections."""
    try:
        config = Config()
        
        if generate:
            try:
                from .incus import list_instances
                instances = list_instances()
                new_config = config.generate_config(instances)
                config.save_config(new_config)
                click.echo(f"Generated config file at: {config.config_file}")
                click.echo(f"Found {len(instances)} instances:")
                for instance in instances:
                    conn_type = "VGA console" if instance.type == "virtual-machine" else "Shell"
                    click.echo(f"  - {instance.name} ({conn_type})")
                sys.exit(0)
            except Exception as e:
                click.echo(f"Error generating config: {e}", err=True)
                sys.exit(1)
        
        config.ensure_directories()
        ctx.obj = {
            'config': config,
            'proxy': Proxy(config)
        }
    except Exception as e:
        click.echo(f"Error initializing: {e}", err=True)
        sys.exit(1)

@cli.command()
@click.argument('instance')
@click.option('--port', type=int, help='Port to listen on (default: from config)')
@click.pass_context
def shell(ctx, instance: str, port: Optional[int]):
    """Proxy an Incus shell connection."""
    try:
        inst = get_instance(instance)
        if not inst:
            click.echo(f"Instance {instance} not found", err=True)
            sys.exit(1)
        
        if not is_running(inst):
            click.echo(f"Instance {instance} is not running", err=True)
            sys.exit(1)
        
        proxy: Proxy = ctx.obj['proxy']
        port = proxy.proxy_shell(inst, port)
        click.echo(f"Shell proxy started for {instance}")
        click.echo(f"Connect using: nc {ctx.obj['config'].bind_address} {port}")
        
        # Keep running until interrupted
        try:
            proxy.active_proxies[f"shell_{instance}"].wait()
        except KeyboardInterrupt:
            click.echo("\nStopping shell proxy...")
            proxy.stop_proxy(instance, "shell")
            
    except (IncusError, ProxyError) as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

@cli.command()
@click.argument('instance')
@click.option('--vga', is_flag=True, help='Use VGA console for virtual machines')
@click.option('--port', type=int, help='Port to listen on (default: from config)')
@click.pass_context
def console(ctx, instance: str, vga: bool, port: Optional[int]):
    """Proxy an Incus console connection."""
    try:
        inst = get_instance(instance)
        if not inst:
            click.echo(f"Instance {instance} not found", err=True)
            sys.exit(1)
        
        if not is_running(inst):
            click.echo(f"Instance {instance} is not running", err=True)
            sys.exit(1)
        
        proxy: Proxy = ctx.obj['proxy']
        port = proxy.proxy_console(inst, vga, port)
        
        click.echo(f"Console proxy started for {instance}")
        if vga:
            click.echo(f"Connect using: nc {ctx.obj['config'].bind_address} {port}")
            click.echo("Note: VGA console requires a SPICE client")
        else:
            click.echo(f"Connect using: nc {ctx.obj['config'].bind_address} {port}")
        
        # Keep running until interrupted
        try:
            proxy_key = f"vga_{instance}" if vga else f"console_{instance}"
            proxy.active_proxies[proxy_key].wait()
        except KeyboardInterrupt:
            click.echo("\nStopping console proxy...")
            proxy.stop_proxy(instance, "vga" if vga else "console")
            
    except (IncusError, ProxyError) as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

@cli.command()
@click.pass_context
def list(ctx):
    """List active proxy connections."""
    proxy: Proxy = ctx.obj['proxy']
    active = proxy.list_active()
    
    if not active:
        click.echo("No active proxy connections")
        return
    
    click.echo("Active proxy connections:")
    for key, info in active.items():
        click.echo(f"  {info['type']}: {info['instance']} (PID: {info['pid']})")

@cli.command()
@click.argument('instance')
@click.option('--type', 'proxy_type', type=click.Choice(['shell', 'console', 'vga', 'all']),
              default='all', help='Type of proxy to stop')
@click.pass_context
def stop(ctx, instance: str, proxy_type: str):
    """Stop proxy connections for an instance."""
    try:
        proxy: Proxy = ctx.obj['proxy']
        proxy.stop_proxy(instance, proxy_type)
        click.echo(f"Stopped {proxy_type} proxy for {instance}")
    except Exception as e:
        click.echo(f"Error stopping proxy: {e}", err=True)
        sys.exit(1)

def main():
    """Entry point for the CLI."""
    cli(obj={})

if __name__ == '__main__':
    main()
