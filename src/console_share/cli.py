import click
import sys
from typing import Optional
from .config import Config
from .incus import get_instance, is_running, list_instances, IncusError
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
                instances = list_instances()
                config.generate_config(instances)
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
@click.pass_context
def start(ctx):
    """Start proxies for all enabled instances in config."""
    config: Config = ctx.obj['config']
    proxy: Proxy = ctx.obj['proxy']
    
    enabled_instances = config.list_enabled_instances()
    if not enabled_instances:
        click.echo("No enabled instances found in config")
        sys.exit(1)
    
    for instance_name in enabled_instances:
        try:
            instance = get_instance(instance_name)
            if not instance:
                click.echo(f"Instance {instance_name} not found, skipping")
                continue
            
            if not is_running(instance):
                click.echo(f"Instance {instance_name} is not running, skipping")
                continue
            
            instance_config = config.get_instance_config(instance_name)
            if not instance_config:
                click.echo(f"No config found for {instance_name}, skipping")
                continue
            
            if instance_config["type"] == "vga":
                port = proxy.proxy_console(instance, vga=True, port=instance_config.get("port"))
                click.echo(f"VGA console proxy started for {instance_name}")
                click.echo(f"Connect using: nc {config.bind_address} {port}")
                click.echo("Note: VGA console requires a SPICE client")
            elif instance_config["type"] == "shell":
                port = proxy.proxy_shell(instance, port=instance_config.get("port"))
                click.echo(f"Shell proxy started for {instance_name}")
                click.echo(f"Connect using: nc {config.bind_address} {port}")
            
        except (IncusError, ProxyError) as e:
            click.echo(f"Error starting proxy for {instance_name}: {e}")
    
    click.echo("\nAll proxies started. Press Ctrl+C to stop.")
    try:
        # Wait for any proxy to exit
        while any(p.poll() is None for p in proxy.active_proxies.values()):
            import time
            time.sleep(1)
    except KeyboardInterrupt:
        click.echo("\nStopping all proxies...")
        for instance_name in enabled_instances:
            proxy.stop_proxy(instance_name)

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

def main():
    """Entry point for the CLI."""
    cli(obj={})

if __name__ == '__main__':
    main()
