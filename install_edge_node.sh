#!/bin/bash

set -e

echo "==================================================================================="
echo "Citizen Drone Defense Force (CDDF) - Edge Node Installation Script"
echo "==================================================================================="
echo "This script will install all prerequisites for a Raspbian drone detection edge node"
echo "==================================================================================="

# Check if running as root
if [[ $EUID -eq 0 ]]; then
   echo "This script should not be run as root. Please run as a regular user with sudo access."
   exit 1
fi

# Update system packages
echo "Updating system packages..."
sudo apt update && sudo apt upgrade -y

# Install system dependencies
echo "Installing system dependencies..."
sudo apt install -y \
    python3 \
    python3-pip \
    python3-venv \
    git \
    build-essential \
    cmake \
    pkg-config \
    libasound2-dev \
    libportaudio2 \
    libportaudiocpp0 \
    portaudio19-dev \
    libfftw3-dev \
    libusb-1.0-0-dev \
    rtl-sdr \
    hackrf \
    libhackrf-dev \
    pulseaudio \
    alsa-utils \
    wget \
    curl \
    libnl-3-dev \
    libnl-genl-3-dev \
    libcap-dev \
    libpcap-dev \
    libnm-dev \
    libdw-dev \
    libsqlite3-dev \
    libprotobuf-dev \
    libprotobuf-c-dev \
    protobuf-compiler \
    protobuf-c-compiler \
    libusb-1.0-0-dev \
    python3-setuptools \
    python3-protobuf \
    librtlsdr-dev \
    libbtbb-dev \
    libbluetooth-dev \
    libssl-dev \
    libwebsockets-dev \
    mosquitto \
    libmosquitto1 \
    libmosquitto-dev \
    ubertooth \
    libudev-dev \
    libdbus-1-dev

# Install RTL-SDR tools
echo "Installing RTL-SDR utilities..."
sudo apt install -y rtl-sdr

# Configure RTL-SDR (blacklist kernel modules that interfere)
echo "Configuring RTL-SDR..."
echo 'blacklist dvb_usb_rtl28xxu' | sudo tee -a /etc/modprobe.d/blacklist-rtl.conf
echo 'blacklist rtl2832' | sudo tee -a /etc/modprobe.d/blacklist-rtl.conf
echo 'blacklist rtl2830' | sudo tee -a /etc/modprobe.d/blacklist-rtl.conf

# Add user to dialout group for hardware access
echo "Adding user to dialout group..."
sudo usermod -a -G dialout $USER

# Create a system group and user (if they don't exist)
if ! getent group kismet > /dev/null 2>&1; then
    sudo groupadd --system kismet
fi

if ! id -u kismet > /dev/null 2>&1; then
    sudo useradd --system --gid kismet --home /var/lib/kismet --shell /usr/sbin/nologin kismet
fi

# Add user to kismet group
sudo usermod -a -G kismet $USER

# Install Kismet from nightly build packages
echo "Installing Kismet from nightly build packages..."

# Add Kismet repository using modern method
echo "Adding Kismet repository..."
wget -O - https://www.kismetwireless.net/repos/kismet-release.gpg.key | sudo gpg --dearmor -o /usr/share/keyrings/kismet-archive-keyring.gpg
# Using bookworm repository as it's compatible with trixie and trixie-specific repo doesn't exist yet
echo 'deb [signed-by=/usr/share/keyrings/kismet-archive-keyring.gpg] https://www.kismetwireless.net/repos/apt/release/trixie trixie main' | sudo tee /etc/apt/sources.list.d/kismet.list

# Update package list and install Kismet
echo "Installing Kismet package..."
sudo apt update
# Install kismet-core and essential capture tools, excluding problematic drone ID plugins with libwebsockets17 dependency
sudo apt install -y kismet-core kismet-capture-linux-bluetooth kismet-capture-linux-wifi kismet-capture-nrf-51822 kismet-capture-nrf-52840 kismet-capture-nrf-mousejack kismet-capture-nxp-kw41z kismet-capture-rz-killerbee kismet-capture-ti-cc-2531 kismet-capture-ti-cc-2540 kismet-capture-ubertooth-one

# The package installation should handle systemd service setup automatically
sudo systemctl daemon-reload

# Ensure directories exist with proper permissions
sudo mkdir -p /var/lib/kismet /var/log/kismet /var/run/kismet
sudo chown -R kismet:kismet /var/lib/kismet /var/log/kismet /var/run/kismet

# Set proper permissions for Kismet capture binaries (if not already set by package)
sudo setcap cap_net_raw,cap_net_admin=eip /usr/bin/kismet_cap_linux_wifi || sudo chmod u+s /usr/bin/kismet_cap_linux_wifi
sudo setcap cap_net_raw,cap_net_admin=eip /usr/bin/kismet_cap_linux_bluetooth || sudo chmod u+s /usr/bin/kismet_cap_linux_bluetooth

# Configure Kismet for edge node operation
echo "Configuring Kismet..."
sudo mkdir -p /etc/kismet/conf.d

# Create CDDF-specific Kismet configuration
sudo tee /etc/kismet/conf.d/cddf-edge.conf > /dev/null <<EOF
# CDDF Edge Node Kismet Configuration

# Enable external data sources for Sniffle integration
helper_binary_path=/usr/local/bin:/usr/bin:/bin
alloweduser=kismet
alloweduser=$USER

# Remote capture configuration for BLE Remote ID
remote_capture_listen=127.0.0.1
remote_capture_port=3501

# Logging configuration for drone detection
log_types=kismet,pcapng,alert
log_template=/var/log/kismet/kismet-%n-%d-%t-%i.%l
log_prefix=/var/log/kismet/

# Enable REST API for CDDF integration
httpd_bind_address=127.0.0.1
httpd_port=2501
httpd_user_dir=/tmp/kismet_httpd/
httpd_session_db=/tmp/kismet_session.db

# Memory and performance tuning for edge deployment
tracker_device_timeout=300
tracker_max_devices=1000

# Alert configuration for drone detection
alert=DRONEDETECTED,5/min,Remote ID drone detected
alert=DRONELOCATION,1/min,Drone location broadcast detected
alert=DRONEAUDIO,10/min,Audio-based drone detection
alert=DRONERF,10/min,RF-based drone detection

# Database logging
db_log_devices=true
db_log_alerts=true
db_file=/var/log/kismet/kismet.db
EOF

# Create Kismet log directory
sudo mkdir -p /var/log/kismet
sudo chown kismet:kismet /var/log/kismet

# Create Kismet systemd service override for edge node
sudo mkdir -p /etc/systemd/system/kismet.service.d
sudo tee /etc/systemd/system/kismet.service.d/cddf-override.conf > /dev/null <<EOF
[Service]
# Restart on failure for edge node reliability
Restart=always
RestartSec=30

# Environment for CDDF integration
Environment=KISMET_CONFIG_DIR=/etc/kismet/conf.d

# Run with lower priority to not interfere with real-time detection
Nice=10
EOF

# Create Python virtual environment
echo "Creating Python virtual environment..."
python3 -m venv ~/cddf-env
source ~/cddf-env/bin/activate

# Upgrade pip
pip install --upgrade pip

# Install Python dependencies
echo "Installing Python dependencies..."
pip install \
    openai>=1.0.0 \
    numpy \
    soundfile \
    sounddevice \
    pyhackrf \
    matplotlib \
    scapy \
    requests \
    bleak \
    pynrfjprog \
    nrfutil

# Configure audio system
echo "Configuring audio system..."
sudo usermod -a -G audio $USER

# Create systemd service for audio permissions
sudo tee /etc/systemd/system/cddf-audio-setup.service > /dev/null <<EOF
[Unit]
Description=CDDF Audio Setup
After=sound.target

[Service]
Type=oneshot
ExecStart=/bin/bash -c 'chmod 666 /dev/snd/* || true'
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl enable cddf-audio-setup.service

# Create udev rules for hardware access
echo "Setting up hardware permissions..."
sudo tee /etc/udev/rules.d/99-cddf-hardware.rules > /dev/null <<EOF
# RTL-SDR devices
SUBSYSTEM=="usb", ATTRS{idVendor}=="0bda", ATTRS{idProduct}=="2832", GROUP="dialout", MODE="0666"
SUBSYSTEM=="usb", ATTRS{idVendor}=="0bda", ATTRS{idProduct}=="2838", GROUP="dialout", MODE="0666"

# HackRF devices
SUBSYSTEM=="usb", ATTRS{idVendor}=="1d50", ATTRS{idProduct}=="6089", GROUP="dialout", MODE="0666"
SUBSYSTEM=="usb", ATTRS{idVendor}=="1d50", ATTRS{idProduct}=="60a1", GROUP="dialout", MODE="0666"

# Nordic nRF52 devices
# nRF52840 DK
SUBSYSTEM=="usb", ATTRS{idVendor}=="1366", ATTRS{idProduct}=="1015", GROUP="dialout", MODE="0666"
# nRF52840 Dongle
SUBSYSTEM=="usb", ATTRS{idVendor}=="1915", ATTRS{idProduct}=="521f", GROUP="dialout", MODE="0666"
# nRF52832 DK
SUBSYSTEM=="usb", ATTRS{idVendor}=="1366", ATTRS{idProduct}=="1052", GROUP="dialout", MODE="0666"
# Generic SEGGER J-Link (used by Nordic DKs)
SUBSYSTEM=="usb", ATTRS{idVendor}=="1366", ATTRS{idProduct}=="0105", GROUP="dialout", MODE="0666"

# Audio devices
SUBSYSTEM=="sound", GROUP="audio", MODE="0666"
EOF

# Reload udev rules
sudo udevadm control --reload-rules
sudo udevadm trigger

# Clone the CDDF repository (if not already present)
if [ ! -d ~/cddf ]; then
    echo "Cloning CDDF repository..."
    git clone https://github.com/h3ml0ck/cddf.git ~/cddf
fi

# Create environment file template
echo "Creating environment template..."
cat > ~/cddf/.env.template <<EOF
# OpenAI API Key for image generation and analysis
OPENAI_API_KEY=your_openai_api_key_here

# Audio device configuration (use 'python -m sounddevice' to list devices)
AUDIO_DEVICE_ID=0

# RF configuration
RTL_SDR_DEVICE_INDEX=0
HACKRF_DEVICE_INDEX=0
EOF

# Create activation script
cat > ~/activate_cddf.sh <<EOF
#!/bin/bash
source ~/cddf-env/bin/activate
cd ~/cddf
echo "CDDF environment activated. Available tools:"
echo "  python drone_audio_monitor.py --device 0"
echo "  python drone_rf_detection.py"
echo "  python drone_rtl_power_detection.py --range 2400M:2483M:1M"
echo "  python drone_description.py image.jpg"
echo "  python image_query.py 'drone description'"
echo "  python rtl_power_visualization.py rtl_power_output.csv"
echo ""
echo "Kismet wireless monitoring:"
echo "  sudo systemctl start kismet    # Start Kismet server"
echo "  sudo systemctl status kismet   # Check Kismet status"
echo "  # Web interface: http://localhost:2501"
echo "  # Logs: /var/log/kismet/"
echo ""
echo "nRF52 BLE Remote ID monitoring:"
echo "  nrfjprog --ids                 # List connected nRF devices"
echo "  nrfjprog --deviceinfo          # Check nRF device info"
echo "  ls -la /dev/tty* | grep ACM    # Find nRF serial port"
echo "  # See howto/nrf-drone-remote-id-setup.md for setup instructions"
EOF
chmod +x ~/activate_cddf.sh

echo "==================================================================================="
echo "Installation Complete!"
echo "==================================================================================="
echo ""
echo "Next steps:"
echo "1. Reboot your system: sudo reboot"
echo "2. After reboot, activate the environment: source ~/activate_cddf.sh"
echo "3. Copy ~/cddf/.env.template to ~/cddf/.env and add your OpenAI API key"
echo "4. Test audio devices: python -m sounddevice"
echo "5. Test RTL-SDR: rtl_test"
echo "6. Test HackRF: hackrf_info"
echo "7. Test nRF devices: nrfjprog --ids"
echo "8. Start Kismet: sudo systemctl start kismet"
echo "9. Access Kismet web interface: http://localhost:2501"
echo ""
echo "Hardware notes:"
echo "- RTL-SDR dongles should be accessible after reboot"
echo "- HackRF One should be detected automatically"
echo "- Audio input devices configured for drone monitoring"
echo "- Kismet configured for wireless monitoring and BLE Remote ID detection"
echo "- nRF52 devices (DK/Dongle) ready for BLE Remote ID scanning"
echo ""
echo "Monitoring capabilities:"
echo "- Audio-based drone detection (100-700Hz analysis)"
echo "- RF signal detection (HackRF/RTL-SDR)"
echo "- WiFi/Bluetooth device monitoring (Kismet)"
echo "- Remote ID beacon detection (BLE via Sniffle integration)"
echo "- nRF52-based BLE Remote ID scanning"
echo "- Centralized logging and web-based analysis"
echo ""
echo "To start monitoring: ./activate_cddf.sh"
echo "==================================================================================="
