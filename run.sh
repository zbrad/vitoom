#!/bin/bash
#
# Vitoom Backend Container Run Script
# Runs the Docker container with localization support
#
# Usage:
#   ./run.sh [OPTIONS]
#
# Options:
#   --language LANG      Deployment language (en_US, zh_CN, ja_JP) [default: en_US]
#   --port PORT         Server port [default: 8888]
#   --detach            Run in detached mode (background)
#   --logs              Show live logs (with --detach)
#   --stop              Stop the running container
#   --restart           Restart the container
#   --shell             Open interactive shell in container
#   --health            Check container health status
#   --help              Show this help message
#
# Examples:
#   # Run in English (default)
#   ./run.sh
#
#   # Run in Chinese
#   ./run.sh --language zh_CN --detach
#
#   # Run in Japanese and show logs
#   ./run.sh --language ja_JP --detach --logs
#
#   # Open shell in running container
#   ./run.sh --shell
#
#   # Check health
#   ./run.sh --health
#

set -e

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# Function to detect language from environment
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

# Default values
LANGUAGE=$(detect_language)
PORT="8888"
DETACH=false
SHOW_LOGS=false
STOP_CONTAINER=false
RESTART_CONTAINER=false
OPEN_SHELL=false
CHECK_HEALTH=false
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

log_info() { echo -e "${BLUE}ℹ${NC} $1"; }
log_success() { echo -e "${GREEN}✓${NC} $1"; }
log_warning() { echo -e "${YELLOW}⚠${NC} $1"; }
log_error() { echo -e "${RED}✗${NC} $1"; }
log_header() { echo -e "\n${CYAN}=== $1 ===${NC}\n"; }

# Resolve Docker Compose invocation: prefer the modern `docker compose`
# plugin, fall back to the standalone `docker-compose` binary.
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

show_usage() {
    echo "Vitoom Backend Container Manager"
    echo ""
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Language Options:"
    echo "  --language en_US    English (default)"
    echo "  --language zh_CN    Chinese (Simplified)"
    echo "  --language ja_JP    Japanese"
    echo ""
    echo "Run Options:"
    echo "  --detach           Run in background"
    echo "  --logs             Show live logs"
    echo "  --port PORT        Custom port (default: 8888)"
    echo ""
    echo "Container Management:"
    echo "  --stop             Stop the container"
    echo "  --restart          Restart the container"
    echo "  --shell            Open interactive shell"
    echo "  --health           Check container health"
    echo ""
    echo "Examples:"
    echo "  $0                           # Run in English, foreground"
    echo "  $0 --language zh_CN --detach # Run in Chinese, background"
    echo "  $0 --language ja_JP --logs   # Run in Japanese with logs"
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --language)
            LANGUAGE="$2"
            shift 2
            ;;
        --port)
            PORT="$2"
            shift 2
            ;;
        --detach)
            DETACH=true
            shift
            ;;
        --logs)
            SHOW_LOGS=true
            shift
            ;;
        --stop)
            STOP_CONTAINER=true
            shift
            ;;
        --restart)
            RESTART_CONTAINER=true
            shift
            ;;
        --shell)
            OPEN_SHELL=true
            shift
            ;;
        --health)
            CHECK_HEALTH=true
            shift
            ;;
        --help|-h)
            show_usage
            exit 0
            ;;
        *)
            log_error "Unknown option: $1"
            show_usage
            exit 1
            ;;
    esac
done

# Validate language
case "$LANGUAGE" in
    en_US)
        LANG_NAME="English (United States)"
        ;;
    zh_CN)
        LANG_NAME="Chinese (Simplified)"
        ;;
    ja_JP)
        LANG_NAME="Japanese (Japan)"
        ;;
    *)
        log_error "Invalid language: $LANGUAGE"
        log_info "Supported: en_US, zh_CN, ja_JP"
        exit 1
        ;;
esac

cd "$PROJECT_DIR"

COMPOSE_CMD="$(detect_compose_cmd)" || {
    log_error "Neither 'docker compose' nor 'docker-compose' is available"
    log_info "Install Docker Compose: https://docs.docker.com/compose/install/"
    exit 1
}

# Load environment
if [ ! -f ".env" ]; then
    log_error ".env file not found"
    log_info "Please run: ./build.sh"
    exit 1
fi

set -a
source .env
set +a

# Handle stop action
if [ "$STOP_CONTAINER" = true ]; then
    log_info "Stopping Vitoom container..."
    $COMPOSE_CMD down
    log_success "Container stopped"
    exit 0
fi

# Handle restart action
if [ "$RESTART_CONTAINER" = true ]; then
    log_info "Restarting Vitoom container..."
    $COMPOSE_CMD restart
    sleep 2
    $COMPOSE_CMD ps
    log_success "Container restarted"
    exit 0
fi

# Handle shell action
if [ "$OPEN_SHELL" = true ]; then
    log_info "Opening shell in running container..."
    $COMPOSE_CMD exec backend /bin/bash
    exit 0
fi

# Handle health check
if [ "$CHECK_HEALTH" = true ]; then
    log_info "Checking container health..."
    if $COMPOSE_CMD ps | grep -q "healthy\|Up"; then
        log_success "Container is running"
        $COMPOSE_CMD exec backend curl -s http://127.0.0.1:${VITOOM_SERVER_PORT:-8888}/api/health || log_warning "Health check endpoint not responding"
    else
        log_error "Container is not running"
        exit 1
    fi
    exit 0
fi

# Display configuration
log_header "Vitoom Container Configuration"
echo "Language:     $LANG_NAME ($LANGUAGE) [auto-detected from OS]"
echo "Port:         $PORT"
echo "Backend URL:  $VITOOM_BACKEND_URL"
echo "Mode:         $([ "$DETACH" = true ] && echo 'Background (detached)' || echo 'Foreground')"
echo ""
log_info "To override language: ./run.sh --language zh_CN"
echo ""

# Stop existing container if running
if $COMPOSE_CMD ps | grep -q "vitoom-backend"; then
    log_warning "Existing container found, stopping..."
    $COMPOSE_CMD down
    sleep 1
fi

# Update environment
log_info "Configuring deployment language..."
if grep -q "VITOOM_LOCALE=" .env; then
    sed -i "s/VITOOM_LOCALE=.*/VITOOM_LOCALE=$LANGUAGE/" .env
else
    echo "VITOOM_LOCALE=$LANGUAGE" >> .env
fi

if grep -q "VITOOM_SERVER_PORT=" .env; then
    sed -i "s/VITOOM_SERVER_PORT=.*/VITOOM_SERVER_PORT=$PORT/" .env
else
    echo "VITOOM_SERVER_PORT=$PORT" >> .env
fi

# Create required directories
mkdir -p data/config data/inference/config data/resources data/logs

# Start container
log_info "Starting Vitoom backend container..."
if [ "$DETACH" = true ]; then
    $COMPOSE_CMD up -d backend
    sleep 3

    if $COMPOSE_CMD ps | grep -q "vitoom-backend.*Up"; then
        log_success "Container started successfully (detached)"
        log_info "Container ID: $($COMPOSE_CMD ps -q backend)"
        log_info "To view logs: $COMPOSE_CMD logs -f backend"

        if [ "$SHOW_LOGS" = true ]; then
            log_info "Showing live logs (Ctrl+C to stop)..."
            $COMPOSE_CMD logs -f backend
        fi
    else
        log_error "Container failed to start"
        log_info "Checking logs..."
        $COMPOSE_CMD logs backend
        exit 1
    fi
else
    log_info "Starting container in foreground mode (Ctrl+C to stop)..."
    $COMPOSE_CMD up backend
fi

log_success "Vitoom backend is running"
log_info "Access at: $VITOOM_BACKEND_URL"
log_info "Language: $LANG_NAME ($LANGUAGE)"
