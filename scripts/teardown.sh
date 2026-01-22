#!/bin/bash
# =============================================================================
# RoboMonkey MCP Teardown Script
# Removes all RoboMonkey containers, services, and configuration
#
# Usage:
#   ./teardown.sh           # Interactive mode - prompts for confirmation
#   ./teardown.sh --force   # Non-interactive - removes everything
#   ./teardown.sh --dry-run # Show what would be removed without doing it
#
# =============================================================================

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color
BOLD='\033[1m'

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Flags
FORCE=false
DRY_RUN=false

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --force|-f)
            FORCE=true
            shift
            ;;
        --dry-run|-n)
            DRY_RUN=true
            shift
            ;;
        --help|-h)
            echo "RoboMonkey MCP Teardown Script"
            echo ""
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --force, -f    Skip confirmation prompts"
            echo "  --dry-run, -n  Show what would be removed without doing it"
            echo "  --help, -h     Show this help message"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# =============================================================================
# Helper Functions
# =============================================================================

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[OK]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_step() {
    echo -e "\n${BOLD}${CYAN}==> $1${NC}"
}

log_dry() {
    echo -e "${YELLOW}[DRY-RUN]${NC} Would: $1"
}

run_cmd() {
    if [ "$DRY_RUN" = true ]; then
        log_dry "$1"
    else
        eval "$1" 2>/dev/null || true
    fi
}

prompt_yes_no() {
    if [ "$FORCE" = true ]; then
        return 0
    fi

    local prompt="$1"
    local default="${2:-n}"
    local yn

    if [[ "$default" == "y" ]]; then
        prompt="$prompt [Y/n]: "
    else
        prompt="$prompt [y/N]: "
    fi

    while true; do
        read -p "$prompt" yn
        yn=${yn:-$default}
        case $yn in
            [Yy]* ) return 0;;
            [Nn]* ) return 1;;
            * ) echo "Please answer yes or no.";;
        esac
    done
}

# =============================================================================
# Teardown Functions
# =============================================================================

stop_local_processes() {
    log_step "Stopping local processes"

    local pid_files=(
        "$PROJECT_ROOT/daemon.pid"
        "$PROJECT_ROOT/embeddings.pid"
        "$PROJECT_ROOT/webui.pid"
    )

    for pid_file in "${pid_files[@]}"; do
        if [ -f "$pid_file" ]; then
            local pid=$(cat "$pid_file")
            local name=$(basename "$pid_file" .pid)
            if kill -0 "$pid" 2>/dev/null; then
                log_info "Stopping $name (PID: $pid)"
                run_cmd "kill $pid"
                log_success "Stopped $name"
            else
                log_info "Process $name not running (stale pid file)"
            fi
            run_cmd "rm -f $pid_file"
        fi
    done

    # Also remove log files
    local log_files=(
        "$PROJECT_ROOT/daemon.log"
        "$PROJECT_ROOT/embeddings.log"
        "$PROJECT_ROOT/webui.log"
    )

    for log_file in "${log_files[@]}"; do
        if [ -f "$log_file" ]; then
            log_info "Removing: $log_file"
            run_cmd "rm -f $log_file"
        fi
    done
}

stop_docker_containers() {
    log_step "Stopping Docker containers"

    local containers=(
        "robomonkey-postgres"
        "robomonkey-ollama"
        "robomonkey-embeddings"
        "robomonkey-daemon"
        "robomonkey-webui"
        "robomonkey-mcp"
        "ollama"
    )

    for container in "${containers[@]}"; do
        if docker ps -a --format '{{.Names}}' 2>/dev/null | grep -q "^${container}$"; then
            log_info "Stopping and removing container: $container"
            run_cmd "docker stop $container"
            run_cmd "docker rm $container"
            log_success "Removed $container"
        else
            log_info "Container not found: $container (skipping)"
        fi
    done
}

remove_docker_volumes() {
    log_step "Removing Docker volumes"

    local volumes=(
        "robomonkey_postgres_data"
        "robomonkey_ollama_data"
        "yonk-robo-codemonkey_postgres_data"
        "yonk-robo-codemonkey_ollama_data"
    )

    for volume in "${volumes[@]}"; do
        if docker volume ls --format '{{.Name}}' 2>/dev/null | grep -q "^${volume}$"; then
            log_info "Removing volume: $volume"
            run_cmd "docker volume rm $volume"
            log_success "Removed $volume"
        else
            log_info "Volume not found: $volume (skipping)"
        fi
    done
}

remove_docker_network() {
    log_step "Removing Docker networks"

    local networks=(
        "robomonkey_default"
        "yonk-robo-codemonkey_default"
    )

    for network in "${networks[@]}"; do
        if docker network ls --format '{{.Name}}' 2>/dev/null | grep -q "^${network}$"; then
            log_info "Removing network: $network"
            run_cmd "docker network rm $network"
            log_success "Removed $network"
        else
            log_info "Network not found: $network (skipping)"
        fi
    done
}

stop_systemd_services() {
    log_step "Stopping systemd services"

    if [[ "$OSTYPE" != "linux-gnu"* ]]; then
        log_info "Not Linux, skipping systemd"
        return
    fi

    local services=(
        "robomonkey-daemon"
        "robomonkey-webui"
    )

    for service in "${services[@]}"; do
        if systemctl list-unit-files 2>/dev/null | grep -q "^${service}\.service"; then
            log_info "Stopping and disabling: $service"
            run_cmd "sudo systemctl stop $service || true"
            run_cmd "sudo systemctl disable $service || true"
            log_success "Stopped $service"
        else
            log_info "Service not found: $service (skipping)"
        fi
    done
}

remove_systemd_units() {
    log_step "Removing systemd unit files"

    if [[ "$OSTYPE" != "linux-gnu"* ]]; then
        log_info "Not Linux, skipping systemd"
        return
    fi

    local unit_files=(
        "/etc/systemd/system/robomonkey-daemon.service"
        "/etc/systemd/system/robomonkey-webui.service"
    )

    for unit in "${unit_files[@]}"; do
        if [ -f "$unit" ]; then
            log_info "Removing: $unit"
            run_cmd "sudo rm -f $unit"
            log_success "Removed $unit"
        else
            log_info "Unit file not found: $unit (skipping)"
        fi
    done

    run_cmd "sudo systemctl daemon-reload"
}

stop_launchd_services() {
    log_step "Stopping launchd services (macOS)"

    if [[ "$OSTYPE" != "darwin"* ]]; then
        log_info "Not macOS, skipping launchd"
        return
    fi

    local plists=(
        "$HOME/Library/LaunchAgents/com.robomonkey.daemon.plist"
        "$HOME/Library/LaunchAgents/com.robomonkey.webui.plist"
    )

    for plist in "${plists[@]}"; do
        if [ -f "$plist" ]; then
            local label=$(basename "$plist" .plist)
            log_info "Unloading and removing: $label"
            run_cmd "launchctl unload $plist || true"
            run_cmd "rm -f $plist"
            log_success "Removed $plist"
        else
            log_info "Plist not found: $plist (skipping)"
        fi
    done
}

remove_config_files() {
    log_step "Removing configuration files"

    local files=(
        "$PROJECT_ROOT/.env"
        "$PROJECT_ROOT/config/robomonkey-daemon.yaml"
        "$PROJECT_ROOT/docker-compose.yml"
    )

    for file in "${files[@]}"; do
        if [ -f "$file" ]; then
            log_info "Removing: $file"
            run_cmd "rm -f $file"
            log_success "Removed $file"
        else
            log_info "File not found: $file (skipping)"
        fi
    done
}

remove_venv() {
    log_step "Removing Python virtual environments"

    local venvs=(
        "$PROJECT_ROOT/.venv"
        "$PROJECT_ROOT/embedding-service/.venv"
    )

    for venv in "${venvs[@]}"; do
        if [ -d "$venv" ]; then
            log_info "Removing: $venv"
            run_cmd "rm -rf $venv"
            log_success "Removed $(basename $venv) in $(dirname $venv)"
        else
            log_info "Virtual environment not found: $venv (skipping)"
        fi
    done
}

remove_generated_dockerfiles() {
    log_step "Removing generated Dockerfiles"

    local files=(
        "$PROJECT_ROOT/docker-deploy/Dockerfile.daemon"
        "$PROJECT_ROOT/docker-deploy/Dockerfile.webui"
    )

    for file in "${files[@]}"; do
        if [ -f "$file" ]; then
            log_info "Removing: $file"
            run_cmd "rm -f $file"
            log_success "Removed $file"
        else
            log_info "File not found: $file (skipping)"
        fi
    done
}

remove_user_config() {
    log_step "Removing user config directory"

    local config_dir="$HOME/.config/robomonkey"

    if [ -d "$config_dir" ]; then
        log_info "Removing: $config_dir"
        run_cmd "rm -rf $config_dir"
        log_success "Removed $config_dir"
    else
        log_info "User config not found (skipping)"
    fi
}

# =============================================================================
# Main
# =============================================================================

main() {
    echo -e "${CYAN}"
    echo "╔═══════════════════════════════════════════════════════════════════════════╗"
    echo "║                     RoboMonkey Teardown Script                            ║"
    echo "╚═══════════════════════════════════════════════════════════════════════════╝"
    echo -e "${NC}"

    if [ "$DRY_RUN" = true ]; then
        echo -e "${YELLOW}DRY-RUN MODE: No changes will be made${NC}\n"
    fi

    echo "This script will remove:"
    echo "  - Local processes (daemon, embeddings service, webui)"
    echo "  - Docker containers (robomonkey-postgres, robomonkey-ollama, etc.)"
    echo "  - Docker volumes (database data)"
    echo "  - Docker networks"
    echo "  - Systemd services (Linux)"
    echo "  - Launchd services (macOS)"
    echo "  - Configuration files (.env, daemon.yaml, docker-compose.yml)"
    echo "  - Python virtual environment (.venv)"
    echo "  - User config (~/.config/robomonkey)"
    echo ""

    if ! prompt_yes_no "Continue with teardown?"; then
        echo "Aborted."
        exit 0
    fi

    # Stop local processes first
    stop_local_processes

    # Check if docker is available
    if command -v docker &> /dev/null; then
        stop_docker_containers
        remove_docker_volumes
        remove_docker_network
    else
        log_info "Docker not found, skipping container cleanup"
    fi

    # Platform-specific service cleanup
    stop_systemd_services
    remove_systemd_units
    stop_launchd_services

    # Remove config and generated files
    remove_config_files
    remove_generated_dockerfiles
    remove_venv

    # Optionally remove user config
    if prompt_yes_no "Remove user config directory (~/.config/robomonkey)?"; then
        remove_user_config
    fi

    echo ""
    log_step "Teardown Complete"
    echo ""
    echo "RoboMonkey has been removed from this system."
    echo ""
    echo "The following were NOT removed (manual cleanup if needed):"
    echo "  - Source code in: $PROJECT_ROOT"
    echo "  - Ollama models (if using system Ollama)"
    echo "  - Any indexed repositories"
    echo ""
    echo "To reinstall, run:"
    echo "  ${CYAN}./scripts/install.sh${NC}"
}

main
