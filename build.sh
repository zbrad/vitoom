#!/bin/bash
#
# Vitoom Docker Build Script
# Builds Docker image with automatic language detection from OS locale
#
# Usage:
#   ./build.sh [OPTIONS]
#
# Options:
#   --language LANG      Override language (en_US, zh_CN, ja_JP)
#   --arch ARCH         Target architecture (x86_64, aarch64) [default: auto-detect]
#   --no-cache          Build without Docker cache
#   --push              Push image to registry after build
#   --help              Show this help message
#
# Environment Variables:
#   VITOOM_LOCALE       Override language (highest priority)
#   LC_ALL              Fallback locale (if VITOOM_LOCALE not set)
#   LANG                Fallback locale (if LC_ALL not set)
#
# The script automatically detects language from OS environment:
#   1. VITOOM_LOCALE environment variable (if set)
#   2. LC_ALL environment variable (if set)
#   3. LANG environment variable (if set)
#   4. Default to English if none found
#

set -e

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# Logging functions
log_info() { echo -e "${BLUE}ℹ${NC} $1"; }
log_success() { echo -e "${GREEN}✓${NC} $1"; }
log_warning() { echo -e "${YELLOW}⚠${NC} $1"; }
log_error() { echo -e "${RED}✗${NC} $1"; }
log_header() { echo -e "\n${CYAN}=== $1 ===${NC}\n"; }

# Resolve Docker Compose invocation: prefer the modern `docker compose`
# plugin, fall back to the standalone `docker-compose` binary if that's
# what's installed instead.
detect_compose_cmd() {
    if docker compose version >/dev/null 2>&1; then
        echo "docker compose"
    elif command -v docker-compose >/dev/null 2>&1; then
        echo "docker-compose"
    else
        return 1
    fi
}

show_help() {
    grep "^#" "$0" | grep -v "^#!/bin/bash" | sed 's/^# *//'
}

# Detect language from environment
detect_language() {
    # Priority 1: VITOOM_LOCALE
    if [ -n "$VITOOM_LOCALE" ]; then
        echo "$VITOOM_LOCALE"
        return 0
    fi

    # Priority 2: LC_ALL
    if [ -n "$LC_ALL" ]; then
        locale_code=$(echo "$LC_ALL" | cut -d'_' -f1-2 | tr '[:upper:]' '[:lower:]')
        case "$locale_code" in
            zh_cn) echo "zh_CN"; return 0 ;;
            ja_jp) echo "ja_JP"; return 0 ;;
            en_us|*) echo "en_US"; return 0 ;;
        esac
    fi

    # Priority 3: LANG
    if [ -n "$LANG" ]; then
        locale_code=$(echo "$LANG" | cut -d'_' -f1-2 | tr '[:upper:]' '[:lower:]')
        case "$locale_code" in
            zh_cn) echo "zh_CN"; return 0 ;;
            ja_jp) echo "ja_JP"; return 0 ;;
            en_us|*) echo "en_US"; return 0 ;;
        esac
    fi

    # Default
    echo "en_US"
}

# Detect architecture. Values must match what Dockerfile.backend expects
# (VITOOM_TARGET_ARCH is compared against Docker's TARGETARCH build arg,
# which reports "arm64" - the Dockerfile maps that to "aarch64" itself).
detect_architecture() {
    arch=$(uname -m)
    case "$arch" in
        x86_64) echo "x86_64" ;;
        aarch64|arm64) echo "aarch64" ;;
        *) echo "x86_64" ;;
    esac
}

# Default values
LANGUAGE=$(detect_language)
ARCH=$(detect_architecture)
CACHE_FLAG=""
PUSH_IMAGE=false
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

log_header "Vitoom Docker Build"
log_info "Auto-detected language: $LANGUAGE"
log_info "Auto-detected architecture: $ARCH"

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --language)
            LANGUAGE="$2"
            shift 2
            ;;
        --arch)
            ARCH="$2"
            shift 2
            ;;
        --no-cache)
            CACHE_FLAG="--no-cache"
            shift
            ;;
        --push)
            PUSH_IMAGE=true
            shift
            ;;
        --help|-h)
            show_help
            exit 0
            ;;
        *)
            log_error "Unknown option: $1"
            show_help
            exit 1
            ;;
    esac
done

# Validate language
case "$LANGUAGE" in
    en_US|zh_CN|ja_JP)
        log_success "Language set to: $LANGUAGE"
        ;;
    *)
        log_error "Invalid language: $LANGUAGE"
        log_info "Supported languages: en_US, zh_CN, ja_JP"
        exit 1
        ;;
esac

# Validate architecture. Accept "arm64" as a user-facing alias but
# normalize to "aarch64", which is what Dockerfile.backend expects.
case "$ARCH" in
    arm64)
        ARCH="aarch64"
        log_success "Architecture set to: $ARCH"
        ;;
    x86_64|aarch64)
        log_success "Architecture set to: $ARCH"
        ;;
    *)
        log_error "Invalid architecture: $ARCH"
        log_info "Supported architectures: x86_64, arm64 (aarch64)"
        exit 1
        ;;
esac

cd "$PROJECT_DIR"

# Check if docker-compose.yml exists
if [ ! -f "docker-compose.yml" ]; then
    log_error "docker-compose.yml not found in $PROJECT_DIR"
    exit 1
fi

COMPOSE_CMD="$(detect_compose_cmd)" || {
    log_error "Neither 'docker compose' nor 'docker-compose' is available"
    log_info "Install Docker Compose: https://docs.docker.com/compose/install/"
    exit 1
}
log_info "Using: $COMPOSE_CMD"
log_info "Project directory: $PROJECT_DIR"
log_info "Build flags: $CACHE_FLAG"
echo ""

# Check if .env exists
if [ ! -f ".env" ]; then
    log_warning ".env file not found. Creating from template..."
    if [ -f ".env.template" ]; then
        cp .env.template .env
        log_info "Created .env from .env.template"
        log_info "Please edit .env with your configuration"
    else
        log_error "Neither .env nor .env.template found"
        exit 1
    fi
fi

# Load environment variables
set -a
source .env
set +a

# Validate required environment variables
log_info "Validating configuration..."

if [ -z "$VITOOM_BACKEND_URL" ]; then
    log_error "VITOOM_BACKEND_URL not set in .env"
    exit 1
fi

if [ -z "$VITOOM_INFERENCE_UPLOAD_AUTH_SECRET" ] || [ "$VITOOM_INFERENCE_UPLOAD_AUTH_SECRET" = "your_secret_here" ]; then
    log_error "VITOOM_INFERENCE_UPLOAD_AUTH_SECRET not properly configured"
    log_info "Run: python scripts/setup_vitoom.py to generate secrets"
    exit 1
fi

if [ -z "$DEFAULT_ADMIN_PASSWORD" ] || [ "$DEFAULT_ADMIN_PASSWORD" = "your_admin_password_here" ]; then
    log_error "DEFAULT_ADMIN_PASSWORD not properly configured"
    exit 1
fi

log_success "Configuration validated"
echo ""

# Update .env with language and architecture
log_info "Updating configuration..."
if grep -q "VITOOM_LOCALE=" .env; then
    sed -i.bak "s/VITOOM_LOCALE=.*/VITOOM_LOCALE=$LANGUAGE/" .env
else
    echo "VITOOM_LOCALE=$LANGUAGE" >> .env
fi

if grep -q "VITOOM_TARGET_ARCH=" .env; then
    sed -i.bak "s/VITOOM_TARGET_ARCH=.*/VITOOM_TARGET_ARCH=$ARCH/" .env
else
    echo "VITOOM_TARGET_ARCH=$ARCH" >> .env
fi

# Remove backup file
rm -f .env.bak

log_success "Configuration updated"
echo ""

# Build the image
log_header "Building Docker Image"
log_info "Command: $COMPOSE_CMD build $CACHE_FLAG backend"
echo ""

$COMPOSE_CMD build \
    $CACHE_FLAG \
    --build-arg VITOOM_TARGET_ARCH="$ARCH" \
    backend

if [ $? -eq 0 ]; then
    log_success "Docker image built successfully"
else
    log_error "Docker image build failed"
    exit 1
fi

# Get image name
IMAGE_NAME="${VITOOM_BACKEND_IMAGE:-vitoom-backend:latest-${ARCH}}"

echo ""
log_header "Build Complete"
log_success "Docker image built: $IMAGE_NAME"
log_info "Language: $LANGUAGE"
log_info "Architecture: $ARCH"

# Push if requested
if [ "$PUSH_IMAGE" = true ]; then
    echo ""
    log_info "Pushing image to registry..."
    docker push "$IMAGE_NAME"
    if [ $? -eq 0 ]; then
        log_success "Image pushed successfully"
    else
        log_warning "Image push failed - this may be OK if using local registry"
    fi
fi

echo ""
log_info "Next steps:"
log_info "  1. Run: ./run.sh"
log_info "  2. Access at: $VITOOM_BACKEND_URL"
log_info ""
log_info "To override language: ./run.sh --language zh_CN"
