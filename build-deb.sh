#!/bin/bash
set -euo pipefail

# Ensure we have the required tools
if ! command -v dpkg-buildpackage >/dev/null 2>&1; then
    echo "Error: dpkg-buildpackage not found. Please install build-essential and devscripts packages."
    exit 1
fi

# Make scripts executable
chmod +x console-share console-vga-proxy

# Build the package
dpkg-buildpackage -b -us -uc

# Move the .deb file to the current directory
mv ../console-share_*.deb .

echo "Package built successfully!"
echo "You can install it with: sudo dpkg -i console-share_*.deb"
