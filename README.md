# Console Share

A Python utility to proxy Incus container and VM consoles to TCP ports using websocat.

## Features

- Supports both container console and VM VGA/SPICE console
- Configurable via INI file
- Multiple console proxies can run simultaneously
- Automatic retry on connection failures
- SSL certificate support for secure connections
- Automatic instance type detection (VM vs Container)
- Auto-configuration generation from existing Incus setup
- Smart network interface detection
- Tabulated instance listing with connection commands
- Robust error handling with automatic retries
- DNS caching for improved performance

## Prerequisites

- Python 3.7 or higher
- Incus installed and configured
- websocat binary (included in the package, source: https://github.com/vi/websocat)

## Installation

### From Git Repository

```bash
pip install git+https://github.com/RIT-GCI/console-share
```

### Using pipx (recommended)

```bash
pipx install console-share
```

### Using pip

```bash
pip install console-share
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

[proxy2]
instance = my-vm
port = 8002
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

## Usage

1. Auto-generate config from your current Incus setup:
```bash
console-share --generate
```

Or create default config:
```bash
console-share --create-config
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
- The proxy will automatically retry on connection failures (max 3 retries with 5 second delay)
- Multiple instances can be proxied simultaneously using different ports
- Instance type (VM/Container) is automatically detected
- Network interfaces are automatically detected for proper IP address display
- Connection information is displayed in a neat table format

## License

MIT License

## Disclaimer

⚠️ WARNING: This code was lovingly crafted by an AI that occasionally dreams of electric sheep, powered by $40 worth of Claude API tokens and a dream. While it mostly works, it may occasionally decide to take a coffee break or contemplate the meaning of life. Our rigorous testing process consists entirely of unsuspecting students who will discover bugs in real-time during their assignments (surprise!). Side effects may include unexpected behavior, spontaneous poetry generation, and a slight tendency to catch fire when Mercury is in retrograde. If you're reading this, congratulations! You're now part of our "involuntary beta testing program." Remember: every crash is not a bug, it's a feature waiting to be documented. Use at your own risk, and keep a fire extinguisher handy. No students were harmed in the making of this software (yet). 🔥🤖📚
