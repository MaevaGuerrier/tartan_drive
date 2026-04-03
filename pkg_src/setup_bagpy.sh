#!/bin/bash
# =============================================================================
# setup_bagpy.sh
# Install bagpy from source in a virtual environment on Compute Canada clusters
# Usage: bash setup_bagpy.sh
# =============================================================================

set -e  # Exit on any error


source ../tartan_venv/bin/activate

# --- Colors for output -------------------------------------------------------
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

info()    { echo -e "${GREEN}[INFO]${NC}  $1"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $1"; }
error()   { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }


if [ ! -d "bagpy" ]; then
    git clone https://github.com/jmscslgroup/bagpy 
fi


# --- Install bagpy from source -----------------------------------------------
info "Installing bagpy from source (editable mode)..."
pip install -e bagpy/.


info "Verifying installation..."
python -c "import rosbag;" \
    && info "bagpy installed successfully!" \
    || error "bagpy import failed. Check the output above for errors."


echo ""
echo -e "${GREEN}============================================================${NC}"
echo -e "${GREEN} Installation complete!${NC}"
echo -e "${GREEN}============================================================${NC}"
echo ""