#!/bin/bash
# WanderWall Installation Script
# Run this on a fresh Pi after cloning the repo

set -euo pipefail

echo "==================================="
echo "WanderWall Installation"
echo "==================================="

# Check we're on a Raspberry Pi
if [[ ! -f /proc/device-tree/model ]] || ! grep -q "Raspberry Pi" /proc/device-tree/model 2>/dev/null; then
    echo "Warning: This doesn't appear to be a Raspberry Pi"
    read -p "Continue anyway? [y/N] " confirm
    [[ "$confirm" =~ ^[Yy]$ ]] || exit 1
fi

# Get the directory where the script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "Project directory: $PROJECT_DIR"

# Create virtual environment
echo ""
echo "Creating virtual environment..."
python3 -m venv "$PROJECT_DIR/venv"
source "$PROJECT_DIR/venv/bin/activate"

# Install system dependencies
echo ""
echo "Installing system dependencies..."
sudo apt-get install -y libheif1

# Install Python dependencies
echo ""
echo "Installing Python dependencies..."
pip install --upgrade pip
pip install -e "$PROJECT_DIR"

# Create config directory
echo ""
echo "Setting up configuration..."
CONFIG_DIR="$HOME/.wanderwall"
mkdir -p "$CONFIG_DIR/logs"
chmod 700 "$CONFIG_DIR"

# Copy example configs if they don't exist
if [[ ! -f "$CONFIG_DIR/config.yaml" ]]; then
    cp "$PROJECT_DIR/config/config.example.yaml" "$CONFIG_DIR/config.yaml"
    echo "Created $CONFIG_DIR/config.yaml - please customize"
fi

if [[ ! -f "$CONFIG_DIR/sources.yaml" ]]; then
    # Full path, never "~" (PL-211): not every part of the API expands it
    cat > "$CONFIG_DIR/sources.yaml" << SOURCES_EOF
sources:
  - id: "local"
    name: "Local Photos"
    local_path: "$HOME/Pictures/local"
    rclone_remote: ""
    enabled: true
SOURCES_EOF
    echo "Created $CONFIG_DIR/sources.yaml - please customize with your photo sources"
fi

# Set up systemd services
echo ""
echo "Setting up systemd services..."
mkdir -p "$HOME/.config/systemd/user"
cp "$PROJECT_DIR/systemd/wanderwall-api.service" "$HOME/.config/systemd/user/"
cp "$PROJECT_DIR/systemd/wanderwall-sync.service" "$HOME/.config/systemd/user/"
cp "$PROJECT_DIR/systemd/wanderwall-sync.timer" "$HOME/.config/systemd/user/"

# Reload systemd
systemctl --user daemon-reload

# Enable lingering (allows user services to run without login)
echo ""
echo "Enabling user service lingering..."
sudo loginctl enable-linger "$USER"

echo ""
echo "==================================="
echo "Installation complete!"
echo "==================================="
echo ""
echo "Next steps:"
echo "1. Edit ~/.wanderwall/config.yaml with your frame settings"
echo "2. Edit ~/.wanderwall/sources.yaml with your photo sources"
echo "3. Configure rclone: rclone config"
echo "4. Set up Tailscale Funnel: ./scripts/setup_tailscale.sh"
echo "5. Start the services:"
echo "   systemctl --user enable wanderwall-api wanderwall-sync.timer"
echo "   systemctl --user start wanderwall-api wanderwall-sync.timer"
echo ""
echo "Check status with:"
echo "   systemctl --user status wanderwall-api"
echo "   systemctl --user list-timers"
