# Console Share

A network proxy tool for Incus console and shell connections.

## Features

- Proxy Incus shell connections
- Proxy Incus console connections (both VGA and regular)
- Network forwarding of local Unix sockets
- Configurable proxy settings
- PATH manipulation for VGA console support

## Installation

```bash
# Install directly from GitHub
pip install git+https://github.com/jetbalsa/console-share.git

# Or with pipx for isolated installation
pipx install git+https://github.com/jetbalsa/console-share.git
```

## Configuration

You can automatically generate a configuration file based on your current Incus instances:

```bash
console-share --generate
```

This will create a config file at `~/.config/console-share/config.toml` with appropriate connection types for each instance (VGA console for virtual machines, shell for containers).

Example generated config:

```toml
[proxy]
# Bind address for proxied connections
bind_address = "0.0.0.0"
# Starting port for proxy connections
start_port = 8000

[console]
# Directory for temporary unix sockets
socket_dir = "/tmp/console-share"
# Path to fake remote-viewer binary
remote_viewer_path = "/tmp/console-share/bin"

[shell]
# Default terminal type
term = "xterm-256color"

[instances]
# Auto-generated instance configurations
"ubuntu-vm" = { type = "vga", port = null, enabled = true }
"alpine-container" = { type = "shell", port = null, enabled = true }
```

The configuration is generated based on your current project and remote settings, and automatically detects the appropriate connection type for each instance.

## Usage

```bash
# Proxy a shell connection
console-share shell <instance>

# Proxy a console connection
console-share console <instance>

# Proxy a VGA console connection
console-share console <instance> --vga

# List active proxy connections
console-share list
```

## How it Works

The tool intercepts Incus console and shell connections to enable network proxying:

### Shell Connections
Uses socat to forward the Incus shell connection over TCP, allowing remote access via standard terminal clients.

### Console Connections
- Regular console: Directly forwards the console connection using socat's exec feature
- VGA console: Intercepts the remote-viewer command by injecting a PATH override, captures the Unix socket, and forwards it over TCP

### Implementation Details

1. Incus data is gathered using CSV output format (`incus -f csv`) for reliable parsing
2. Default project and remote are auto-detected by looking for "(current)" marker in command output
3. VGA console handling:
   - Creates a fake remote-viewer script in a temporary directory
   - Uses PATH manipulation to intercept incus's remote-viewer call
   - Captures the Unix socket path from the intercepted command
   - Forwards the socket using socat for network access
4. Shell and regular console connections:
   - Direct socat forwarding using EXEC mode
   - PTY allocation for proper terminal handling
   - Signal passing for CTRL+C support
5. Configuration:
   - TOML-based configuration file
   - XDG compliant config location
   - Automatic port allocation
   - Customizable bind address and socket directories

## Requirements

- Python 3.8+
- Incus CLI
- socat
- netcat (optional, for testing)

## Development

```bash
# Clone the repository
git clone https://github.com/jetbalsa/console-share.git
cd console-share

# Install in development mode
pip install -e .

# Run tests
pytest
```

## Contributing

Pull requests are welcome! Please feel free to submit issues and enhancement requests.

## Prompt History

```
1.0:
Lets make a new project in python, Its going to use the incus command line to get all its data, use incus -f csv for it all, youll get better data, for project and remote you can detect the default if they have the word (current) in them, you can run these commands in the shell to get their outputs now. 

in the python script have a config file we can use to setup proxies for incus console and incus shell, using socat, you are going to have to trick incus console --type=vga for virtual-machines into using a fake remote-viewer so it will drop its unix socket on the system and work from there, this program is going to work by taking those unix sockets and publishing them using socat to the network. 

right now its going the golang findCommand function to do this, find a good way to spoof this, you can run bash commands to test these out as well, maybe a PATH injection or reset would work for this. don't forget, I want this to run via pipx so make a toml for the project and a readme outlining everything I want, I want the python program to be able to proxy incus shell, incus console of both types, if its not a --type=vga on incus console, just use socat exec directly for console connections over telnet.

1.1:
update it to allow for a autogeneretion of a config, using --generate take the current active project and remote (so no switching) look at all the instances and set --type=vga for all VIRTUAL-MACHINES and incus shell for containers and write it out to disk

```
