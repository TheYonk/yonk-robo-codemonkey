#!/bin/bash
# =============================================================================
# RoboMonkey MCP Installation Script
# Cross-platform installer for macOS and Linux
#
# Usage:
#   ./install.sh           # Docker mode (default) - everything runs in containers
#   ./install.sh --docker  # Explicitly use Docker mode
#   ./install.sh --native  # Native mode - install Python packages locally
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

# Installation mode: docker (default) or native
INSTALL_MODE="docker"

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --docker)
            INSTALL_MODE="docker"
            shift
            ;;
        --native|--no-docker)
            INSTALL_MODE="native"
            shift
            ;;
        --help|-h)
            echo "RoboMonkey MCP Installer"
            echo ""
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --docker     Install using Docker containers (default)"
            echo "               Only requires Docker to be installed"
            echo ""
            echo "  --native     Install natively on host system"
            echo "               Requires Python 3.11 or 3.12"
            echo ""
            echo "  --help, -h   Show this help message"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# Default values
DEFAULT_DB_PORT=5433
DEFAULT_EMBEDDING_MODEL="snowflake-arctic-embed2:latest"
DEFAULT_EMBEDDING_DIMENSION=1024
DEFAULT_LLM_MODEL="qwen2.5-coder:7b"

# =============================================================================
# Helper Functions
# =============================================================================

print_banner() {
    echo -e "${CYAN}"
    echo "╔═══════════════════════════════════════════════════════════════════════════╗"
    echo "║                                                                           ║"
    echo "║     ██████╗  ██████╗ ██████╗  ██████╗ ███╗   ███╗ ██████╗ ███╗   ██╗     ║"
    echo "║     ██╔══██╗██╔═══██╗██╔══██╗██╔═══██╗████╗ ████║██╔═══██╗████╗  ██║     ║"
    echo "║     ██████╔╝██║   ██║██████╔╝██║   ██║██╔████╔██║██║   ██║██╔██╗ ██║     ║"
    echo "║     ██╔══██╗██║   ██║██╔══██╗██║   ██║██║╚██╔╝██║██║   ██║██║╚██╗██║     ║"
    echo "║     ██║  ██║╚██████╔╝██████╔╝╚██████╔╝██║ ╚═╝ ██║╚██████╔╝██║ ╚████║     ║"
    echo "║     ╚═╝  ╚═╝ ╚═════╝ ╚═════╝  ╚═════╝ ╚═╝     ╚═╝ ╚═════╝ ╚═╝  ╚═══╝     ║"
    echo "║                                                                           ║"
    echo "║                    MCP Code Search Installation                           ║"
    echo "║                                                                           ║"
    echo "╚═══════════════════════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
}

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_step() {
    echo -e "\n${BOLD}${CYAN}==> $1${NC}"
}

prompt_yes_no() {
    local prompt="$1"
    local default="${2:-y}"
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

prompt_choice() {
    local prompt="$1"
    shift
    local options=("$@")
    local choice

    echo -e "\n${BOLD}$prompt${NC}" >&2
    for i in "${!options[@]}"; do
        echo "  $((i+1)). ${options[$i]}" >&2
    done

    while true; do
        read -p "Enter choice (1-${#options[@]}): " choice
        if [[ "$choice" =~ ^[0-9]+$ ]] && [ "$choice" -ge 1 ] && [ "$choice" -le "${#options[@]}" ]; then
            # Echo the result (0-indexed) instead of returning to avoid set -e issues
            echo $((choice-1))
            return 0
        fi
        echo "Invalid choice. Please enter a number between 1 and ${#options[@]}." >&2
    done
}

prompt_input() {
    local prompt="$1"
    local default="$2"
    local value

    if [ -n "$default" ]; then
        read -p "$prompt [$default]: " value
        echo "${value:-$default}"
    else
        read -p "$prompt: " value
        echo "$value"
    fi
}

# =============================================================================
# OS Detection
# =============================================================================

detect_os() {
    if [[ "$OSTYPE" == "darwin"* ]]; then
        OS="macos"
        log_info "Detected: macOS"
    elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
        OS="linux"
        # Detect distro
        if [ -f /etc/os-release ]; then
            . /etc/os-release
            DISTRO=$ID
            log_info "Detected: Linux ($DISTRO)"
        else
            DISTRO="unknown"
            log_info "Detected: Linux (unknown distribution)"
        fi
    else
        log_error "Unsupported operating system: $OSTYPE"
        exit 1
    fi
}

# =============================================================================
# Prerequisite Checks
# =============================================================================

check_command() {
    if command -v "$1" &> /dev/null; then
        return 0
    else
        return 1
    fi
}

check_python() {
    log_step "Checking Python installation"

    # First check for python3.12 or python3.11 explicitly (preferred)
    if check_command python3.12; then
        PYTHON_CMD="python3.12"
        PYTHON_VERSION=$($PYTHON_CMD --version 2>&1 | cut -d' ' -f2)
        log_success "Python $PYTHON_VERSION found (python3.12)"
        return 0
    elif check_command python3.11; then
        PYTHON_CMD="python3.11"
        PYTHON_VERSION=$($PYTHON_CMD --version 2>&1 | cut -d' ' -f2)
        log_success "Python $PYTHON_VERSION found (python3.11)"
        return 0
    fi

    # Check Homebrew paths on macOS (may not be in PATH)
    if [ "$OS" == "macos" ]; then
        for brew_python in /opt/homebrew/bin/python3.12 /usr/local/bin/python3.12 /opt/homebrew/bin/python3.11 /usr/local/bin/python3.11; do
            if [ -x "$brew_python" ]; then
                PYTHON_CMD="$brew_python"
                PYTHON_VERSION=$($PYTHON_CMD --version 2>&1 | cut -d' ' -f2)
                log_success "Python $PYTHON_VERSION found ($brew_python)"
                return 0
            fi
        done
    fi

    # Fall back to python3 and check version
    if check_command python3; then
        PYTHON_VERSION=$(python3 --version 2>&1 | cut -d' ' -f2)
        PYTHON_MAJOR=$(echo "$PYTHON_VERSION" | cut -d'.' -f1)
        PYTHON_MINOR=$(echo "$PYTHON_VERSION" | cut -d'.' -f2)

        if [ "$PYTHON_MAJOR" -ge 3 ] && [ "$PYTHON_MINOR" -ge 11 ] && [ "$PYTHON_MINOR" -le 12 ]; then
            log_success "Python $PYTHON_VERSION found"
            PYTHON_CMD="python3"
            return 0
        elif [ "$PYTHON_MINOR" -ge 13 ]; then
            log_warn "Python $PYTHON_VERSION found, but tree-sitter-languages requires Python 3.11 or 3.12"

            # Offer to install
            if [ "$OS" == "macos" ] && check_command brew; then
                echo ""
                if prompt_yes_no "Would you like to install Python 3.12 via Homebrew?"; then
                    log_info "Installing Python 3.12..."
                    brew install python@3.12

                    # Find the installed python
                    for brew_python in /opt/homebrew/bin/python3.12 /usr/local/bin/python3.12; do
                        if [ -x "$brew_python" ]; then
                            PYTHON_CMD="$brew_python"
                            log_success "Python 3.12 installed successfully"
                            return 0
                        fi
                    done
                fi
            fi

            log_error "Please install Python 3.11 or 3.12:"
            if [ "$OS" == "macos" ]; then
                echo "  brew install python@3.12"
            else
                echo "  sudo apt install python3.12 python3.12-venv"
            fi
            return 1
        else
            log_error "Python 3.11 or 3.12 required, found $PYTHON_VERSION"
            return 1
        fi
    else
        log_error "Python 3 not found"
        return 1
    fi
}

check_docker() {
    log_step "Checking Docker installation"

    if check_command docker; then
        if docker info &> /dev/null; then
            log_success "Docker is installed and running"
            return 0
        else
            log_warn "Docker is installed but not running"
            echo "Please start Docker and re-run this script."
            return 1
        fi
    else
        log_error "Docker not found"
        echo "Please install Docker: https://docs.docker.com/get-docker/"
        return 1
    fi
}

check_docker_compose() {
    if docker compose version &> /dev/null; then
        log_success "Docker Compose (plugin) available"
        DOCKER_COMPOSE="docker compose"
        return 0
    elif check_command docker-compose; then
        log_success "docker-compose (standalone) available"
        DOCKER_COMPOSE="docker-compose"
        return 0
    else
        log_error "Docker Compose not found"
        return 1
    fi
}

check_git() {
    log_step "Checking Git installation"

    if check_command git; then
        log_success "Git is installed"
        return 0
    else
        log_error "Git not found"
        return 1
    fi
}

check_ollama() {
    # Check if Ollama CLI is available
    if check_command ollama; then
        OLLAMA_INSTALLED=true
        # Check if it's running
        if curl -s http://localhost:11434/api/tags &> /dev/null; then
            log_success "Ollama is installed and running"
            OLLAMA_RUNNING=true
        else
            log_info "Ollama is installed but not running"
            OLLAMA_RUNNING=false
        fi
    # Check if Ollama is running via Docker
    elif curl -s http://localhost:11434/api/tags &> /dev/null; then
        log_success "Ollama is running (via Docker or remote)"
        OLLAMA_INSTALLED=true
        OLLAMA_RUNNING=true
        OLLAMA_IS_DOCKER=true
    else
        log_info "Ollama not installed"
        OLLAMA_INSTALLED=false
        OLLAMA_RUNNING=false
    fi
    # Always return 0 to avoid set -e issues
    return 0
}

# =============================================================================
# Installation Functions
# =============================================================================

install_ollama() {
    log_step "Installing Ollama"

    if [ "$OS" == "macos" ]; then
        log_info "Installing Ollama for macOS..."

        # Check if Homebrew is available
        if check_command brew; then
            log_info "Installing via Homebrew..."
            brew install ollama
        else
            log_info "Downloading Ollama from official site..."
            # Download and install the macOS app
            curl -fsSL https://ollama.com/download/Ollama-darwin.zip -o /tmp/Ollama.zip
            unzip -o /tmp/Ollama.zip -d /Applications
            rm /tmp/Ollama.zip
            log_info "Ollama.app installed to /Applications"
            log_warn "Please launch Ollama from Applications to start the service"
        fi

    elif [ "$OS" == "linux" ]; then
        log_info "Installing Ollama for Linux..."
        curl -fsSL https://ollama.com/install.sh | sh
    fi

    log_success "Ollama installation complete"
}

start_ollama_docker() {
    log_step "Starting Ollama via Docker"

    # Check if container already exists
    if docker ps -a --format '{{.Names}}' | grep -q '^ollama$'; then
        if docker ps --format '{{.Names}}' | grep -q '^ollama$'; then
            log_info "Ollama container already running"
        else
            log_info "Starting existing Ollama container..."
            docker start ollama
        fi
    else
        log_info "Creating and starting Ollama container..."

        # Check for GPU support
        local gpu_flag=""
        if [ "$OS" == "linux" ]; then
            if command -v nvidia-smi &> /dev/null; then
                log_info "NVIDIA GPU detected, enabling GPU support"
                gpu_flag="--gpus all"
            fi
        fi

        # Run Ollama container
        docker run -d \
            $gpu_flag \
            -v ollama_data:/root/.ollama \
            -p 11434:11434 \
            --name ollama \
            --restart unless-stopped \
            ollama/ollama:latest
    fi

    # Wait for Ollama to be ready
    log_info "Waiting for Ollama to start..."
    local retries=30
    while [ $retries -gt 0 ]; do
        if curl -s http://localhost:11434/api/tags &> /dev/null; then
            log_success "Ollama is ready"
            OLLAMA_IS_DOCKER=true
            return 0
        fi
        sleep 1
        retries=$((retries-1))
    done

    log_warn "Ollama may not have started. Check: docker logs ollama"
    return 0
}

pull_ollama_model_docker() {
    local model="$1"
    log_info "Pulling Ollama model via Docker: $model"
    docker exec ollama ollama pull "$model"
    log_success "Model $model pulled successfully"
}

start_ollama() {
    log_info "Starting Ollama service..."

    if [ "$OS" == "macos" ]; then
        # Check if ollama is available as CLI
        if check_command ollama; then
            ollama serve &>/dev/null &
            sleep 3
        else
            log_warn "Please launch Ollama from Applications folder"
            read -p "Press Enter when Ollama is running..."
        fi
    else
        # Linux - use systemd if available
        if systemctl is-enabled --quiet ollama 2>/dev/null; then
            sudo systemctl start ollama
        else
            ollama serve &>/dev/null &
        fi
        sleep 3
    fi

    # Verify it's running
    if curl -s http://localhost:11434/api/tags &> /dev/null; then
        log_success "Ollama is now running"
        return 0
    else
        log_warn "Ollama may not have started. Check manually."
        return 1
    fi
}

pull_ollama_model() {
    local model="$1"
    log_info "Pulling Ollama model: $model"
    ollama pull "$model"
    log_success "Model $model pulled successfully"
}

setup_postgres_docker() {
    log_step "Setting up PostgreSQL with pgvector"

    cd "$PROJECT_ROOT"

    # Check if postgres container is already running
    if docker ps --format '{{.Names}}' | grep -q 'robomonkey'; then
        log_info "RoboMonkey PostgreSQL container already running"
        return 0
    fi

    log_info "Starting PostgreSQL container..."
    $DOCKER_COMPOSE up -d

    # Wait for postgres to be ready
    log_info "Waiting for PostgreSQL to be ready..."
    local retries=30
    while [ $retries -gt 0 ]; do
        if docker exec $(docker ps -qf "ancestor=pgvector/pgvector:pg16" | head -1) pg_isready -U postgres &>/dev/null; then
            log_success "PostgreSQL is ready"
            return 0
        fi
        sleep 1
        retries=$((retries-1))
    done

    log_error "PostgreSQL failed to start"
    return 1
}


setup_python_env() {
    log_step "Setting up Python environment"

    cd "$PROJECT_ROOT"

    if [ ! -d ".venv" ]; then
        log_info "Creating virtual environment with ${PYTHON_CMD:-python3}..."
        ${PYTHON_CMD:-python3} -m venv .venv
    fi

    log_info "Activating virtual environment..."
    source .venv/bin/activate

    log_info "Installing RoboMonkey..."
    pip install -e . --quiet

    log_success "Python environment ready"
}

init_database() {
    log_step "Initializing database schema"

    cd "$PROJECT_ROOT"
    source .venv/bin/activate

    robomonkey db init
    robomonkey db ping

    log_success "Database initialized"
}

# =============================================================================
# Configuration Generation
# =============================================================================

generate_env_file() {
    log_step "Generating .env configuration"

    local env_file="$PROJECT_ROOT/.env"

    cat > "$env_file" << EOF
# RoboMonkey MCP Configuration
# Generated by install.sh on $(date)

# Database Configuration
DATABASE_URL=postgresql://${DB_USER}:${DB_PASSWORD}@${DB_HOST}:${DB_PORT}/${DB_NAME}

# Embeddings Configuration
EMBEDDINGS_PROVIDER=${EMBEDDINGS_PROVIDER}
EMBEDDINGS_MODEL=${EMBEDDINGS_MODEL}
EMBEDDINGS_BASE_URL=${EMBEDDINGS_BASE_URL}
EMBEDDINGS_DIMENSION=${EMBEDDINGS_DIMENSION}
MAX_CHUNK_LENGTH=8192
EMBEDDING_BATCH_SIZE=100
EOF

    # Add API key if provided
    if [ -n "$EMBEDDINGS_API_KEY" ]; then
        cat >> "$env_file" << EOF
EMBEDDINGS_API_KEY=${EMBEDDINGS_API_KEY}
EOF
    fi

    cat >> "$env_file" << EOF

# Search Parameters
VECTOR_TOP_K=30
FTS_TOP_K=30
FINAL_TOP_K=12
CONTEXT_BUDGET_TOKENS=12000
GRAPH_DEPTH=2

# Schema Isolation
SCHEMA_PREFIX=robomonkey_
USE_SCHEMAS=true

# Default Repository (optional)
DEFAULT_REPO=${DEFAULT_REPO}
EOF

    log_success "Created .env file"
}

generate_daemon_config() {
    log_step "Generating daemon configuration"

    local config_file="$PROJECT_ROOT/config/robomonkey-daemon.yaml"

    # Backup existing config if present
    if [ -f "$config_file" ]; then
        cp "$config_file" "${config_file}.backup.$(date +%Y%m%d_%H%M%S)"
        log_info "Backed up existing daemon config"
    fi

    cat > "$config_file" << EOF
# RoboMonkey Daemon Configuration
# Generated by install.sh on $(date)

# =============================================================================
# LLM Configuration
# =============================================================================
llm:
  # Deep model: Complex code analysis, feature context, comprehensive reviews
  deep:
    provider: "${LLM_DEEP_PROVIDER}"
    model: "${LLM_DEEP_MODEL}"
    base_url: "${LLM_DEEP_BASE_URL}"
EOF

    if [ -n "$LLM_DEEP_API_KEY" ]; then
        cat >> "$config_file" << EOF
    api_key: "${LLM_DEEP_API_KEY}"
EOF
    fi

    # Set max_tokens based on provider (OpenAI GPT-5.x supports up to 128k output)
    local deep_max_tokens=4000
    local small_max_tokens=1000
    if [ "$LLM_DEEP_PROVIDER" == "openai" ]; then
        deep_max_tokens=64000
        small_max_tokens=32000
    fi

    cat >> "$config_file" << EOF
    temperature: 0.3
    max_tokens: ${deep_max_tokens}

  # Small model: Quick summaries, classifications, simple questions
  small:
    provider: "${LLM_SMALL_PROVIDER}"
    model: "${LLM_SMALL_MODEL}"
    base_url: "${LLM_SMALL_BASE_URL}"
EOF

    if [ -n "$LLM_SMALL_API_KEY" ]; then
        cat >> "$config_file" << EOF
    api_key: "${LLM_SMALL_API_KEY}"
EOF
    fi

    cat >> "$config_file" << EOF
    temperature: 0.3
    max_tokens: ${small_max_tokens}

# =============================================================================
# Database Configuration
# =============================================================================
database:
  control_dsn: "postgresql://${DB_USER}:${DB_PASSWORD}@${DB_HOST}:${DB_PORT}/${DB_NAME}"
  schema_prefix: "robomonkey_"
  pool_size: 10

# =============================================================================
# Embeddings Configuration
# =============================================================================
embeddings:
  enabled: true
  backfill_on_startup: true
  provider: "${EMBEDDINGS_PROVIDER}"
  model: "${EMBEDDINGS_MODEL}"
  dimension: ${EMBEDDINGS_DIMENSION}
  max_chunk_length: 4000
  batch_size: 100

  ollama:
    base_url: "${EMBEDDINGS_BASE_URL}"
EOF

    if [ "$EMBEDDINGS_PROVIDER" == "vllm" ] || [ "$EMBEDDINGS_PROVIDER" == "openai" ]; then
        cat >> "$config_file" << EOF

  vllm:
    base_url: "${EMBEDDINGS_BASE_URL}"
    api_key: "${EMBEDDINGS_API_KEY:-local-key}"
EOF
    fi

    cat >> "$config_file" << EOF

# =============================================================================
# Summary Generation
# =============================================================================
summaries:
  enabled: true
  check_interval_minutes: 60
  generate_on_index: true
  provider: "${LLM_SMALL_PROVIDER}"
  model: "${LLM_SMALL_MODEL}"
  base_url: "${LLM_SMALL_BASE_URL}"
  batch_size: 10

# =============================================================================
# Workers & Watching
# =============================================================================
workers:
  global_max_concurrent: 4
  max_concurrent_per_repo: 2
  reindex_workers: 2
  embed_workers: 2
  docs_workers: 1
  poll_interval_sec: 5

watching:
  enabled: true
  debounce_seconds: 2
  ignore_patterns:
    - "*.pyc"
    - "__pycache__"
    - ".git"
    - "node_modules"
    - ".venv"
  code_extensions:
    - ".py"
    - ".js"
    - ".jsx"
    - ".ts"
    - ".tsx"
    - ".go"
    - ".java"
  doc_extensions:
    - ".md"
    - ".rst"
    - ".adoc"

# =============================================================================
# Monitoring & Logging
# =============================================================================
monitoring:
  heartbeat_interval: 30
  dead_threshold: 120
  log_level: "INFO"

logging:
  level: "INFO"
  format: "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
EOF

    log_success "Created daemon configuration"
}

# =============================================================================
# Interactive Setup
# =============================================================================

setup_database_options() {
    log_step "Database Setup"

    echo ""
    local db_choice=$(prompt_choice "How would you like to set up the database?" \
        "Create fresh database (Docker)" \
        "Use existing PostgreSQL server")

    case $db_choice in
        0)
            DB_SETUP="fresh"
            DB_HOST="localhost"
            DB_PORT=$(prompt_input "PostgreSQL port" "$DEFAULT_DB_PORT")
            DB_USER="postgres"
            DB_PASSWORD="postgres"
            DB_NAME="robomonkey"
            USE_SAMPLE_DATA=false
            ;;
        1)
            DB_SETUP="existing"
            DB_HOST=$(prompt_input "PostgreSQL host" "localhost")
            DB_PORT=$(prompt_input "PostgreSQL port" "5432")
            DB_USER=$(prompt_input "PostgreSQL user" "postgres")
            read -sp "PostgreSQL password: " DB_PASSWORD
            echo ""
            DB_NAME=$(prompt_input "Database name" "robomonkey")
            USE_SAMPLE_DATA=false
            ;;
    esac
}

setup_embeddings_options() {
    log_step "Embeddings Configuration"

    echo ""
    echo "Embedding providers:"
    echo "  - Local (lightweight): CPU-based sentence-transformers, no external deps"
    echo "  - Ollama: Local or remote, many models available"
    echo "  - OpenAI: Cloud API, best quality"
    echo "  - NVIDIA NIM: Enterprise GPU inference"
    echo ""

    local embed_choice=$(prompt_choice "How would you like to configure embeddings?" \
        "Local lightweight (sentence-transformers, CPU-only)" \
        "Local Ollama (recommended)" \
        "Remote Ollama server" \
        "OpenAI API")

    # Note: prompt_choice only supports 4 options, so we handle additional providers
    # via "Other" within the OpenAI option or separate prompts

    case $embed_choice in
        0)
            # Local sentence-transformers (lightweight, CPU-only)
            EMBEDDINGS_PROVIDER="openai"  # Uses OpenAI-compatible API
            EMBEDDINGS_BASE_URL="http://localhost:8082"
            EMBEDDINGS_API_KEY=""
            USE_LOCAL_EMBEDDINGS=true

            echo ""
            local local_model_choice=$(prompt_choice "Select local embedding model:" \
                "all-MiniLM-L6-v2 (384d, fast, ~80MB) - RECOMMENDED" \
                "all-mpnet-base-v2 (768d, better quality, ~420MB)")

            case $local_model_choice in
                0)
                    EMBEDDINGS_MODEL="all-MiniLM-L6-v2"
                    EMBEDDINGS_DIMENSION=384
                    ;;
                1)
                    EMBEDDINGS_MODEL="all-mpnet-base-v2"
                    EMBEDDINGS_DIMENSION=768
                    ;;
            esac

            log_info "Local embedding service will be started on port 8082"
            log_info "Model: $EMBEDDINGS_MODEL ($EMBEDDINGS_DIMENSION dimensions)"
            NEED_EMBEDDING_MODEL=false
            ;;
        1)
            # Local Ollama
            EMBEDDINGS_PROVIDER="ollama"
            EMBEDDINGS_BASE_URL="http://localhost:11434"
            EMBEDDINGS_API_KEY=""
            USE_LOCAL_EMBEDDINGS=false

            # Check if Ollama needs installation
            check_ollama
            if [ "$OLLAMA_INSTALLED" == "false" ] || [ "$OLLAMA_RUNNING" == "false" ]; then
                echo ""
                if [ "$OLLAMA_INSTALLED" == "false" ]; then
                    log_warn "Ollama is not installed."
                else
                    log_warn "Ollama is installed but not running."
                fi
                echo ""
                echo "How would you like to proceed?"

                local ollama_setup_choice=$(prompt_choice "Ollama setup:" \
                    "Install Ollama natively (recommended)" \
                    "Run Ollama via Docker container" \
                    "I'll set it up manually later" \
                    "Skip - I'll use a different embedding provider")

                case $ollama_setup_choice in
                    0)
                        # Native install
                        install_ollama
                        NEED_OLLAMA_START=true
                        OLLAMA_IS_DOCKER=false
                        ;;
                    1)
                        # Docker install
                        start_ollama_docker
                        OLLAMA_IS_DOCKER=true
                        ;;
                    2)
                        # Manual setup later
                        log_info "You'll need to install/start Ollama before using embeddings."
                        log_info "  macOS: brew install ollama && ollama serve"
                        log_info "  Linux: curl -fsSL https://ollama.com/install.sh | sh"
                        log_info "  Docker: docker run -d -p 11434:11434 --name ollama ollama/ollama"
                        NEED_OLLAMA_START=false
                        ;;
                    3)
                        # Go back and choose different provider
                        log_info "Please re-run the installer to choose a different embedding provider."
                        exit 0
                        ;;
                esac
            fi

            # Choose embedding model
            echo ""
            local model_choice=$(prompt_choice "Select embedding model:" \
                "snowflake-arctic-embed2:latest (1024d, 8k context) - RECOMMENDED" \
                "nomic-embed-text (768d, 2k context)" \
                "mxbai-embed-large (1024d, 512 context)" \
                "Custom model")

            case $model_choice in
                0)
                    EMBEDDINGS_MODEL="snowflake-arctic-embed2:latest"
                    EMBEDDINGS_DIMENSION=1024
                    ;;
                1)
                    EMBEDDINGS_MODEL="nomic-embed-text"
                    EMBEDDINGS_DIMENSION=768
                    ;;
                2)
                    EMBEDDINGS_MODEL="mxbai-embed-large"
                    EMBEDDINGS_DIMENSION=1024
                    ;;
                3)
                    EMBEDDINGS_MODEL=$(prompt_input "Model name")
                    EMBEDDINGS_DIMENSION=$(prompt_input "Embedding dimension" "1024")
                    ;;
            esac
            NEED_EMBEDDING_MODEL=true
            ;;
        2)
            # Remote Ollama
            EMBEDDINGS_PROVIDER="ollama"
            EMBEDDINGS_BASE_URL=$(prompt_input "Remote Ollama URL" "http://your-server:11434")
            EMBEDDINGS_API_KEY=""
            EMBEDDINGS_MODEL=$(prompt_input "Embedding model" "$DEFAULT_EMBEDDING_MODEL")
            EMBEDDINGS_DIMENSION=$(prompt_input "Embedding dimension" "$DEFAULT_EMBEDDING_DIMENSION")
            NEED_EMBEDDING_MODEL=false
            USE_LOCAL_EMBEDDINGS=false
            ;;
        3)
            # OpenAI or other cloud providers
            echo ""
            local cloud_choice=$(prompt_choice "Select cloud provider:" \
                "OpenAI" \
                "NVIDIA NIM" \
                "Other (Together.ai, Groq, vLLM, etc.)")

            case $cloud_choice in
                0)
                    # OpenAI
                    EMBEDDINGS_PROVIDER="openai"
                    EMBEDDINGS_BASE_URL="https://api.openai.com"
                    echo ""
                    read -sp "OpenAI API Key: " EMBEDDINGS_API_KEY
                    echo ""
                    if [ -n "$EMBEDDINGS_API_KEY" ]; then
                        log_success "API key entered (${#EMBEDDINGS_API_KEY} characters)"
                    else
                        log_warn "No API key entered - you'll need to set OPENAI_API_KEY environment variable"
                    fi

                    echo ""
                    local openai_embed_choice=$(prompt_choice "Select embedding model:" \
                        "text-embedding-3-small (1536d, cheap, good quality)" \
                        "text-embedding-3-large (3072d, best quality)" \
                        "text-embedding-ada-002 (1536d, legacy)" \
                        "Custom model")

                    case $openai_embed_choice in
                        0)
                            EMBEDDINGS_MODEL="text-embedding-3-small"
                            EMBEDDINGS_DIMENSION=1536
                            ;;
                        1)
                            EMBEDDINGS_MODEL="text-embedding-3-large"
                            EMBEDDINGS_DIMENSION=3072
                            ;;
                        2)
                            EMBEDDINGS_MODEL="text-embedding-ada-002"
                            EMBEDDINGS_DIMENSION=1536
                            ;;
                        3)
                            EMBEDDINGS_MODEL=$(prompt_input "Model name")
                            EMBEDDINGS_DIMENSION=$(prompt_input "Embedding dimension" "1536")
                            ;;
                    esac
                    ;;
                1)
                    # NVIDIA NIM
                    EMBEDDINGS_PROVIDER="openai"
                    EMBEDDINGS_BASE_URL=$(prompt_input "NVIDIA NIM endpoint" "https://integrate.api.nvidia.com/v1")
                    echo ""
                    read -sp "NVIDIA API Key: " EMBEDDINGS_API_KEY
                    echo ""
                    if [ -n "$EMBEDDINGS_API_KEY" ]; then
                        log_success "API key entered (${#EMBEDDINGS_API_KEY} characters)"
                    else
                        log_warn "No API key entered - you'll need to set the API key environment variable"
                    fi

                    echo ""
                    local nim_embed_choice=$(prompt_choice "Select NIM embedding model:" \
                        "nvidia/nv-embedqa-e5-v5 (1024d)" \
                        "nvidia/nv-embed-v1 (4096d)" \
                        "snowflake/arctic-embed-l (1024d)" \
                        "Custom model")

                    case $nim_embed_choice in
                        0)
                            EMBEDDINGS_MODEL="nvidia/nv-embedqa-e5-v5"
                            EMBEDDINGS_DIMENSION=1024
                            ;;
                        1)
                            EMBEDDINGS_MODEL="nvidia/nv-embed-v1"
                            EMBEDDINGS_DIMENSION=4096
                            ;;
                        2)
                            EMBEDDINGS_MODEL="snowflake/arctic-embed-l"
                            EMBEDDINGS_DIMENSION=1024
                            ;;
                        3)
                            EMBEDDINGS_MODEL=$(prompt_input "Model name")
                            EMBEDDINGS_DIMENSION=$(prompt_input "Embedding dimension" "1024")
                            ;;
                    esac
                    ;;
                2)
                    # Other OpenAI-compatible
                    EMBEDDINGS_PROVIDER="openai"
                    EMBEDDINGS_BASE_URL=$(prompt_input "API endpoint URL" "https://api.together.xyz")
                    echo ""
                    read -sp "API Key: " EMBEDDINGS_API_KEY
                    echo ""
                    if [ -n "$EMBEDDINGS_API_KEY" ]; then
                        log_success "API key entered (${#EMBEDDINGS_API_KEY} characters)"
                    else
                        log_warn "No API key entered"
                    fi
                    EMBEDDINGS_MODEL=$(prompt_input "Model name")
                    EMBEDDINGS_DIMENSION=$(prompt_input "Embedding dimension" "1024")
                    ;;
            esac
            NEED_EMBEDDING_MODEL=false
            USE_LOCAL_EMBEDDINGS=false
            ;;
    esac

}

setup_service_options() {
    log_step "Service Configuration"

    echo ""
    echo "RoboMonkey includes two optional services:"
    echo "  - Daemon: Background processing (embeddings, summaries, file watching)"
    echo "  - Web UI: Admin panel for database inspection (port 9832)"
    echo ""

    # Ask about starting daemon now
    if prompt_yes_no "Would you like to start the daemon now (one-time)?"; then
        START_DAEMON_NOW=true
    else
        START_DAEMON_NOW=false
    fi

    # Ask about auto-start service
    echo ""
    if prompt_yes_no "Would you like to set up the daemon as an auto-start background service?"; then
        SETUP_AUTOSTART=true

        # Ask about web UI in autostart
        if prompt_yes_no "Include the Web UI in the auto-start service?" "n"; then
            AUTOSTART_WEB_UI=true
        else
            AUTOSTART_WEB_UI=false
        fi
    else
        SETUP_AUTOSTART=false
        AUTOSTART_WEB_UI=false
    fi
}

setup_llm_options() {
    log_step "LLM Configuration (for summaries and analysis)"

    echo ""
    local llm_choice=$(prompt_choice "How would you like to configure the LLM for summaries?" \
        "Local Ollama (same as embeddings)" \
        "Remote Ollama server" \
        "OpenAI API" \
        "NVIDIA NIM endpoint" \
        "Other OpenAI-compatible endpoint")

    case $llm_choice in
        0)
            LLM_DEEP_PROVIDER="ollama"
            LLM_DEEP_BASE_URL="http://localhost:11434"
            LLM_DEEP_API_KEY=""
            LLM_SMALL_PROVIDER="ollama"
            LLM_SMALL_BASE_URL="http://localhost:11434"
            LLM_SMALL_API_KEY=""

            echo ""
            local deep_choice=$(prompt_choice "Select LLM model for deep analysis:" \
                "qwen3-coder:30b (best quality, needs 20GB+ VRAM)" \
                "qwen2.5-coder:14b (good balance)" \
                "qwen2.5-coder:7b (fast, lower memory)" \
                "llama3.1:8b (general purpose)" \
                "Custom model")

            case $deep_choice in
                0) LLM_DEEP_MODEL="qwen3-coder:30b" ;;
                1) LLM_DEEP_MODEL="qwen2.5-coder:14b" ;;
                2) LLM_DEEP_MODEL="qwen2.5-coder:7b" ;;
                3) LLM_DEEP_MODEL="llama3.1:8b" ;;
                4) LLM_DEEP_MODEL=$(prompt_input "Deep model name") ;;
            esac

            echo ""
            local small_choice=$(prompt_choice "Select LLM model for quick tasks (summaries):" \
                "qwen2.5-coder:7b (recommended)" \
                "phi3.5:3.8b (very fast)" \
                "llama3.2:3b (lightweight)" \
                "Same as deep model" \
                "Custom model")

            case $small_choice in
                0) LLM_SMALL_MODEL="qwen2.5-coder:7b" ;;
                1) LLM_SMALL_MODEL="phi3.5:3.8b" ;;
                2) LLM_SMALL_MODEL="llama3.2:3b" ;;
                3) LLM_SMALL_MODEL="$LLM_DEEP_MODEL" ;;
                4) LLM_SMALL_MODEL=$(prompt_input "Small model name") ;;
            esac

            NEED_LLM_MODELS=true
            ;;
        1)
            LLM_DEEP_PROVIDER="ollama"
            LLM_DEEP_BASE_URL=$(prompt_input "Remote Ollama URL" "http://your-server:11434")
            LLM_DEEP_API_KEY=""
            LLM_DEEP_MODEL=$(prompt_input "Deep model" "qwen2.5-coder:14b")
            LLM_SMALL_PROVIDER="ollama"
            LLM_SMALL_BASE_URL="$LLM_DEEP_BASE_URL"
            LLM_SMALL_API_KEY=""
            LLM_SMALL_MODEL=$(prompt_input "Small model" "qwen2.5-coder:7b")
            NEED_LLM_MODELS=false
            ;;
        2)
            LLM_DEEP_PROVIDER="openai"
            LLM_DEEP_BASE_URL="https://api.openai.com"
            echo ""
            read -sp "OpenAI API Key: " LLM_DEEP_API_KEY
            echo ""
            if [ -n "$LLM_DEEP_API_KEY" ]; then
                log_success "API key entered (${#LLM_DEEP_API_KEY} characters)"
            else
                log_warn "No API key entered - you'll need to set OPENAI_API_KEY environment variable"
            fi

            echo ""
            local openai_deep_choice=$(prompt_choice "Select deep model for complex analysis:" \
                "gpt-5.2-codex (best for coding - recommended)" \
                "gpt-5.2 (best for coding and agentic tasks)" \
                "gpt-5.2-pro (smarter, more precise responses)" \
                "gpt-5 (reasoning model with configurable effort)" \
                "gpt-4.1 (smartest non-reasoning model)" \
                "Custom model")

            case $openai_deep_choice in
                0) LLM_DEEP_MODEL="gpt-5.2-codex" ;;
                1) LLM_DEEP_MODEL="gpt-5.2" ;;
                2) LLM_DEEP_MODEL="gpt-5.2-pro" ;;
                3) LLM_DEEP_MODEL="gpt-5" ;;
                4) LLM_DEEP_MODEL="gpt-4.1" ;;
                5) LLM_DEEP_MODEL=$(prompt_input "Custom model name") ;;
            esac

            echo ""
            local openai_small_choice=$(prompt_choice "Select small model for quick tasks:" \
                "gpt-5-mini (fast, cost-efficient - recommended)" \
                "gpt-5-nano (fastest, most cost-efficient)" \
                "gpt-4.1 (smartest non-reasoning)" \
                "Same as deep model" \
                "Custom model")

            case $openai_small_choice in
                0) LLM_SMALL_MODEL="gpt-5-mini" ;;
                1) LLM_SMALL_MODEL="gpt-5-nano" ;;
                2) LLM_SMALL_MODEL="gpt-4.1" ;;
                3) LLM_SMALL_MODEL="$LLM_DEEP_MODEL" ;;
                4) LLM_SMALL_MODEL=$(prompt_input "Custom model name") ;;
            esac

            LLM_SMALL_PROVIDER="openai"
            LLM_SMALL_BASE_URL="https://api.openai.com"
            LLM_SMALL_API_KEY="$LLM_DEEP_API_KEY"
            NEED_LLM_MODELS=false
            ;;
        3)
            LLM_DEEP_PROVIDER="openai"
            LLM_DEEP_BASE_URL=$(prompt_input "NIM endpoint URL" "https://integrate.api.nvidia.com/v1")
            echo ""
            read -sp "NVIDIA API Key: " LLM_DEEP_API_KEY
            echo ""
            if [ -n "$LLM_DEEP_API_KEY" ]; then
                log_success "API key entered (${#LLM_DEEP_API_KEY} characters)"
            else
                log_warn "No API key entered"
            fi

            echo ""
            local nim_deep_choice=$(prompt_choice "Select deep model:" \
                "meta/llama-3.1-70b-instruct (recommended)" \
                "meta/llama-3.1-405b-instruct (largest)" \
                "mistralai/mixtral-8x22b-instruct-v0.1" \
                "Custom model")

            case $nim_deep_choice in
                0) LLM_DEEP_MODEL="meta/llama-3.1-70b-instruct" ;;
                1) LLM_DEEP_MODEL="meta/llama-3.1-405b-instruct" ;;
                2) LLM_DEEP_MODEL="mistralai/mixtral-8x22b-instruct-v0.1" ;;
                3) LLM_DEEP_MODEL=$(prompt_input "Model name") ;;
            esac

            echo ""
            local nim_small_choice=$(prompt_choice "Select small model:" \
                "meta/llama-3.1-8b-instruct (recommended)" \
                "mistralai/mistral-7b-instruct-v0.3" \
                "Same as deep model" \
                "Custom model")

            case $nim_small_choice in
                0) LLM_SMALL_MODEL="meta/llama-3.1-8b-instruct" ;;
                1) LLM_SMALL_MODEL="mistralai/mistral-7b-instruct-v0.3" ;;
                2) LLM_SMALL_MODEL="$LLM_DEEP_MODEL" ;;
                3) LLM_SMALL_MODEL=$(prompt_input "Model name") ;;
            esac

            LLM_SMALL_PROVIDER="openai"
            LLM_SMALL_BASE_URL="$LLM_DEEP_BASE_URL"
            LLM_SMALL_API_KEY="$LLM_DEEP_API_KEY"
            NEED_LLM_MODELS=false
            ;;
        4)
            LLM_DEEP_PROVIDER="openai"
            LLM_DEEP_BASE_URL=$(prompt_input "API endpoint URL")
            echo ""
            read -sp "API Key: " LLM_DEEP_API_KEY
            echo ""
            if [ -n "$LLM_DEEP_API_KEY" ]; then
                log_success "API key entered (${#LLM_DEEP_API_KEY} characters)"
            else
                log_warn "No API key entered"
            fi
            LLM_DEEP_MODEL=$(prompt_input "Deep model name")

            if prompt_yes_no "Use same endpoint for small model?" "y"; then
                LLM_SMALL_PROVIDER="openai"
                LLM_SMALL_BASE_URL="$LLM_DEEP_BASE_URL"
                LLM_SMALL_API_KEY="$LLM_DEEP_API_KEY"
            else
                LLM_SMALL_BASE_URL=$(prompt_input "Small model API endpoint")
                echo ""
                read -sp "Small model API Key: " LLM_SMALL_API_KEY
                echo ""
                if [ -n "$LLM_SMALL_API_KEY" ]; then
                    log_success "API key entered (${#LLM_SMALL_API_KEY} characters)"
                fi
                LLM_SMALL_PROVIDER="openai"
            fi
            LLM_SMALL_MODEL=$(prompt_input "Small model name")
            NEED_LLM_MODELS=false
            ;;
    esac
}

# =============================================================================
# Service Setup Functions
# =============================================================================

start_local_embeddings() {
    log_step "Starting Local Embedding Service"

    cd "$PROJECT_ROOT/embedding-service"

    # Check if already running
    if [ -f "$PROJECT_ROOT/embeddings.pid" ]; then
        local pid=$(cat "$PROJECT_ROOT/embeddings.pid")
        if kill -0 "$pid" 2>/dev/null; then
            log_info "Local embedding service already running (PID: $pid)"
            return 0
        fi
    fi

    # Install requirements if needed
    if [ ! -d "$PROJECT_ROOT/embedding-service/.venv" ]; then
        log_info "Setting up embedding service virtual environment..."
        python3 -m venv "$PROJECT_ROOT/embedding-service/.venv"
        source "$PROJECT_ROOT/embedding-service/.venv/bin/activate"
        pip install --quiet torch --index-url https://download.pytorch.org/whl/cpu
        pip install --quiet -r requirements.txt
        deactivate
    fi

    log_info "Starting embedding service in background..."
    source "$PROJECT_ROOT/embedding-service/.venv/bin/activate"
    nohup python main.py > "$PROJECT_ROOT/embeddings.log" 2>&1 &
    local embed_pid=$!
    echo "$embed_pid" > "$PROJECT_ROOT/embeddings.pid"
    deactivate
    cd "$PROJECT_ROOT"

    # Wait for startup
    sleep 5

    if kill -0 "$embed_pid" 2>/dev/null; then
        log_success "Local embedding service started (PID: $embed_pid)"
        log_info "Log file: $PROJECT_ROOT/embeddings.log"
        log_info "API: http://localhost:8082/health"
    else
        log_warn "Embedding service may have failed to start. Check embeddings.log"
    fi
}

start_daemon_once() {
    log_step "Starting Daemon (one-time)"

    cd "$PROJECT_ROOT"
    source .venv/bin/activate

    log_info "Starting robomonkey daemon in background..."

    nohup robomonkey daemon run > "$PROJECT_ROOT/daemon.log" 2>&1 &
    local daemon_pid=$!
    echo "$daemon_pid" > "$PROJECT_ROOT/daemon.pid"

    sleep 2

    if kill -0 "$daemon_pid" 2>/dev/null; then
        log_success "Daemon started (PID: $daemon_pid)"
        log_info "Log file: $PROJECT_ROOT/daemon.log"
        log_info "PID file: $PROJECT_ROOT/daemon.pid"
        log_info "To stop: kill \$(cat $PROJECT_ROOT/daemon.pid)"
    else
        log_warn "Daemon may have failed to start. Check daemon.log for details."
    fi
}

start_web_ui_once() {
    log_step "Starting Web UI (one-time)"

    cd "$PROJECT_ROOT"
    source .venv/bin/activate

    log_info "Starting web UI in background..."

    nohup python -m yonk_code_robomonkey.web.app > "$PROJECT_ROOT/webui.log" 2>&1 &
    local webui_pid=$!
    echo "$webui_pid" > "$PROJECT_ROOT/webui.pid"

    sleep 2

    if kill -0 "$webui_pid" 2>/dev/null; then
        log_success "Web UI started (PID: $webui_pid)"
        log_info "Access at: http://localhost:9832"
        log_info "Log file: $PROJECT_ROOT/webui.log"
    else
        log_warn "Web UI may have failed to start. Check webui.log for details."
    fi
}

create_systemd_service() {
    log_step "Creating systemd service"

    local service_file="/etc/systemd/system/robomonkey-daemon.service"
    local current_user=$(whoami)

    # Create service file content
    local service_content="[Unit]
Description=RoboMonkey MCP Daemon
After=network.target postgresql.service docker.service
Wants=postgresql.service

[Service]
Type=simple
User=${current_user}
WorkingDirectory=${PROJECT_ROOT}
Environment=PATH=${PROJECT_ROOT}/.venv/bin:/usr/bin:/bin
ExecStart=${PROJECT_ROOT}/.venv/bin/robomonkey daemon run
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
"

    # Check if we can write to systemd directory
    if [ -w "/etc/systemd/system" ]; then
        echo "$service_content" > "$service_file"
    else
        log_info "Creating systemd service requires sudo..."
        echo "$service_content" | sudo tee "$service_file" > /dev/null
    fi

    # Create web UI service if requested
    if [ "$AUTOSTART_WEB_UI" == "true" ]; then
        local webui_service_file="/etc/systemd/system/robomonkey-webui.service"
        local webui_service_content="[Unit]
Description=RoboMonkey Web UI
After=network.target postgresql.service robomonkey-daemon.service
Wants=robomonkey-daemon.service

[Service]
Type=simple
User=${current_user}
WorkingDirectory=${PROJECT_ROOT}
Environment=PATH=${PROJECT_ROOT}/.venv/bin:/usr/bin:/bin
ExecStart=${PROJECT_ROOT}/.venv/bin/python -m yonk_code_robomonkey.web.app
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
"
        if [ -w "/etc/systemd/system" ]; then
            echo "$webui_service_content" > "$webui_service_file"
        else
            echo "$webui_service_content" | sudo tee "$webui_service_file" > /dev/null
        fi
    fi

    # Reload systemd and enable services
    log_info "Enabling systemd services..."
    if [ -w "/etc/systemd/system" ]; then
        systemctl daemon-reload
        systemctl enable robomonkey-daemon
        if [ "$AUTOSTART_WEB_UI" == "true" ]; then
            systemctl enable robomonkey-webui
        fi
    else
        sudo systemctl daemon-reload
        sudo systemctl enable robomonkey-daemon
        if [ "$AUTOSTART_WEB_UI" == "true" ]; then
            sudo systemctl enable robomonkey-webui
        fi
    fi

    log_success "Systemd service created and enabled"
    log_info "To start now: sudo systemctl start robomonkey-daemon"
    log_info "To check status: sudo systemctl status robomonkey-daemon"
    log_info "To view logs: sudo journalctl -u robomonkey-daemon -f"

    if [ "$AUTOSTART_WEB_UI" == "true" ]; then
        log_info "Web UI service: sudo systemctl start robomonkey-webui"
    fi
}

create_launchd_plist() {
    log_step "Creating launchd service (macOS)"

    local plist_dir="$HOME/Library/LaunchAgents"
    local plist_file="$plist_dir/com.robomonkey.daemon.plist"

    # Ensure directory exists
    mkdir -p "$plist_dir"

    # Create plist content
    cat > "$plist_file" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.robomonkey.daemon</string>
    <key>ProgramArguments</key>
    <array>
        <string>${PROJECT_ROOT}/.venv/bin/robomonkey</string>
        <string>daemon</string>
        <string>run</string>
    </array>
    <key>WorkingDirectory</key>
    <string>${PROJECT_ROOT}</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>${PROJECT_ROOT}/.venv/bin:/usr/local/bin:/usr/bin:/bin</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>${PROJECT_ROOT}/daemon.log</string>
    <key>StandardErrorPath</key>
    <string>${PROJECT_ROOT}/daemon.error.log</string>
</dict>
</plist>
EOF

    log_success "Created launchd plist: $plist_file"

    # Create web UI plist if requested
    if [ "$AUTOSTART_WEB_UI" == "true" ]; then
        local webui_plist_file="$plist_dir/com.robomonkey.webui.plist"
        cat > "$webui_plist_file" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.robomonkey.webui</string>
    <key>ProgramArguments</key>
    <array>
        <string>${PROJECT_ROOT}/.venv/bin/python</string>
        <string>-m</string>
        <string>yonk_code_robomonkey.web.app</string>
    </array>
    <key>WorkingDirectory</key>
    <string>${PROJECT_ROOT}</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>${PROJECT_ROOT}/.venv/bin:/usr/local/bin:/usr/bin:/bin</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>${PROJECT_ROOT}/webui.log</string>
    <key>StandardErrorPath</key>
    <string>${PROJECT_ROOT}/webui.error.log</string>
</dict>
</plist>
EOF
        log_success "Created Web UI plist: $webui_plist_file"
    fi

    # Load the services
    log_info "Loading launchd services..."
    launchctl load "$plist_file"
    if [ "$AUTOSTART_WEB_UI" == "true" ]; then
        launchctl load "$webui_plist_file"
    fi

    log_success "Launchd services loaded and will start at login"
    log_info "To start now: launchctl start com.robomonkey.daemon"
    log_info "To stop: launchctl stop com.robomonkey.daemon"
    log_info "To unload: launchctl unload $plist_file"

    if [ "$AUTOSTART_WEB_UI" == "true" ]; then
        log_info "Web UI: launchctl start com.robomonkey.webui"
    fi
}

setup_autostart_service() {
    if [ "$OS" == "linux" ]; then
        create_systemd_service
    elif [ "$OS" == "macos" ]; then
        create_launchd_plist
    fi
}

# =============================================================================
# Docker Installation Functions
# =============================================================================

generate_docker_compose() {
    log_step "Generating docker-compose.yml"

    local compose_file="$PROJECT_ROOT/docker-compose.yml"

    # Determine local embedding service config
    local embeddings_service=""
    local embeddings_depends=""
    if [ "$USE_LOCAL_EMBEDDINGS" == "true" ]; then
        embeddings_depends="embeddings:"
        embeddings_service="
  # Local Embedding Service - lightweight CPU-based sentence-transformers
  embeddings:
    build:
      context: ./embedding-service
      dockerfile: Dockerfile
    container_name: robomonkey-embeddings
    environment:
      EMBEDDING_PORT: 8082
      DEFAULT_EMBEDDING_MODEL: ${EMBEDDINGS_MODEL:-all-MiniLM-L6-v2}
    ports:
      - \"\${EMBEDDINGS_PORT:-8082}:8082\"
    healthcheck:
      test: [\"CMD\", \"python\", \"-c\", \"import urllib.request; urllib.request.urlopen('http://localhost:8082/health')\"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 60s
    restart: unless-stopped"
    fi

    # Determine Ollama config based on provider
    local ollama_service=""
    local ollama_depends=""
    if [ "$EMBEDDINGS_PROVIDER" == "ollama" ] && [ "$EMBEDDINGS_BASE_URL" == "http://ollama:11434" ]; then
        ollama_depends="ollama:"
        ollama_service="
  # Ollama for local embeddings and LLM inference
  ollama:
    build:
      context: .
      dockerfile: docker-deploy/Dockerfile.ollama
    container_name: robomonkey-ollama
    volumes:
      - ollama_data:/root/.ollama
    ports:
      - \"\${OLLAMA_PORT:-11434}:11434\"
    healthcheck:
      test: [\"CMD\", \"curl\", \"-f\", \"http://localhost:11434/api/tags\"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 30s
    restart: unless-stopped"
    fi

    cat > "$compose_file" << 'COMPOSE_HEADER'
# RoboMonkey MCP - Docker Compose Configuration
# Generated by install.sh
#
# Usage:
#   docker compose up -d              # Start all services
#   docker compose logs -f            # View logs
#   docker compose down               # Stop all services
#   docker compose run --rm mcp       # Run MCP server interactively

services:
  # PostgreSQL with pgvector - stores the indexed codebase
  postgres:
    image: pgvector/pgvector:pg16
    container_name: robomonkey-postgres
    environment:
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-postgres}
      POSTGRES_USER: ${POSTGRES_USER:-postgres}
      POSTGRES_DB: ${POSTGRES_DB:-robomonkey}
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ./scripts/init_db.sql:/docker-entrypoint-initdb.d/01_init_schema.sql:ro
COMPOSE_HEADER


    cat >> "$compose_file" << 'COMPOSE_POSTGRES_REST'
    ports:
      - "${POSTGRES_PORT:-5433}:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres -d robomonkey"]
      interval: 5s
      timeout: 5s
      retries: 10
    restart: unless-stopped
COMPOSE_POSTGRES_REST

    # Add local embedding service if needed
    if [ -n "$embeddings_service" ]; then
        echo "$embeddings_service" >> "$compose_file"
    fi

    # Add Ollama service if needed
    if [ -n "$ollama_service" ]; then
        echo "$ollama_service" >> "$compose_file"
    fi

    # Add daemon service
    cat >> "$compose_file" << 'COMPOSE_DAEMON'

  # RoboMonkey Daemon - background processing (embeddings, summaries, watching)
  daemon:
    build:
      context: .
      dockerfile: docker-deploy/Dockerfile.daemon
    container_name: robomonkey-daemon
    environment:
      DATABASE_URL: postgresql://${POSTGRES_USER:-postgres}:${POSTGRES_PASSWORD:-postgres}@postgres:5432/${POSTGRES_DB:-robomonkey}
      EMBEDDINGS_PROVIDER: ${EMBEDDINGS_PROVIDER:-ollama}
      EMBEDDINGS_MODEL: ${EMBEDDINGS_MODEL:-snowflake-arctic-embed2:latest}
      EMBEDDINGS_BASE_URL: ${EMBEDDINGS_BASE_URL:-http://ollama:11434}
      EMBEDDINGS_DIMENSION: ${EMBEDDINGS_DIMENSION:-1024}
      DEFAULT_REPO: ${DEFAULT_REPO:-}
COMPOSE_DAEMON

    # Add OpenAI key if using OpenAI
    if [ "$LLM_DEEP_PROVIDER" == "openai" ] && [ -n "$LLM_DEEP_API_KEY" ]; then
        echo "      OPENAI_API_KEY: \${OPENAI_API_KEY:-}" >> "$compose_file"
    fi

    cat >> "$compose_file" << 'COMPOSE_DAEMON_REST'
    volumes:
      - ./config:/app/config:ro
      - source_code:/source:ro
    depends_on:
      postgres:
        condition: service_healthy
COMPOSE_DAEMON_REST

    if [ -n "$embeddings_depends" ]; then
        cat >> "$compose_file" << 'COMPOSE_EMBED_DEP'
      embeddings:
        condition: service_healthy
COMPOSE_EMBED_DEP
    fi

    if [ -n "$ollama_depends" ]; then
        cat >> "$compose_file" << 'COMPOSE_OLLAMA_DEP'
      ollama:
        condition: service_healthy
COMPOSE_OLLAMA_DEP
    fi

    cat >> "$compose_file" << 'COMPOSE_DAEMON_END'
    restart: unless-stopped

  # RoboMonkey MCP Server - provides code search tools to IDEs
  mcp:
    build:
      context: .
      dockerfile: docker-deploy/Dockerfile.mcp
    container_name: robomonkey-mcp
    environment:
      DATABASE_URL: postgresql://${POSTGRES_USER:-postgres}:${POSTGRES_PASSWORD:-postgres}@postgres:5432/${POSTGRES_DB:-robomonkey}
      EMBEDDINGS_PROVIDER: ${EMBEDDINGS_PROVIDER:-ollama}
      EMBEDDINGS_MODEL: ${EMBEDDINGS_MODEL:-snowflake-arctic-embed2:latest}
      EMBEDDINGS_BASE_URL: ${EMBEDDINGS_BASE_URL:-http://ollama:11434}
      EMBEDDINGS_DIMENSION: ${EMBEDDINGS_DIMENSION:-1024}
      DEFAULT_REPO: ${DEFAULT_REPO:-}
    depends_on:
      postgres:
        condition: service_healthy
    stdin_open: true
    tty: true
    profiles:
      - mcp  # Only start with: docker compose run --rm mcp

  # RoboMonkey Web UI - admin panel
  webui:
    build:
      context: .
      dockerfile: docker-deploy/Dockerfile.webui
    container_name: robomonkey-webui
    environment:
      DATABASE_URL: postgresql://${POSTGRES_USER:-postgres}:${POSTGRES_PASSWORD:-postgres}@postgres:5432/${POSTGRES_DB:-robomonkey}
    ports:
      - "${WEBUI_PORT:-9832}:9832"
    depends_on:
      postgres:
        condition: service_healthy
    profiles:
      - webui  # Only start with: docker compose --profile webui up -d
    restart: unless-stopped

volumes:
  pgdata:
    name: robomonkey_pgdata
  ollama_data:
    name: robomonkey_ollama
  source_code:
    name: robomonkey_source

networks:
  default:
    name: robomonkey_network
COMPOSE_DAEMON_END

    log_success "Generated docker-compose.yml"
}

generate_docker_env() {
    log_step "Generating .env for Docker"

    local env_file="$PROJECT_ROOT/.env"

    cat > "$env_file" << EOF
# RoboMonkey Docker Configuration
# Generated by install.sh on $(date)

# PostgreSQL
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_DB=robomonkey
POSTGRES_PORT=${DB_PORT}

# Embeddings
EMBEDDINGS_PROVIDER=${EMBEDDINGS_PROVIDER}
EMBEDDINGS_MODEL=${EMBEDDINGS_MODEL}
EMBEDDINGS_DIMENSION=${EMBEDDINGS_DIMENSION}
EOF

    # Set embeddings URL based on provider
    if [ "$USE_LOCAL_EMBEDDINGS" == "true" ]; then
        echo "EMBEDDINGS_BASE_URL=http://embeddings:8082" >> "$env_file"
    elif [ "$EMBEDDINGS_PROVIDER" == "ollama" ]; then
        if [ "$OLLAMA_LOCATION" == "docker" ]; then
            echo "EMBEDDINGS_BASE_URL=http://ollama:11434" >> "$env_file"
        else
            echo "EMBEDDINGS_BASE_URL=${EMBEDDINGS_BASE_URL}" >> "$env_file"
        fi
    else
        echo "EMBEDDINGS_BASE_URL=${EMBEDDINGS_BASE_URL}" >> "$env_file"
    fi

    # Add API keys if present
    if [ -n "$EMBEDDINGS_API_KEY" ]; then
        echo "EMBEDDINGS_API_KEY=${EMBEDDINGS_API_KEY}" >> "$env_file"
    fi

    if [ "$LLM_DEEP_PROVIDER" == "openai" ] && [ -n "$LLM_DEEP_API_KEY" ]; then
        echo "" >> "$env_file"
        echo "# OpenAI API Key" >> "$env_file"
        echo "OPENAI_API_KEY=${LLM_DEEP_API_KEY}" >> "$env_file"
    fi

    # Add LLM model for Ollama container to pull (if using Ollama for LLM)
    if [ "$LLM_DEEP_PROVIDER" == "ollama" ]; then
        echo "" >> "$env_file"
        echo "# LLM Model for Ollama to pull" >> "$env_file"
        echo "LLM_MODEL=${LLM_DEEP_MODEL}" >> "$env_file"
    fi

    cat >> "$env_file" << EOF

# Default repository for MCP queries
DEFAULT_REPO=${DEFAULT_REPO:-}

# Ollama port (if using local Ollama in Docker)
OLLAMA_PORT=11434

# Web UI port
WEBUI_PORT=9832
EOF

    log_success "Generated .env file"
}

create_daemon_dockerfile() {
    local dockerfile="$PROJECT_ROOT/docker-deploy/Dockerfile.daemon"

    if [ -f "$dockerfile" ]; then
        log_info "Dockerfile.daemon already exists"
        return 0
    fi

    log_info "Creating Dockerfile.daemon"

    cat > "$dockerfile" << 'EOF'
# RoboMonkey Daemon Dockerfile
FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python package
COPY pyproject.toml README.md ./
COPY src/ ./src/

# Install the package
RUN pip install --no-cache-dir -e .

# Copy config files
COPY config/ ./config/

# Default command: run daemon
CMD ["robomonkey", "daemon", "run"]
EOF

    log_success "Created Dockerfile.daemon"
}

create_webui_dockerfile() {
    local dockerfile="$PROJECT_ROOT/docker-deploy/Dockerfile.webui"

    if [ -f "$dockerfile" ]; then
        log_info "Dockerfile.webui already exists"
        return 0
    fi

    log_info "Creating Dockerfile.webui"

    cat > "$dockerfile" << 'EOF'
# RoboMonkey Web UI Dockerfile
FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python package
COPY pyproject.toml README.md ./
COPY src/ ./src/

# Install the package with uvicorn
RUN pip install --no-cache-dir -e . uvicorn

# Copy config and static files
COPY config/ ./config/

# Expose web UI port
EXPOSE 9832

# Default command: run web UI
CMD ["python", "-m", "yonk_code_robomonkey.web.app"]
EOF

    log_success "Created Dockerfile.webui"
}

setup_docker_ollama_models() {
    log_step "Pulling Ollama models in Docker"

    # Wait for Ollama to be ready
    log_info "Waiting for Ollama container to be ready..."
    local retries=30
    while [ $retries -gt 0 ]; do
        if docker exec robomonkey-ollama ollama list &>/dev/null; then
            break
        fi
        sleep 2
        retries=$((retries-1))
    done

    if [ $retries -eq 0 ]; then
        log_warn "Ollama container not ready, skipping model pull"
        return 0
    fi

    # Pull embedding model
    log_info "Pulling embedding model: $EMBEDDINGS_MODEL"
    docker exec robomonkey-ollama ollama pull "$EMBEDDINGS_MODEL"

    # Pull LLM models if using Ollama for LLM
    if [ "$LLM_DEEP_PROVIDER" == "ollama" ]; then
        log_info "Pulling LLM model: $LLM_DEEP_MODEL"
        docker exec robomonkey-ollama ollama pull "$LLM_DEEP_MODEL"

        if [ "$LLM_SMALL_MODEL" != "$LLM_DEEP_MODEL" ]; then
            log_info "Pulling LLM model: $LLM_SMALL_MODEL"
            docker exec robomonkey-ollama ollama pull "$LLM_SMALL_MODEL"
        fi
    fi

    log_success "Ollama models pulled"
}

setup_embeddings_docker() {
    log_step "Embeddings Configuration (Docker)"

    echo ""
    echo "Embedding providers:"
    echo "  - Local (lightweight): CPU-based sentence-transformers in Docker"
    echo "  - Ollama: In Docker container or on host"
    echo "  - Cloud APIs: OpenAI, NVIDIA NIM, etc."
    echo ""

    local embed_choice=$(prompt_choice "Embeddings provider:" \
        "Local lightweight (sentence-transformers, CPU-only)" \
        "Ollama in Docker container (recommended)" \
        "Ollama on host machine" \
        "Cloud API (OpenAI, NIM, etc.)")

    case $embed_choice in
        0)
            # Local sentence-transformers in Docker
            EMBEDDINGS_PROVIDER="openai"  # Uses OpenAI-compatible API
            EMBEDDINGS_BASE_URL="http://embeddings:8082"
            OLLAMA_LOCATION="none"
            EMBEDDINGS_API_KEY=""
            USE_LOCAL_EMBEDDINGS=true
            NEED_DOCKER_OLLAMA=false

            echo ""
            local local_model_choice=$(prompt_choice "Select local embedding model:" \
                "all-MiniLM-L6-v2 (384d, fast, ~80MB) - RECOMMENDED" \
                "all-mpnet-base-v2 (768d, better quality, ~420MB)")

            case $local_model_choice in
                0)
                    EMBEDDINGS_MODEL="all-MiniLM-L6-v2"
                    EMBEDDINGS_DIMENSION=384
                    ;;
                1)
                    EMBEDDINGS_MODEL="all-mpnet-base-v2"
                    EMBEDDINGS_DIMENSION=768
                    ;;
            esac

            log_info "Local embedding service will run in Docker on port 8082"
            log_info "Model: $EMBEDDINGS_MODEL ($EMBEDDINGS_DIMENSION dimensions)"
            ;;
        1)
            # Ollama in Docker
            EMBEDDINGS_PROVIDER="ollama"
            EMBEDDINGS_BASE_URL="http://ollama:11434"
            OLLAMA_LOCATION="docker"
            EMBEDDINGS_API_KEY=""
            USE_LOCAL_EMBEDDINGS=false

            echo ""
            local model_choice=$(prompt_choice "Select embedding model:" \
                "snowflake-arctic-embed2:latest (1024d, 8k context) - RECOMMENDED" \
                "nomic-embed-text (768d, 2k context)" \
                "mxbai-embed-large (1024d, 512 context)" \
                "Custom model")

            case $model_choice in
                0)
                    EMBEDDINGS_MODEL="snowflake-arctic-embed2:latest"
                    EMBEDDINGS_DIMENSION=1024
                    ;;
                1)
                    EMBEDDINGS_MODEL="nomic-embed-text"
                    EMBEDDINGS_DIMENSION=768
                    ;;
                2)
                    EMBEDDINGS_MODEL="mxbai-embed-large"
                    EMBEDDINGS_DIMENSION=1024
                    ;;
                3)
                    EMBEDDINGS_MODEL=$(prompt_input "Model name")
                    EMBEDDINGS_DIMENSION=$(prompt_input "Embedding dimension" "1024")
                    ;;
            esac
            NEED_DOCKER_OLLAMA=true
            ;;
        2)
            # Ollama on host
            EMBEDDINGS_PROVIDER="ollama"
            EMBEDDINGS_BASE_URL="http://host.docker.internal:11434"
            OLLAMA_LOCATION="host"
            EMBEDDINGS_API_KEY=""
            USE_LOCAL_EMBEDDINGS=false
            EMBEDDINGS_MODEL=$(prompt_input "Embedding model" "$DEFAULT_EMBEDDING_MODEL")
            EMBEDDINGS_DIMENSION=$(prompt_input "Embedding dimension" "$DEFAULT_EMBEDDING_DIMENSION")
            NEED_DOCKER_OLLAMA=false
            ;;
        3)
            # Cloud APIs
            USE_LOCAL_EMBEDDINGS=false
            NEED_DOCKER_OLLAMA=false
            OLLAMA_LOCATION="none"

            echo ""
            local cloud_choice=$(prompt_choice "Select cloud provider:" \
                "OpenAI" \
                "NVIDIA NIM" \
                "Other (Together.ai, Groq, vLLM, etc.)")

            case $cloud_choice in
                0)
                    # OpenAI
                    EMBEDDINGS_PROVIDER="openai"
                    EMBEDDINGS_BASE_URL="https://api.openai.com"
                    echo ""
                    read -sp "OpenAI API Key: " EMBEDDINGS_API_KEY
                    echo ""
                    if [ -n "$EMBEDDINGS_API_KEY" ]; then
                        log_success "API key entered (${#EMBEDDINGS_API_KEY} characters)"
                    fi

                    echo ""
                    local openai_embed_choice=$(prompt_choice "Select embedding model:" \
                        "text-embedding-3-small (1536d, cheap, good quality)" \
                        "text-embedding-3-large (3072d, best quality)" \
                        "Custom model")

                    case $openai_embed_choice in
                        0)
                            EMBEDDINGS_MODEL="text-embedding-3-small"
                            EMBEDDINGS_DIMENSION=1536
                            ;;
                        1)
                            EMBEDDINGS_MODEL="text-embedding-3-large"
                            EMBEDDINGS_DIMENSION=3072
                            ;;
                        2)
                            EMBEDDINGS_MODEL=$(prompt_input "Model name")
                            EMBEDDINGS_DIMENSION=$(prompt_input "Embedding dimension" "1536")
                            ;;
                    esac
                    ;;
                1)
                    # NVIDIA NIM
                    EMBEDDINGS_PROVIDER="openai"
                    EMBEDDINGS_BASE_URL=$(prompt_input "NVIDIA NIM endpoint" "https://integrate.api.nvidia.com/v1")
                    echo ""
                    read -sp "NVIDIA API Key: " EMBEDDINGS_API_KEY
                    echo ""
                    if [ -n "$EMBEDDINGS_API_KEY" ]; then
                        log_success "API key entered (${#EMBEDDINGS_API_KEY} characters)"
                    fi

                    echo ""
                    local nim_embed_choice=$(prompt_choice "Select NIM embedding model:" \
                        "nvidia/nv-embedqa-e5-v5 (1024d)" \
                        "nvidia/nv-embed-v1 (4096d)" \
                        "snowflake/arctic-embed-l (1024d)" \
                        "Custom model")

                    case $nim_embed_choice in
                        0)
                            EMBEDDINGS_MODEL="nvidia/nv-embedqa-e5-v5"
                            EMBEDDINGS_DIMENSION=1024
                            ;;
                        1)
                            EMBEDDINGS_MODEL="nvidia/nv-embed-v1"
                            EMBEDDINGS_DIMENSION=4096
                            ;;
                        2)
                            EMBEDDINGS_MODEL="snowflake/arctic-embed-l"
                            EMBEDDINGS_DIMENSION=1024
                            ;;
                        3)
                            EMBEDDINGS_MODEL=$(prompt_input "Model name")
                            EMBEDDINGS_DIMENSION=$(prompt_input "Embedding dimension" "1024")
                            ;;
                    esac
                    ;;
                2)
                    # Other
                    EMBEDDINGS_PROVIDER="openai"
                    EMBEDDINGS_BASE_URL=$(prompt_input "API endpoint URL")
                    echo ""
                    read -sp "API Key: " EMBEDDINGS_API_KEY
                    echo ""
                    if [ -n "$EMBEDDINGS_API_KEY" ]; then
                        log_success "API key entered (${#EMBEDDINGS_API_KEY} characters)"
                    fi
                    EMBEDDINGS_MODEL=$(prompt_input "Model name")
                    EMBEDDINGS_DIMENSION=$(prompt_input "Embedding dimension" "1024")
                    ;;
            esac
            ;;
    esac

}

setup_database_docker() {
    log_step "Database Setup (Docker)"

    DB_SETUP="fresh"
    USE_SAMPLE_DATA=false
    DEFAULT_REPO=""

    DB_PORT=$(prompt_input "PostgreSQL port (host)" "$DEFAULT_DB_PORT")
}

main_docker() {
    print_banner

    echo -e "\nWelcome to the RoboMonkey MCP installer!"
    echo -e "Installation mode: ${GREEN}Docker${NC} (all services run in containers)"
    echo ""

    # Detect OS
    detect_os

    # Check Docker prerequisites only
    log_step "Checking Prerequisites"

    local prereqs_ok=true

    check_docker || prereqs_ok=false
    check_docker_compose || prereqs_ok=false

    if [ "$prereqs_ok" == "false" ]; then
        log_error "Please install Docker and re-run this script"
        echo ""
        echo "Install Docker: https://docs.docker.com/get-docker/"
        exit 1
    fi

    # Interactive setup
    setup_database_docker
    setup_embeddings_docker
    setup_llm_options

    # Summary
    log_step "Installation Summary"
    echo ""
    echo "Mode: Docker (containerized)"
    echo ""
    echo "Database:"
    echo "  - Setup: $DB_SETUP"
    echo "  - Port: $DB_PORT"
    if [ "$USE_SAMPLE_DATA" == "true" ]; then
        echo "  - Sample data: Yes (sko_test repository)"
    fi
    echo ""
    echo "Embeddings:"
    echo "  - Provider: $EMBEDDINGS_PROVIDER"
    echo "  - Model: $EMBEDDINGS_MODEL"
    echo "  - Dimension: $EMBEDDINGS_DIMENSION"
    if [ "$OLLAMA_LOCATION" == "docker" ]; then
        echo "  - Location: Docker container"
    elif [ "$OLLAMA_LOCATION" == "host" ]; then
        echo "  - Location: Host machine"
    fi
    echo ""
    echo "LLM:"
    echo "  - Deep: $LLM_DEEP_PROVIDER / $LLM_DEEP_MODEL"
    echo "  - Small: $LLM_SMALL_PROVIDER / $LLM_SMALL_MODEL"
    echo ""

    if ! prompt_yes_no "Proceed with installation?"; then
        log_info "Installation cancelled"
        exit 0
    fi

    # Start installation
    log_step "Starting Docker Installation"

    # Create Dockerfiles if needed
    create_daemon_dockerfile
    create_webui_dockerfile

    # Generate configuration files
    generate_docker_env
    generate_daemon_config
    generate_docker_compose

    # Build and start services
    log_step "Building Docker images"
    cd "$PROJECT_ROOT"

    # Determine which services to start
    local services="postgres daemon"
    if [ "$NEED_DOCKER_OLLAMA" == "true" ]; then
        services="postgres ollama daemon"
    fi

    log_info "Building images..."
    $DOCKER_COMPOSE build daemon

    log_info "Starting services: $services"
    $DOCKER_COMPOSE up -d $services

    # Wait for postgres to be healthy
    log_info "Waiting for PostgreSQL to be ready..."
    local retries=30
    while [ $retries -gt 0 ]; do
        if docker exec robomonkey-postgres pg_isready -U postgres &>/dev/null; then
            log_success "PostgreSQL is ready"
            break
        fi
        sleep 2
        retries=$((retries-1))
    done

    # Pull Ollama models if using Docker Ollama
    if [ "$NEED_DOCKER_OLLAMA" == "true" ]; then
        setup_docker_ollama_models
    fi

    # Installation complete
    echo ""
    log_step "Installation Complete!"
    echo ""
    echo -e "${GREEN}RoboMonkey is now running in Docker!${NC}"
    echo ""

    echo -e "${BOLD}Services running:${NC}"
    echo "  - PostgreSQL:  localhost:$DB_PORT"
    if [ "$NEED_DOCKER_OLLAMA" == "true" ]; then
        echo "  - Ollama:      localhost:11434"
    fi
    echo "  - Daemon:      background processing"
    echo ""

    echo -e "${BOLD}Quick Reference:${NC}"
    echo ""
    echo "  View logs:"
    echo "     ${CYAN}docker compose logs -f${NC}"
    echo ""
    echo "  Run MCP server (for IDE integration):"
    echo "     ${CYAN}docker compose run --rm mcp${NC}"
    echo ""
    echo "  Start Web UI (http://localhost:9832):"
    echo "     ${CYAN}docker compose --profile webui up -d${NC}"
    echo ""
    echo "  Stop all services:"
    echo "     ${CYAN}docker compose down${NC}"
    echo ""
    echo "  Index a repository:"
    echo "     ${CYAN}docker compose exec daemon robomonkey index --repo /source/myrepo --name myrepo${NC}"
    echo ""

    echo "For IDE integration, see: docs/INSTALL.md#d-ide-integration"
    echo ""
    echo -e "${CYAN}Happy coding!${NC}"
}

# =============================================================================
# Native Installation Flow (original main function renamed)
# =============================================================================

main_native() {
    print_banner

    echo -e "\nWelcome to the RoboMonkey MCP installer!"
    echo -e "Installation mode: ${YELLOW}Native${NC} (install on host system)"
    echo ""

    # Detect OS
    detect_os

    # Check prerequisites
    log_step "Checking Prerequisites"

    local prereqs_ok=true

    check_python || prereqs_ok=false
    check_docker || prereqs_ok=false
    check_docker_compose || prereqs_ok=false
    check_git || prereqs_ok=false

    if [ "$prereqs_ok" == "false" ]; then
        log_error "Please install missing prerequisites and re-run this script"
        exit 1
    fi

    # Interactive setup
    setup_database_options
    setup_embeddings_options
    setup_llm_options
    setup_service_options

    # Summary before proceeding
    log_step "Installation Summary"
    echo ""
    echo "Database:"
    echo "  - Setup: $DB_SETUP"
    echo "  - Host: $DB_HOST:$DB_PORT"
    echo "  - Name: $DB_NAME"
    if [ "$USE_SAMPLE_DATA" == "true" ]; then
        echo "  - Sample data: Yes (sko_test repository)"
    fi
    echo ""
    echo "Embeddings:"
    echo "  - Provider: $EMBEDDINGS_PROVIDER"
    echo "  - Model: $EMBEDDINGS_MODEL"
    echo "  - Dimension: $EMBEDDINGS_DIMENSION"
    echo "  - URL: $EMBEDDINGS_BASE_URL"
    if [ "$NEED_REBUILD_EMBEDDINGS" == "true" ]; then
        echo "  - WARNING: Embeddings will need to be regenerated"
    fi
    echo ""
    echo "LLM:"
    echo "  - Deep: $LLM_DEEP_PROVIDER / $LLM_DEEP_MODEL"
    echo "  - Small: $LLM_SMALL_PROVIDER / $LLM_SMALL_MODEL"
    echo ""
    echo "Services:"
    echo "  - Start daemon now: $([ "$START_DAEMON_NOW" == "true" ] && echo "Yes" || echo "No")"
    echo "  - Auto-start service: $([ "$SETUP_AUTOSTART" == "true" ] && echo "Yes" || echo "No")"
    if [ "$SETUP_AUTOSTART" == "true" ]; then
        echo "  - Include Web UI: $([ "$AUTOSTART_WEB_UI" == "true" ] && echo "Yes" || echo "No")"
    fi
    echo ""

    if ! prompt_yes_no "Proceed with installation?"; then
        log_info "Installation cancelled"
        exit 0
    fi

    # Start installation
    log_step "Starting Installation"

    # 1. Setup Python environment
    setup_python_env

    # 2. Setup database
    if [ "$DB_SETUP" == "fresh" ] || [ "$DB_SETUP" == "sample" ]; then
        setup_postgres_docker
    fi

    # 3. Generate configuration files
    generate_env_file
    generate_daemon_config

    # 4. Initialize database
    if [ "$DB_SETUP" != "sample" ]; then
        init_database
    fi

    # 5. Restore sample data if selected
    if [ "$USE_SAMPLE_DATA" == "true" ]; then
        restore_sample_database
    fi

    # 6. Start Ollama and pull models if needed
    if [ "$NEED_OLLAMA_START" == "true" ]; then
        start_ollama
    fi

    if [ "$NEED_EMBEDDING_MODEL" == "true" ] && [ "$EMBEDDINGS_PROVIDER" == "ollama" ]; then
        if [ "$OLLAMA_IS_DOCKER" == "true" ]; then
            pull_ollama_model_docker "$EMBEDDINGS_MODEL"
        else
            pull_ollama_model "$EMBEDDINGS_MODEL"
        fi
    fi

    if [ "$NEED_LLM_MODELS" == "true" ]; then
        if [ "$LLM_DEEP_PROVIDER" == "ollama" ]; then
            if [ "$OLLAMA_IS_DOCKER" == "true" ]; then
                pull_ollama_model_docker "$LLM_DEEP_MODEL"
                if [ "$LLM_SMALL_MODEL" != "$LLM_DEEP_MODEL" ]; then
                    pull_ollama_model_docker "$LLM_SMALL_MODEL"
                fi
            else
                pull_ollama_model "$LLM_DEEP_MODEL"
                if [ "$LLM_SMALL_MODEL" != "$LLM_DEEP_MODEL" ]; then
                    pull_ollama_model "$LLM_SMALL_MODEL"
                fi
            fi
        fi
    fi

    # 7. Rebuild embeddings if needed
    if [ "$NEED_REBUILD_EMBEDDINGS" == "true" ]; then
        log_step "Regenerating Embeddings"
        log_warn "This may take a while depending on the size of the sample data..."

        cd "$PROJECT_ROOT"
        source .venv/bin/activate

        # Clear existing embeddings and regenerate
        python scripts/embed_repo_direct.py sko_test robomonkey_sko_test
    fi

    # 8. Setup auto-start service if requested
    if [ "$SETUP_AUTOSTART" == "true" ]; then
        setup_autostart_service
    fi

    # 9. Start local embedding service if using local embeddings
    if [ "$USE_LOCAL_EMBEDDINGS" == "true" ]; then
        start_local_embeddings
    fi

    # 10. Start daemon now if requested
    if [ "$START_DAEMON_NOW" == "true" ]; then
        start_daemon_once
    fi

    # Installation complete
    echo ""
    log_step "Installation Complete!"
    echo ""
    echo -e "${GREEN}RoboMonkey MCP has been installed successfully!${NC}"
    echo ""

    # Show service status
    if [ "$USE_LOCAL_EMBEDDINGS" == "true" ]; then
        echo -e "${GREEN}Local embedding service running${NC} (PID: $(cat $PROJECT_ROOT/embeddings.pid 2>/dev/null || echo 'unknown'))"
    fi
    if [ "$START_DAEMON_NOW" == "true" ]; then
        echo -e "${GREEN}Daemon is running${NC} (PID: $(cat $PROJECT_ROOT/daemon.pid 2>/dev/null || echo 'unknown'))"
    fi
    if [ "$SETUP_AUTOSTART" == "true" ]; then
        echo -e "${GREEN}Auto-start service configured${NC}"
    fi
    echo ""

    # Show commands reference
    echo -e "${BOLD}Quick Reference:${NC}"
    echo ""
    echo "  Activate environment:"
    echo "     ${CYAN}source $PROJECT_ROOT/.venv/bin/activate${NC}"
    echo ""
    echo "  Start Daemon (foreground):"
    echo "     ${CYAN}robomonkey daemon run${NC}"
    echo ""
    echo "  Start Daemon (background):"
    echo "     ${CYAN}nohup robomonkey daemon run > daemon.log 2>&1 &${NC}"
    echo ""
    echo "  Start Web UI (http://localhost:9832):"
    echo "     ${CYAN}python -m yonk_code_robomonkey.web.app${NC}"
    echo ""
    echo "  Start MCP Server (stdio mode for IDEs):"
    echo "     ${CYAN}python -m yonk_code_robomonkey.mcp.server${NC}"
    echo ""

    if [ "$SETUP_AUTOSTART" == "true" ]; then
        echo -e "${BOLD}Service Management:${NC}"
        echo ""
        if [ "$OS" == "linux" ]; then
            echo "  Start daemon:  ${CYAN}sudo systemctl start robomonkey-daemon${NC}"
            echo "  Stop daemon:   ${CYAN}sudo systemctl stop robomonkey-daemon${NC}"
            echo "  View logs:     ${CYAN}sudo journalctl -u robomonkey-daemon -f${NC}"
            if [ "$AUTOSTART_WEB_UI" == "true" ]; then
                echo "  Start Web UI:  ${CYAN}sudo systemctl start robomonkey-webui${NC}"
            fi
        else
            echo "  Start daemon:  ${CYAN}launchctl start com.robomonkey.daemon${NC}"
            echo "  Stop daemon:   ${CYAN}launchctl stop com.robomonkey.daemon${NC}"
            echo "  View logs:     ${CYAN}tail -f $PROJECT_ROOT/daemon.log${NC}"
            if [ "$AUTOSTART_WEB_UI" == "true" ]; then
                echo "  Start Web UI:  ${CYAN}launchctl start com.robomonkey.webui${NC}"
            fi
        fi
        echo ""
    fi

    # Show next steps based on setup
    echo -e "${BOLD}Next Steps:${NC}"
    echo ""

    if [ "$USE_SAMPLE_DATA" == "true" ]; then
        echo "  1. Test the installation:"
        echo "     ${CYAN}robomonkey db ping${NC}"
        echo "     ${CYAN}robomonkey repo ls${NC}"
        echo ""
        if [ "$START_DAEMON_NOW" != "true" ] && [ "$SETUP_AUTOSTART" != "true" ]; then
            echo "  2. Start the daemon to enable background processing:"
            echo "     ${CYAN}robomonkey daemon run${NC}"
            echo ""
        fi
    else
        echo "  1. Index your first repository:"
        echo "     ${CYAN}robomonkey index --repo /path/to/repo --name myrepo${NC}"
        echo ""
        echo "  2. Generate embeddings:"
        echo "     ${CYAN}python scripts/embed_repo_direct.py myrepo robomonkey_myrepo${NC}"
        echo ""
        if [ "$START_DAEMON_NOW" != "true" ] && [ "$SETUP_AUTOSTART" != "true" ]; then
            echo "  3. Start the daemon:"
            echo "     ${CYAN}robomonkey daemon run${NC}"
            echo ""
        fi
    fi

    echo "For IDE integration, see: docs/INSTALL.md#d-ide-integration"
    echo ""
    echo -e "${CYAN}Happy coding!${NC}"
}

# =============================================================================
# Main Entry Point
# =============================================================================

main() {
    if [ "$INSTALL_MODE" == "docker" ]; then
        main_docker
    else
        main_native
    fi
}

# Run main function
main "$@"
