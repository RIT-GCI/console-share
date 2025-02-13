# Console Share

A Python utility to proxy Incus container and VM consoles to TCP ports using websocat.

## Features

- Supports both container console and VM VGA/SPICE console
- Configurable via INI file
- Multiple console proxies can run simultaneously
- Automatic retry on connection failures
- SSL certificate support for secure connections
- Auto-generation of configuration from current Incus setup

## Prerequisites

- Python 3.7 or higher
- Incus installed and configured
- websocat binary (included in the package, source: https://github.com/vi/websocat)

## Installation

### Using pipx (recommended)

```bash
pipx install console-share
```

### Using pip

```bash
pip install https://pypi.org/project/console-share
```

## Configuration

Create a configuration file (default: `console-share.ini`):

```ini
[global]
remote = unix:/var/lib/incus/unix.socket
project = default

[proxy1]
instance = my-container
port = 8001
console_type = shell

[proxy2]
instance = my-vm
port = 8002
console_type = vga
```

### Configuration Options

#### Global Section
- `remote`: Incus remote (default: unix:/var/lib/incus/unix.socket)
- `project`: Incus project (default: default)

#### Proxy Sections
- `instance`: Name of the Incus instance
- `port`: TCP port to listen on
- `remote`: (optional) Override global remote
- `project`: (optional) Override global project
- `console_type`: (optional) Type of console to use
  - For containers: `shell` (default) or `console`
    - `shell`: Uses incus exec to provide a shell (recommended)
    - `console`: Uses incus console for direct console access
  - For VMs: `vga` (default) or `shell`
    - `vga`: Uses SPICE/VGA console (recommended for VMs)
    - `shell`: Uses incus exec to provide a shell

## Usage

1. Create a configuration file:
   - Create default config:
   ```bash
   console-share --create-config
   ```
   - Or auto-generate from current Incus setup:
   ```bash
   console-share --generate
   ```

2. Edit the config file with your instance settings

3. Run the proxy:
```bash
console-share
```

Additional options:
- `--config`: Specify custom config file path
- `--debug`: Enable debug logging

## Accessing Consoles

### For Containers
Use telnet to connect to the proxy port:
```bash
telnet localhost <port>
```

### For VMs
Use remote-viewer to connect to the SPICE console:
```bash
remote-viewer spice://localhost:<port>
```

## Notes

- The websocat binary is included in the package and does not need to be downloaded separately
- SSL certificates for Incus are automatically used if found in ~/.config/incus/
- The proxy will automatically retry on connection failures
- Multiple instances can be proxied simultaneously using different ports

## License

MIT License
