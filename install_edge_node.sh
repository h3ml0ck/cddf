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
    curl

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
    scapy

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
echo ""
echo "Hardware notes:"
echo "- RTL-SDR dongles should be accessible after reboot"
echo "- HackRF One should be detected automatically"
echo "- Audio input devices configured for drone monitoring"
echo ""
echo "To start monitoring: ./activate_cddf.sh"
echo "==================================================================================="