#!/usr/bin/env python3
import argparse
import asyncio
import json
import logging
import os
import ssl
import sys
import aiohttp
import subprocess
from pathlib import Path
import urllib.parse
import hashlib
import configparser
import time
import socket
from tabulate import tabulate

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('console-share.log')
    ]
)
logger = logging.getLogger(__name__)

WEBSOCAT_PATH = os.path.join(os.path.dirname(__file__), "websocat_max.x86_64-unknown-linux-musl")
DEFAULT_CONFIG_PATH = "console-share.ini"
MAX_RETRIES = 3
RETRY_DELAY = 5  # seconds

class IncusConsoleProxy:
    def __init__(self, remote, project, instance, port):
        self.remote = remote or "unix:/var/lib/incus/unix.socket"
        self.project = project or "default"
        self.instance = instance
        self.listen_port = port
        self.cert_path = str(Path.home() / ".config/incus/client.crt")
        self.key_path = str(Path.home() / ".config/incus/client.key")
        self.is_container = None
        self.retry_count = 0

    def get_scheme_and_host(self):
        """Get scheme and host based on remote type"""
        if self.remote.startswith("unix:"):
            socket_path = self.remote[5:]
            return "https+unix", f"{socket_path}:/"
        else:
            # Handle URLs that already have a scheme
            if self.remote.startswith(("http://", "https://")):
                # Remove scheme and get host part
                host = self.remote.split("://")[1]
                return "https", host
            else:
                # No scheme provided, add default port if needed
                if ':' not in self.remote:
                    return "https", f"{self.remote}:8443"
                return "https", self.remote

    async def api_request(self, method, path, data=None):
        """Make an HTTP request to the Incus API"""
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        if os.path.exists(self.cert_path) and os.path.exists(self.key_path):
            ssl_context.load_cert_chain(self.cert_path, self.key_path)

        scheme, host = self.get_scheme_and_host()
        # For unix socket connections
        if scheme == "https+unix":
            url = f"{scheme}://{host}/1.0{path}"
        else:
            # For HTTPS connections, ensure we don't duplicate the scheme
            url = f"https://{host}/1.0{path}"
        logger.debug(f"API {method} request to: {url}")
        
        # Configure TCP connector with custom DNS cache parameters
        connector = aiohttp.TCPConnector(
            ssl=ssl_context,
            ttl_dns_cache=300,  # Cache DNS results for 5 minutes
            use_dns_cache=True,  # Enable DNS caching
            force_close=True     # Ensure connections are closed properly
        )
        
        async with aiohttp.ClientSession(connector=connector) as session:
            try:
                async with session.request(method, url, json=data) as response:
                    response_data = await response.json()
                    if response.status in [200, 202]:
                        return response_data
                    else:
                        raise Exception(f"HTTP {response.status}: {await response.text()}")
            except aiohttp.ClientConnectorError as e:
                if "Name or service not known" in str(e) or "Temporary failure in name resolution" in str(e):
                    logger.error(f"DNS resolution error for {url}: {e}")
                    logger.info("Please check your network connection and DNS settings")
                    raise Exception(f"DNS resolution failed for {url}. Check network/DNS settings.")
                else:
                    logger.error(f"Connection error for {url}: {e}")
                    raise Exception(f"Failed to connect to {url}: {e}")
            except aiohttp.ClientError as e:
                logger.error(f"HTTP client error for {url}: {e}")
                raise Exception(f"HTTP client error: {e}")

    async def get_instance_info(self):
        """Get instance information from Incus API"""
        try:
            response = await self.api_request("GET", f"/instances/{self.instance}?project={self.project}")
            return response.get("metadata", {})
        except Exception as e:
            logger.error(f"Failed to get instance info: {e}")
            raise

    async def determine_instance_type(self):
        """Determine if instance is a container or VM"""
        try:
            info = await self.get_instance_info()
            instance_type = info.get("type", "")
            
            if instance_type == "virtual-machine":
                self.is_container = False
                logger.info(f"[{self.instance}] VM detected - using SPICE/VGA console")
            else:
                self.is_container = True
                logger.info(f"[{self.instance}] Container detected - using text console")
        except Exception as e:
            logger.error(f"[{self.instance}] Error determining instance type: {e}")
            logger.info(f"[{self.instance}] Defaulting to container console")
            self.is_container = True

    async def create_console(self):
        """Create a new console session"""
        if self.is_container is None:
            await self.determine_instance_type()
            
        # Different console type for VMs vs containers
        if self.is_container:
            data = {
                "width": 80,
                "height": 25,
                "type": "console",
                "force": True
            }
        else:
            data = {
                "width": 1024,
                "height": 768,
                "type": "vga",
                "force": True
            }
            
        try:
            response = await self.api_request(
                "POST",
                f"/instances/{self.instance}/console?project={self.project}",
                data=data
            )
            
            operation = response.get("operation")
            metadata = response.get("metadata", {})
            fds = metadata.get("metadata", {}).get("fds", {})
            
            console_secret = fds.get("0")
            control_secret = fds.get("control")
            
            if not console_secret or not control_secret:
                raise Exception("Failed to get console secrets")
                
            operation_id = operation.split("/")[-1]
            return operation_id, console_secret, control_secret
        except Exception as e:
            logger.error(f"[{self.instance}] Failed to create console: {e}")
            raise

    def get_websocat_command(self, operation_id, console_secret):
        """Generate websocat command for the connection"""
        scheme, host = self.get_scheme_and_host()
        
        # Handle unix socket
        if scheme == "https+unix":
            unix_path = host.split(":/")[0]
            ws_url = f"ws+unix:{unix_path}:/1.0/operations/{operation_id}/websocket?secret={console_secret}&project={self.project}"
        else:
            # For HTTPS connections, use the host directly since it's already properly formatted
            ws_url = f"wss://{host}/1.0/operations/{operation_id}/websocket?secret={console_secret}&project={self.project}"

        # Build the command with proper SSL handling
        cmd = [
            WEBSOCAT_PATH,
            "--insecure",  # insecure SSL for self-signed certs
        ]

        # Add container-specific options for better PTY handling
        if self.is_container:
            cmd.extend([
                "--binary",  # text mode for console
                "--exit-on-eof",  # proper disconnect handling
            ])
        else:
            cmd.extend([
                "--binary",  # binary mode for VMs
                "--exit-on-eof",  # Exit on endpoint disconnect
            ])
        
        # Add client certificate and key if they exist
        if os.path.exists(self.cert_path) and os.path.exists(self.key_path):
            cmd.extend(["--client-pkcs12-der", self.cert_path])
            
        # Add endpoints last
        cmd.extend([
            f"tcp-listen:0.0.0.0:{self.listen_port}",  # TCP listen endpoint
            ws_url  # WebSocket URL endpoint
        ])
            
        return cmd

    async def start_proxy(self):
        """Start the websocat proxy with retry logic"""
        while True:
            try:
                # Determine instance type
                if self.is_container is None:
                    await self.determine_instance_type()

                # Create console session
                operation_id, console_secret, control_secret = await self.create_console()
                
                # Build websocat command
                cmd = self.get_websocat_command(operation_id, console_secret)
                logger.info(f"[{self.instance}] Starting websocat proxy: {' '.join(cmd)}")
                
                # Start websocat process
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                
                logger.info(f"[{self.instance}] Proxy started on 0.0.0.0:{self.listen_port}")
                if self.is_container:
                    logger.info(f"[{self.instance}] Use: telnet localhost {self.listen_port}")
                else:
                    logger.info(f"[{self.instance}] Use: remote-viewer spice://localhost:{self.listen_port}")
                
                # Reset retry count on successful start
                self.retry_count = 0
                
                # Monitor the process
                while True:
                    if process.stdout:
                        data = await process.stdout.readline()
                        if data:
                            logger.debug(f"[{self.instance}] websocat stdout: {data.decode().strip()}")
                    if process.stderr:
                        data = await process.stderr.readline()
                        if data:
                            logger.error(f"[{self.instance}] websocat stderr: {data.decode().strip()}")
                    
                    # Check if process is still running
                    if process.returncode is not None:
                        raise Exception(f"Proxy process exited with code {process.returncode}")
                    
                    await asyncio.sleep(0.1)
            
            except asyncio.CancelledError:
                logger.info(f"[{self.instance}] Shutting down proxy...")
                if 'process' in locals():
                    process.terminate()
                    await process.wait()
                break
            
            except Exception as e:
                logger.error(f"[{self.instance}] Error in proxy: {e}")
                if 'process' in locals():
                    process.terminate()
                    await process.wait()
                
                self.retry_count += 1
                if self.retry_count > MAX_RETRIES:
                    logger.error(f"[{self.instance}] Max retries ({MAX_RETRIES}) exceeded, stopping proxy")
                    break
                
                logger.info(f"[{self.instance}] Retrying in {RETRY_DELAY} seconds... (attempt {self.retry_count}/{MAX_RETRIES})")
                await asyncio.sleep(RETRY_DELAY)

class ProxyManager:
    def __init__(self, config_path=DEFAULT_CONFIG_PATH):
        self.config_path = config_path
        self.config = configparser.ConfigParser()
        self.proxies = []

    def load_config(self):
        """Load configuration from INI file"""
        if not os.path.exists(self.config_path):
            raise FileNotFoundError(f"Config file not found: {self.config_path}")
        
        self.config.read(self.config_path)
        
        # Get global settings
        global_settings = self.config['global'] if 'global' in self.config else {}
        default_remote = global_settings.get('remote', "unix:/var/lib/incus/unix.socket")
        default_project = global_settings.get('project', "default")
        
        # Create proxy instances for each mapping
        for section in self.config.sections():
            if section != 'global':
                instance = self.config[section].get('instance')
                port = self.config[section].getint('port')
                remote = self.config[section].get('remote', default_remote)
                project = self.config[section].get('project', default_project)
                
                if instance and port:
                    proxy = IncusConsoleProxy(remote, project, instance, port)
                    self.proxies.append(proxy)

    def get_local_ip(self):
        """Get the local IP address of the main network interface"""
        try:
            # Create a socket and connect to a public DNS to determine local IP
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
            return local_ip
        except Exception:
            return "127.0.0.1"  # Fallback to localhost if unable to determine

    def print_instance_table(self):
        """Print a table of instances and their connection information"""
        local_ip = self.get_local_ip()
        
        # Prepare table data
        table_data = []
        for proxy in self.proxies:
            if proxy.is_container:
                command = f"telnet {local_ip} {proxy.listen_port}"
            else:
                command = f"remote-viewer spice://{local_ip}:{proxy.listen_port}"
            
            table_data.append([
                proxy.instance,
                f"{local_ip}:{proxy.listen_port}",
                "Container" if proxy.is_container else "VM",
                command
            ])
        
        # Print the table
        headers = ["Instance", "Address", "Type", "Connection Command"]
        print("\nConsole Share Instances:")
        print(tabulate(table_data, headers=headers, tablefmt="grid"))
        print()  # Add a blank line after the table

    def cleanup(self):
        """Kill all websocat processes"""
        try:
            subprocess.run(['pkill', '-f', 'websocat_max'], check=False)
            logger.info("Killed all websocat processes")
        except Exception as e:
            logger.error(f"Error killing websocat processes: {e}")

    async def start_all(self):
        """Start all proxy instances"""
        try:
            # Create and start all proxy tasks
            tasks = []
            for proxy in self.proxies:
                tasks.append(asyncio.create_task(proxy.start_proxy()))
            
            # Wait 10 seconds for proxies to initialize
            await asyncio.sleep(2)
            
            # Print instance table
            self.print_instance_table()
            
            # Continue running the tasks
            await asyncio.gather(*tasks)
        finally:
            # Ensure cleanup happens on exit
            self.cleanup()

def get_current_remote():
    """Get the current remote from incus remote ls"""
    try:
        result = subprocess.run(['incus', 'remote', 'ls', '-f', 'csv'], 
                              capture_output=True, text=True, check=True)
        for line in result.stdout.splitlines():
            if '(current)' in line:
                parts = line.split(',')
                remote = parts[0].replace(' (current)', '')
                url = parts[1]
                
                # Handle unix socket
                if not url.startswith(('http://', 'https://')):
                    return "unix:/var/lib/incus/unix.socket"
                
                # Parse URL to handle various formats
                parsed = urllib.parse.urlparse(url)
                host = parsed.netloc or parsed.path  # path for cases without //
                
                # Add scheme if missing
                if not url.startswith(('http://', 'https://')):
                    url = f"https://{host}"
                
                # Add port if missing
                if ':' not in host:
                    url = f"{url}:8443"
                
                return url
                
        return "unix:/var/lib/incus/unix.socket"  # fallback
    except subprocess.CalledProcessError:
        return "unix:/var/lib/incus/unix.socket"  # fallback

def get_default_project():
    """Get the current project from incus project list"""
    try:
        result = subprocess.run(['incus', 'project', 'list', '-f', 'csv'], 
                              capture_output=True, text=True, check=True)
        for line in result.stdout.splitlines():
            if '(current)' in line:
                return line.split(',')[0].replace(' (current)', '')
        return "default"  # fallback
    except subprocess.CalledProcessError:
        return "default"  # fallback

def get_instances():
    """Get list of all instances"""
    try:
        result = subprocess.run(['incus', 'list', '-f', 'csv'], 
                              capture_output=True, text=True, check=True)
        instances = []
        for line in result.stdout.splitlines():
            if line and not line.startswith('NAME,'):  # Skip header
                instance_name = line.split(',')[0]
                instances.append(instance_name)
        return instances
    except subprocess.CalledProcessError:
        return []

def generate_config():
    """Generate configuration file based on current incus setup"""
    if os.path.exists(DEFAULT_CONFIG_PATH):
        logger.warning(f"Config file already exists: {DEFAULT_CONFIG_PATH}")
        response = input("Do you want to overwrite it? (y/N): ")
        if response.lower() != 'y':
            logger.info("Aborted.")
            return

    remote = get_current_remote()
    project = get_default_project()
    instances = get_instances()

    if not instances:
        logger.error("No instances found.")
        return

    config = configparser.ConfigParser()
    config['global'] = {
        'remote': remote,
        'project': project
    }

    # Start port assignments from 8001
    base_port = 8001
    for i, instance in enumerate(instances):
        section = f"proxy{i+1}"
        config[section] = {
            'instance': instance,
            'port': str(base_port + i)
        }

    with open(DEFAULT_CONFIG_PATH, 'w') as f:
        config.write(f)
    
    logger.info(f"Generated config file: {DEFAULT_CONFIG_PATH}")
    logger.info(f"Remote: {remote}")
    logger.info(f"Project: {project}")
    logger.info(f"Configured {len(instances)} instances starting from port {base_port}")

def create_default_config():
    """Create a default configuration file if it doesn't exist"""
    if not os.path.exists(DEFAULT_CONFIG_PATH):
        config = configparser.ConfigParser()
        config['global'] = {
            'remote': 'unix:/var/lib/incus/unix.socket',
            'project': 'default'
        }
        config['proxy1'] = {
            'instance': 'instance-name',
            'port': '8001'
        }
        
        with open(DEFAULT_CONFIG_PATH, 'w') as f:
            config.write(f)
        logger.info(f"Created default config file: {DEFAULT_CONFIG_PATH}")
        logger.info("Please edit the config file with your instance settings")
        sys.exit(0)

def signal_handler(manager):
    """Handle shutdown signals"""
    def _handler(signum, frame):
        logger.info("\nShutting down...")
        manager.cleanup()
        sys.exit(0)
    return _handler

def main():
    parser = argparse.ArgumentParser(description='Proxy Incus console to TCP using websocat4')
    parser.add_argument('--config', default=DEFAULT_CONFIG_PATH, help=f'Config file path (default: {DEFAULT_CONFIG_PATH})')
    parser.add_argument('--create-config', action='store_true', help='Create default config file')
    parser.add_argument('--generate', action='store_true', help='Generate config file from current incus setup')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    args = parser.parse_args()

    if args.debug:
        logger.setLevel(logging.DEBUG)

    if args.generate:
        generate_config()
        sys.exit(0)
    elif args.create_config:
        create_default_config()

    try:
        # Create and start proxy manager
        manager = ProxyManager(args.config)
        manager.load_config()
        
        # Set up signal handlers
        import signal
        handler = signal_handler(manager)
        signal.signal(signal.SIGINT, handler)
        signal.signal(signal.SIGTERM, handler)
        
        asyncio.run(manager.start_all())
    except FileNotFoundError as e:
        logger.error(f"Error: {e}")
        logger.info("Use --create-config to create a default configuration file or use --generate to try and auto-create one for you.")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
