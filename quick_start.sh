#!/bin/bash
set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}================================================${NC}"
echo -e "${BLUE}  RoboMonkey Quick Start${NC}"
echo -e "${BLUE}================================================${NC}"
echo ""

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Check prerequisites
echo -e "${YELLOW}[1/8] Checking prerequisites...${NC}"
command -v docker >/dev/null 2>&1 || { echo -e "${RED}Error: docker is not installed${NC}" >&2; exit 1; }
command -v docker-compose >/dev/null 2>&1 || command -v docker compose >/dev/null 2>&1 || { echo -e "${RED}Error: docker-compose is not installed${NC}" >&2; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo -e "${RED}Error: python3 is not installed${NC}" >&2; exit 1; }
echo -e "${GREEN}✓ All prerequisites found${NC}"
echo ""

# Check if virtual environment exists
if [ ! -d ".venv" ]; then
    echo -e "${YELLOW}[2/8] Creating virtual environment...${NC}"
    python3 -m venv .venv
    echo -e "${GREEN}✓ Virtual environment created${NC}"
else
    echo -e "${YELLOW}[2/8] Virtual environment already exists${NC}"
fi
echo ""

# Activate virtual environment and install
echo -e "${YELLOW}[3/8] Installing RoboMonkey...${NC}"
source .venv/bin/activate
pip install -q -e . || { echo -e "${RED}Error: Failed to install RoboMonkey${NC}" >&2; exit 1; }
echo -e "${GREEN}✓ RoboMonkey installed${NC}"
echo ""

# Start Docker Compose
echo -e "${YELLOW}[4/8] Starting PostgreSQL with pgvector...${NC}"
if command -v docker-compose >/dev/null 2>&1; then
    docker-compose up -d
else
    docker compose up -d
fi

# Wait for postgres to be ready
echo -e "${YELLOW}Waiting for PostgreSQL to be ready...${NC}"
sleep 5
max_retries=30
retry_count=0
while [ $retry_count -lt $max_retries ]; do
    if .venv/bin/robomonkey db ping >/dev/null 2>&1; then
        break
    fi
    retry_count=$((retry_count + 1))
    echo -n "."
    sleep 1
done

if [ $retry_count -eq $max_retries ]; then
    echo -e "${RED}Error: PostgreSQL did not start in time${NC}" >&2
    exit 1
fi
echo ""
echo -e "${GREEN}✓ PostgreSQL is ready${NC}"
echo ""

# Initialize database
echo -e "${YELLOW}[5/10] Initializing database schema...${NC}"
if .venv/bin/robomonkey db ping | grep -q "already initialized"; then
    echo -e "${GREEN}✓ Database already initialized${NC}"
else
    .venv/bin/robomonkey db init || { echo -e "${RED}Error: Failed to initialize database${NC}" >&2; exit 1; }
    echo -e "${GREEN}✓ Database initialized${NC}"
fi
echo ""

# LLM/Embeddings configuration
echo -e "${YELLOW}[6/10] LLM and Embeddings Configuration${NC}"
echo -e "${BLUE}Configure your AI models:${NC}"
echo ""

# Embeddings provider
echo -e "${BLUE}Embeddings Provider:${NC}"
echo "  1) ollama (local, recommended)"
echo "  2) vllm (OpenAI-compatible API, local)"
echo "  3) openai (OpenAI API, cloud)"
read -p "Choose provider [1]: " PROVIDER_CHOICE
PROVIDER_CHOICE=${PROVIDER_CHOICE:-1}

case "$PROVIDER_CHOICE" in
    2)
        EMBEDDINGS_PROVIDER="vllm"
        ;;
    3)
        EMBEDDINGS_PROVIDER="openai"
        ;;
    *)
        EMBEDDINGS_PROVIDER="ollama"
        ;;
esac
echo -e "${GREEN}Using provider: $EMBEDDINGS_PROVIDER${NC}"

# API key (for vLLM and OpenAI)
EMBEDDINGS_API_KEY=""
if [ "$EMBEDDINGS_PROVIDER" = "vllm" ]; then
    read -p "vLLM API key (optional, press Enter to skip): " EMBEDDINGS_API_KEY
elif [ "$EMBEDDINGS_PROVIDER" = "openai" ]; then
    echo -e "${YELLOW}Note: API key needed for embedding generation (can be added later to .env)${NC}"
    read -p "OpenAI API key (press Enter to skip for now): " EMBEDDINGS_API_KEY
    if [ -z "$EMBEDDINGS_API_KEY" ]; then
        echo -e "${YELLOW}⚠ No API key provided - embeddings will fail until key is added to .env${NC}"
    fi
fi

# Embeddings base URL
case "$EMBEDDINGS_PROVIDER" in
    ollama)
        read -p "Ollama base URL [http://localhost:11434]: " EMBEDDINGS_BASE_URL
        EMBEDDINGS_BASE_URL=${EMBEDDINGS_BASE_URL:-http://localhost:11434}
        ;;
    vllm)
        read -p "vLLM base URL [http://localhost:8000]: " EMBEDDINGS_BASE_URL
        EMBEDDINGS_BASE_URL=${EMBEDDINGS_BASE_URL:-http://localhost:8000}
        ;;
    openai)
        read -p "OpenAI base URL [https://api.openai.com/v1]: " EMBEDDINGS_BASE_URL
        EMBEDDINGS_BASE_URL=${EMBEDDINGS_BASE_URL:-https://api.openai.com/v1}
        ;;
esac

# Verify provider is accessible
echo -e "${YELLOW}Verifying $EMBEDDINGS_PROVIDER is accessible...${NC}"
case "$EMBEDDINGS_PROVIDER" in
    ollama)
        if curl -s "$EMBEDDINGS_BASE_URL/api/tags" >/dev/null 2>&1; then
            echo -e "${GREEN}✓ Ollama is accessible${NC}"

            # List available models
            echo ""
            echo -e "${BLUE}Available Ollama models:${NC}"
            curl -s "$EMBEDDINGS_BASE_URL/api/tags" | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    models = data.get('models', [])
    embed_models = [m for m in models if 'embed' in m.get('name', '').lower()]
    if embed_models:
        for m in embed_models:
            print(f\"  - {m['name']}\")
    else:
        print('  (No embedding models found)')
except:
    print('  (Could not parse models)')
" || echo "  (Could not list models)"
        else
            echo -e "${RED}Warning: Cannot connect to Ollama at $EMBEDDINGS_BASE_URL${NC}"
            echo -e "${YELLOW}Make sure Ollama is running: ollama serve${NC}"
            read -p "Continue anyway? [y/N] " -n 1 -r
            echo ""
            if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                exit 1
            fi
        fi
        ;;
    vllm)
        if curl -s "$EMBEDDINGS_BASE_URL/health" >/dev/null 2>&1 || curl -s "$EMBEDDINGS_BASE_URL/v1/models" >/dev/null 2>&1; then
            echo -e "${GREEN}✓ vLLM is accessible${NC}"
        else
            echo -e "${RED}Warning: Cannot connect to vLLM at $EMBEDDINGS_BASE_URL${NC}"
            read -p "Continue anyway? [y/N] " -n 1 -r
            echo ""
            if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                exit 1
            fi
        fi
        ;;
    openai)
        if [ -n "$EMBEDDINGS_API_KEY" ]; then
            if curl -s -H "Authorization: Bearer $EMBEDDINGS_API_KEY" "$EMBEDDINGS_BASE_URL/models" | grep -q "text-embedding"; then
                echo -e "${GREEN}✓ OpenAI API is accessible${NC}"
            else
                echo -e "${RED}Warning: Cannot connect to OpenAI API${NC}"
                echo -e "${YELLOW}Check your API key and internet connection${NC}"
                read -p "Continue anyway? [y/N] " -n 1 -r
                echo ""
                if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                    exit 1
                fi
            fi
        else
            echo -e "${YELLOW}Skipping API verification (no API key)${NC}"
        fi
        ;;
esac
echo ""

# Embeddings model
case "$EMBEDDINGS_PROVIDER" in
    ollama)
        read -p "Embeddings model [snowflake-arctic-embed2:latest]: " EMBEDDINGS_MODEL
        EMBEDDINGS_MODEL=${EMBEDDINGS_MODEL:-snowflake-arctic-embed2:latest}

        # Check if model exists, offer to pull
        echo -e "${YELLOW}Checking if model is available...${NC}"
        if curl -s "$EMBEDDINGS_BASE_URL/api/show" -d "{\"name\":\"$EMBEDDINGS_MODEL\"}" 2>/dev/null | grep -q "error"; then
            echo -e "${YELLOW}Model '$EMBEDDINGS_MODEL' not found locally${NC}"
            read -p "Pull model now? [Y/n] " -n 1 -r
            echo ""
            if [[ ! $REPLY =~ ^[Nn]$ ]]; then
                echo -e "${BLUE}Pulling model (this may take a few minutes)...${NC}"
                curl -s "$EMBEDDINGS_BASE_URL/api/pull" -d "{\"name\":\"$EMBEDDINGS_MODEL\"}" | \
                    python3 -c "
import json, sys
for line in sys.stdin:
    try:
        data = json.loads(line)
        status = data.get('status', '')
        if status:
            print(f'\r{status}', end='', flush=True)
    except:
        pass
print()
"
                echo -e "${GREEN}✓ Model pulled successfully${NC}"
            fi
        else
            echo -e "${GREEN}✓ Model is available${NC}"
        fi
        ;;
    vllm)
        read -p "Embeddings model name: " EMBEDDINGS_MODEL
        if [ -z "$EMBEDDINGS_MODEL" ]; then
            echo -e "${RED}Error: Model name is required${NC}" >&2
            exit 1
        fi
        ;;
    openai)
        echo -e "${BLUE}OpenAI embedding models:${NC}"
        echo "  1) text-embedding-3-small (1536 dim, $0.02/1M tokens)"
        echo "  2) text-embedding-3-large (3072 dim, $0.13/1M tokens)"
        echo "  3) text-embedding-ada-002 (1536 dim, legacy)"
        read -p "Choose model [1]: " OPENAI_MODEL_CHOICE
        OPENAI_MODEL_CHOICE=${OPENAI_MODEL_CHOICE:-1}

        case "$OPENAI_MODEL_CHOICE" in
            2)
                EMBEDDINGS_MODEL="text-embedding-3-large"
                ;;
            3)
                EMBEDDINGS_MODEL="text-embedding-ada-002"
                ;;
            *)
                EMBEDDINGS_MODEL="text-embedding-3-small"
                ;;
        esac
        echo -e "${GREEN}Using model: $EMBEDDINGS_MODEL${NC}"
        ;;
esac
echo ""

# Embeddings dimension
echo -e "${BLUE}Common embedding dimensions:${NC}"
case "$EMBEDDINGS_PROVIDER" in
    ollama)
        echo "  - snowflake-arctic-embed2:latest: 1024"
        echo "  - nomic-embed-text: 768"
        echo "  - mxbai-embed-large: 1024"
        read -p "Embeddings dimension [1024]: " EMBEDDINGS_DIMENSION
        EMBEDDINGS_DIMENSION=${EMBEDDINGS_DIMENSION:-1024}
        ;;
    vllm)
        read -p "Embeddings dimension: " EMBEDDINGS_DIMENSION
        if [ -z "$EMBEDDINGS_DIMENSION" ]; then
            echo -e "${RED}Error: Dimension is required${NC}" >&2
            exit 1
        fi
        ;;
    openai)
        case "$EMBEDDINGS_MODEL" in
            text-embedding-3-large)
                echo "  - text-embedding-3-large supports: 256-3072 dimensions"
                read -p "Embeddings dimension [3072]: " EMBEDDINGS_DIMENSION
                EMBEDDINGS_DIMENSION=${EMBEDDINGS_DIMENSION:-3072}
                ;;
            *)
                echo "  - $EMBEDDINGS_MODEL: 1536 dimensions (fixed)"
                EMBEDDINGS_DIMENSION=1536
                ;;
        esac
        ;;
esac
echo -e "${GREEN}Using dimension: $EMBEDDINGS_DIMENSION${NC}"
echo ""

# LLM configuration for summaries and tag suggestions
echo -e "${BLUE}LLM Configuration (for summaries, tag suggestions):${NC}"
echo ""
echo "Use same provider as embeddings?"
read -p "Use $EMBEDDINGS_PROVIDER for LLM? [Y/n] " -n 1 -r
echo ""

if [[ $REPLY =~ ^[Nn]$ ]]; then
    # Different LLM provider
    echo -e "${BLUE}LLM Provider:${NC}"
    echo "  1) ollama (local, recommended)"
    echo "  2) vllm (OpenAI-compatible API, local)"
    echo "  3) openai (OpenAI API, cloud)"
    read -p "Choose LLM provider [1]: " LLM_PROVIDER_CHOICE
    LLM_PROVIDER_CHOICE=${LLM_PROVIDER_CHOICE:-1}

    case "$LLM_PROVIDER_CHOICE" in
        2)
            LLM_PROVIDER="vllm"
            ;;
        3)
            LLM_PROVIDER="openai"
            ;;
        *)
            LLM_PROVIDER="ollama"
            ;;
    esac

    # LLM API key
    LLM_API_KEY=""
    if [ "$LLM_PROVIDER" = "vllm" ]; then
        read -p "vLLM API key (optional): " LLM_API_KEY
    elif [ "$LLM_PROVIDER" = "openai" ]; then
        echo -e "${YELLOW}Note: API key needed for summary generation (can be added later to .env)${NC}"
        read -p "OpenAI API key (press Enter to skip): " LLM_API_KEY
        if [ -z "$LLM_API_KEY" ]; then
            echo -e "${YELLOW}⚠ No API key - summaries will fail until key is added${NC}"
        fi
    fi

    # LLM base URL
    case "$LLM_PROVIDER" in
        ollama)
            read -p "Ollama base URL [http://localhost:11434]: " LLM_BASE_URL
            LLM_BASE_URL=${LLM_BASE_URL:-http://localhost:11434}
            ;;
        vllm)
            read -p "vLLM base URL [http://localhost:8000]: " LLM_BASE_URL
            LLM_BASE_URL=${LLM_BASE_URL:-http://localhost:8000}
            ;;
        openai)
            read -p "OpenAI base URL [https://api.openai.com/v1]: " LLM_BASE_URL
            LLM_BASE_URL=${LLM_BASE_URL:-https://api.openai.com/v1}
            ;;
    esac
else
    # Use same provider as embeddings
    LLM_PROVIDER="$EMBEDDINGS_PROVIDER"
    LLM_API_KEY="$EMBEDDINGS_API_KEY"
    LLM_BASE_URL="$EMBEDDINGS_BASE_URL"
fi

echo -e "${GREEN}Using LLM provider: $LLM_PROVIDER${NC}"
echo ""

# LLM model selection
case "$LLM_PROVIDER" in
    ollama)
        echo -e "${BLUE}Recommended Ollama LLM models:${NC}"
        echo "  - qwen2.5-coder:7b (fast, good quality)"
        echo "  - qwen2.5-coder:14b (balanced)"
        echo "  - deepseek-coder:33b (best quality, slower)"
        read -p "LLM model [qwen2.5-coder:7b]: " LLM_MODEL
        LLM_MODEL=${LLM_MODEL:-qwen2.5-coder:7b}
        ;;
    vllm)
        read -p "LLM model name: " LLM_MODEL
        if [ -z "$LLM_MODEL" ]; then
            echo -e "${RED}Error: Model name is required${NC}" >&2
            exit 1
        fi
        ;;
    openai)
        echo -e "${BLUE}OpenAI LLM models:${NC}"
        echo "  1) gpt-4o (best quality, $5/1M input tokens)"
        echo "  2) gpt-4o-mini (fast, cheap, $0.15/1M input tokens)"
        echo "  3) gpt-3.5-turbo (legacy, $0.50/1M input tokens)"
        read -p "Choose model [2]: " OPENAI_LLM_CHOICE
        OPENAI_LLM_CHOICE=${OPENAI_LLM_CHOICE:-2}

        case "$OPENAI_LLM_CHOICE" in
            1)
                LLM_MODEL="gpt-4o"
                ;;
            3)
                LLM_MODEL="gpt-3.5-turbo"
                ;;
            *)
                LLM_MODEL="gpt-4o-mini"
                ;;
        esac
        echo -e "${GREEN}Using model: $LLM_MODEL${NC}"
        ;;
esac

echo -e "${GREEN}LLM configured: $LLM_MODEL${NC}"
echo ""

# Create/update .env file
echo -e "${YELLOW}Creating .env configuration...${NC}"
cat > .env <<ENVEOF
# Database
DATABASE_URL=postgresql://postgres:postgres@localhost:5433/robomonkey

# Embeddings Provider
EMBEDDINGS_PROVIDER=$EMBEDDINGS_PROVIDER
EMBEDDINGS_MODEL=$EMBEDDINGS_MODEL
EMBEDDINGS_BASE_URL=$EMBEDDINGS_BASE_URL
EMBEDDINGS_DIMENSION=$EMBEDDINGS_DIMENSION
EMBEDDINGS_API_KEY=$EMBEDDINGS_API_KEY

# LLM Provider (for summaries, tag suggestions)
LLM_PROVIDER=$LLM_PROVIDER
LLM_MODEL=$LLM_MODEL
LLM_BASE_URL=$LLM_BASE_URL
LLM_API_KEY=$LLM_API_KEY

# Performance tuning
MAX_CHUNK_LENGTH=8192
EMBEDDING_BATCH_SIZE=100

# Search parameters
VECTOR_TOP_K=30
FTS_TOP_K=30
FINAL_TOP_K=12
CONTEXT_BUDGET_TOKENS=12000
GRAPH_DEPTH=2
ENVEOF

echo -e "${GREEN}✓ Configuration saved to .env${NC}"
if [ -n "$EMBEDDINGS_API_KEY" ] || [ -n "$LLM_API_KEY" ]; then
    echo -e "${YELLOW}⚠ API keys stored in .env - keep this file secure!${NC}"
fi
echo ""

# Prompt for repository details
echo -e "${YELLOW}[7/10] Repository configuration${NC}"
echo -e "${BLUE}Enter the repository details:${NC}"
echo ""

# Get repo name
while true; do
    read -p "Repository name (e.g., my-project): " REPO_NAME
    if [ -n "$REPO_NAME" ]; then
        # Sanitize repo name (lowercase, replace spaces/special chars with hyphens)
        REPO_NAME=$(echo "$REPO_NAME" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9-]/-/g' | sed 's/--*/-/g' | sed 's/^-//' | sed 's/-$//')
        echo -e "${GREEN}Using repository name: $REPO_NAME${NC}"
        break
    else
        echo -e "${RED}Repository name cannot be empty${NC}"
    fi
done

# Get repo directory
while true; do
    read -p "Repository directory (absolute path): " REPO_DIR

    # Expand tilde to home directory
    REPO_DIR="${REPO_DIR/#\~/$HOME}"

    if [ -n "$REPO_DIR" ] && [ -d "$REPO_DIR" ]; then
        # Convert to absolute path
        REPO_DIR=$(cd "$REPO_DIR" && pwd)
        echo -e "${GREEN}Using directory: $REPO_DIR${NC}"
        break
    else
        echo -e "${RED}Directory does not exist or is invalid${NC}"
    fi
done
echo ""

# Add repository to RoboMonkey
echo -e "${YELLOW}Adding repository to RoboMonkey...${NC}"
cat > /tmp/robomonkey_add_repo.py <<PYEOF
import asyncio
import asyncpg
import sys
from pathlib import Path

async def add_repo():
    repo_name = "$REPO_NAME"
    repo_dir = "$REPO_DIR"
    schema_name = f"robomonkey_{repo_name.replace('-', '_')}"

    conn = await asyncpg.connect(dsn='postgresql://postgres:postgres@localhost:5433/robomonkey')
    try:
        # Check if repo already exists
        exists = await conn.fetchval(
            "SELECT 1 FROM robomonkey_control.repo_registry WHERE name = \$1",
            repo_name
        )

        if exists:
            print(f"Repository '{repo_name}' already exists, updating...")
            await conn.execute(
                """UPDATE robomonkey_control.repo_registry
                   SET root_path = \$2, updated_at = NOW()
                   WHERE name = \$1""",
                repo_name, repo_dir
            )
        else:
            print(f"Adding repository '{repo_name}'...")
            await conn.execute(
                """INSERT INTO robomonkey_control.repo_registry
                   (name, schema_name, root_path, auto_embed)
                   VALUES (\$1, \$2, \$3, \$4)""",
                repo_name, schema_name, repo_dir, True
            )

        # Initialize schema
        print(f"Initializing schema '{schema_name}'...")
        from yonk_code_robomonkey.db.schema_manager import init_schema_tables
        await init_schema_tables(conn, schema_name)

        # Enqueue FULL_INDEX job
        print(f"Enqueuing indexing job...")
        job_id = await conn.fetchval(
            """INSERT INTO robomonkey_control.job_queue
               (repo_name, schema_name, job_type, payload, priority, status)
               VALUES (\$1, \$2, 'FULL_INDEX', '{}', 10, 'PENDING')
               RETURNING id""",
            repo_name, schema_name
        )

        print(f"✓ Repository added successfully!")
        print(f"  Schema: {schema_name}")
        print(f"  Job ID: {job_id}")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        await conn.close()

asyncio.run(add_repo())
PYEOF

python3 /tmp/robomonkey_add_repo.py || { echo -e "${RED}Error: Failed to add repository${NC}" >&2; exit 1; }
rm /tmp/robomonkey_add_repo.py
echo -e "${GREEN}✓ Repository added and indexing job enqueued${NC}"
echo ""

# Create MCP config in repo directory
echo -e "${YELLOW}[8/10] Creating MCP configuration...${NC}"

# Build MCP config with conditional API keys
MCP_ENV_VARS="\"DATABASE_URL\": \"postgresql://postgres:postgres@localhost:5433/robomonkey\",
        \"EMBEDDINGS_PROVIDER\": \"$EMBEDDINGS_PROVIDER\",
        \"EMBEDDINGS_MODEL\": \"$EMBEDDINGS_MODEL\",
        \"EMBEDDINGS_BASE_URL\": \"$EMBEDDINGS_BASE_URL\",
        \"EMBEDDINGS_DIMENSION\": \"$EMBEDDINGS_DIMENSION\""

if [ -n "$EMBEDDINGS_API_KEY" ]; then
    MCP_ENV_VARS="$MCP_ENV_VARS,
        \"EMBEDDINGS_API_KEY\": \"$EMBEDDINGS_API_KEY\""
fi

MCP_ENV_VARS="$MCP_ENV_VARS,
        \"LLM_PROVIDER\": \"$LLM_PROVIDER\",
        \"LLM_MODEL\": \"$LLM_MODEL\",
        \"LLM_BASE_URL\": \"$LLM_BASE_URL\""

if [ -n "$LLM_API_KEY" ]; then
    MCP_ENV_VARS="$MCP_ENV_VARS,
        \"LLM_API_KEY\": \"$LLM_API_KEY\""
fi

MCP_ENV_VARS="$MCP_ENV_VARS,
        \"DEFAULT_REPO\": \"$REPO_NAME\""

cat > "$REPO_DIR/.mcp.json" <<MCPEOF
{
  "mcpServers": {
    "yonk-code-robomonkey": {
      "type": "stdio",
      "command": "$SCRIPT_DIR/.venv/bin/python",
      "args": ["-m", "yonk_code_robomonkey.mcp.server"],
      "env": {
        $MCP_ENV_VARS
      }
    }
  }
}
MCPEOF
echo -e "${GREEN}✓ MCP config created at $REPO_DIR/.mcp.json${NC}"
if [ -n "$EMBEDDINGS_API_KEY" ] || [ -n "$LLM_API_KEY" ]; then
    echo -e "${YELLOW}⚠ API keys included in MCP config - keep this file secure!${NC}"
fi
echo ""

# Start daemon
echo -e "${YELLOW}[9/10] Starting RoboMonkey daemon...${NC}"

# Check if daemon is already running
if pgrep -f "robomonkey daemon" >/dev/null 2>&1; then
    echo -e "${YELLOW}Daemon already running, restarting...${NC}"
    pkill -f "robomonkey daemon" || true
    sleep 2
fi

# Start daemon in background
nohup .venv/bin/robomonkey daemon > robomonkey-daemon.log 2>&1 &
DAEMON_PID=$!
echo $DAEMON_PID > robomonkey-daemon.pid
sleep 2

# Check if daemon started successfully
if ps -p $DAEMON_PID > /dev/null; then
    echo -e "${GREEN}✓ Daemon started (PID: $DAEMON_PID)${NC}"
    echo -e "${BLUE}  Log file: robomonkey-daemon.log${NC}"
else
    echo -e "${RED}Error: Daemon failed to start${NC}" >&2
    echo -e "${YELLOW}Check robomonkey-daemon.log for details${NC}"
    exit 1
fi
echo ""

# Monitor progress
echo -e "${YELLOW}[10/10] Monitoring indexing progress...${NC}"
echo -e "${BLUE}Press Ctrl+C to stop monitoring (indexing will continue in background)${NC}"
echo ""

# Function to get job status
get_status() {
    python3 - <<STATEOF
import asyncio
import asyncpg

async def get_status():
    conn = await asyncpg.connect(dsn='postgresql://postgres:postgres@localhost:5433/robomonkey')
    try:
        # Get pending/claimed jobs
        jobs = await conn.fetch(
            """SELECT job_type, status, priority
               FROM robomonkey_control.job_queue
               WHERE repo_name = \$1 AND status IN ('PENDING', 'CLAIMED')
               ORDER BY priority DESC, created_at""",
            "$REPO_NAME"
        )

        if jobs:
            print("Active jobs:")
            for job in jobs:
                print(f"  - {job['job_type']}: {job['status']}")
        else:
            print("No active jobs (indexing may be complete or not started)")

        # Get repository stats
        schema_name = "robomonkey_${REPO_NAME//-/_}"
        await conn.execute(f'SET search_path TO "{schema_name}", public')

        stats = await conn.fetchrow(
            """SELECT
                (SELECT COUNT(*) FROM file) as files,
                (SELECT COUNT(*) FROM symbol) as symbols,
                (SELECT COUNT(*) FROM chunk) as chunks,
                (SELECT COUNT(*) FROM chunk_embedding) as chunk_embeddings,
                (SELECT COUNT(*) FROM document) as docs,
                (SELECT COUNT(*) FROM document_embedding) as doc_embeddings"""
        )

        if stats and stats['files'] > 0:
            print(f"\nRepository stats:")
            print(f"  Files: {stats['files']}")
            print(f"  Symbols: {stats['symbols']}")
            print(f"  Chunks: {stats['chunks']} ({stats['chunk_embeddings']} embedded)")
            print(f"  Docs: {stats['docs']} ({stats['doc_embeddings']} embedded)")

            if stats['chunks'] > 0:
                chunk_pct = (stats['chunk_embeddings'] / stats['chunks']) * 100
                print(f"  Chunk embedding progress: {chunk_pct:.1f}%")
            if stats['docs'] > 0:
                doc_pct = (stats['doc_embeddings'] / stats['docs']) * 100
                print(f"  Doc embedding progress: {doc_pct:.1f}%")

    finally:
        await conn.close()

asyncio.run(get_status())
STATEOF
}

# Monitor every 10 seconds
trap 'echo ""; echo -e "${YELLOW}Stopped monitoring. Daemon continues in background.${NC}"; exit 0' INT

while true; do
    clear
    echo -e "${BLUE}================================================${NC}"
    echo -e "${BLUE}  RoboMonkey Status - $REPO_NAME${NC}"
    echo -e "${BLUE}================================================${NC}"
    echo ""
    get_status
    echo ""
    echo -e "${YELLOW}Refreshing every 10 seconds... (Ctrl+C to stop monitoring)${NC}"
    sleep 10
done
