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
        url = f"{scheme}://{host}/1.0{path}"
        logger.debug(f"API {method} request to: {url}")
        
        async with aiohttp.ClientSession() as session:
            async with session.request(method, url, json=data, ssl=ssl_context) as response:
                response_data = await response.json()
                if response.status in [200, 202]:
                    return response_data
                else:
                    raise Exception(f"HTTP {response.status}: {await response.text()}")

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
            # Handle TCP connection
            if ':' not in host:
                host = f"{host}:8443"
            ws_url = f"wss://{host}/1.0/operations/{operation_id}/websocket?secret={console_secret}&project={self.project}"

        # Build the command with proper SSL handling
        cmd = [
            WEBSOCAT_PATH,
            "--insecure",  # insecure SSL for self-signed certs
        ]

        # Add container-specific options for better PTY handling
        if self.is_container:
            cmd.extend([
                "--text",  # text mode for console
                "--async-stdio",  # better terminal handling
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

    async def start_all(self):
        """Start all proxy instances"""
        tasks = []
        for proxy in self.proxies:
            tasks.append(asyncio.create_task(proxy.start_proxy()))
        await asyncio.gather(*tasks)

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

def main():
    parser = argparse.ArgumentParser(description='Proxy Incus console to TCP using websocat4')
    parser.add_argument('--config', default=DEFAULT_CONFIG_PATH, help=f'Config file path (default: {DEFAULT_CONFIG_PATH})')
    parser.add_argument('--create-config', action='store_true', help='Create default config file')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    args = parser.parse_args()

    if args.debug:
        logger.setLevel(logging.DEBUG)

    if args.create_config:
        create_default_config()

    try:
        # Create and start proxy manager
        manager = ProxyManager(args.config)
        manager.load_config()
        asyncio.run(manager.start_all())
    except KeyboardInterrupt:
        logger.info("\nShutting down...")
    except FileNotFoundError as e:
        logger.error(f"Error: {e}")
        logger.info("Use --create-config to create a default configuration file")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
