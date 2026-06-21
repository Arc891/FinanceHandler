#!/bin/bash
set -e

# Finance Automation Bot - Docker Deployment Script
# This script builds and deploys the Discord Finance Bot using the docker-build-push.sh utility

ADDITIONAL_FLAGS=""
FORCE_REBUILD=0

for arg in "$@"; do
  case $arg in
    --force-rebuild)
      FORCE_REBUILD=1
      ;;
    *)
      ADDITIONAL_FLAGS+=" $arg"
      ;;
  esac
done

# Resolve the invoking user's home even under sudo (HOME is /root otherwise),
# so we use the real ~/.scripts and not root's copy.
SCRIPT_HOME="${SUDO_USER:+/home/$SUDO_USER}"
SCRIPT_DIR="${SCRIPT_HOME:-$HOME}/.scripts"
DOCKER_SCRIPT="$SCRIPT_DIR/docker-build-push.sh"

# Check if docker-build-push.sh exists
if [[ ! -f "$DOCKER_SCRIPT" ]]; then
    echo "❌ Error: docker-build-push.sh not found at $DOCKER_SCRIPT"
    echo "Please ensure the script exists in your ~/.scripts directory"
    exit 1
fi

# Make sure we're in the project directory
cd "$(dirname "$0")"

echo "🚀 Deploying Finance Automation Bot..."
echo "📁 Project directory: $(pwd)"

# Check if required files exist
if [[ ! -f "Dockerfile" ]]; then
    echo "❌ Error: Dockerfile not found in current directory"
    exit 1
fi

if [[ ! -f "src/config/config_settings.py" ]]; then
    echo "❌ Error: src/config/config_settings.py not found"
    echo "Please ensure your Discord bot configuration is set up"
    exit 1
fi

if [[ ! -f "src/config/google_service_account.json" ]]; then
    echo "⚠️  Warning: Google service account not found at src/config/google_service_account.json"
    echo "Google Sheets integration will not work without this file"
fi

# Extract Discord token from local config for container
echo "🔑 Extracting Discord token from config..."
if [[ -f "src/config/config_settings.py" ]]; then
    # Try to get token from environment first, then from config file
    DISCORD_TOKEN_VALUE=$(python3 -c "
import sys
sys.path.append('src')
try:
    from config.config_settings import DISCORD_TOKEN
    if DISCORD_TOKEN and DISCORD_TOKEN != 'your_discord_token_here':
        print(DISCORD_TOKEN)
    else:
        print('')
except:
    print('')
" 2>/dev/null)

    if [[ -z "$DISCORD_TOKEN_VALUE" ]]; then
        echo "❌ Error: No valid Discord token found in config_settings.py"
        echo "Please ensure DISCORD_TOKEN is properly set in your config"
        exit 1
    fi
    echo "✅ Discord token found and will be passed to container"
else
    echo "❌ Error: config_settings.py not found"
    exit 1
fi

# Determine actual user's home (not root when using sudo)
ACTUAL_USER_HOME="${SUDO_USER:+/home/$SUDO_USER}"
ACTUAL_USER_HOME="${ACTUAL_USER_HOME:-$HOME}"

# Set up Docker run arguments for the bot
DOCKER_RUN_ARGS=(
    # Use the host network stack: the docker bridge cannot currently egress to
    # the internet on this host (Discord/Google/PyPI time out), but the host
    # network can. Bot's API still serves on host port 8383. The -p flags from
    # --port are ignored under host networking (harmless warning).
    --network=host

    # Mount volumes for persistent data
    -v "$(pwd)/data:/app/data"

    # Mount Claude Code CLI for AI categorization
    # Executable is read-only, config needs write access for logs/cache
    -v "$ACTUAL_USER_HOME/.local/bin/claude:/usr/local/bin/claude:ro"
    -v "$ACTUAL_USER_HOME/.claude:/home/appuser/.claude"

    # Set restart policy
    --restart "unless-stopped"

    # Add labels for easier management
    --label "project=finance-automation"
    --label "type=discord-bot"
)

echo "🔨 Building and deploying finance-automation-bot..."

# Clean up Docker cache if force rebuild is requested
if [[ $FORCE_REBUILD -eq 1 ]]; then
    echo "🧹 Force rebuild requested - cleaning Docker cache..."
    docker system prune -f --volumes || true
    docker builder prune -f || true
    # ADDITIONAL_FLAGS+=" --upgrade-minor"  # Force version bump
fi

# Run the docker build and push script
"$DOCKER_SCRIPT" \
    $ADDITIONAL_FLAGS \
    --image "finance-automation-bot" \
    --port "8383" \
    --registry "registry.arc8.dev" \
    --push-registry "localhost:5000" \
    --version-file "package.json" \
    --docker-run-args "${DOCKER_RUN_ARGS[@]}"

echo ""
echo "✅ Finance Automation Bot deployed successfully!"
echo ""
echo "📋 Management commands:"
echo "  View logs:    docker logs finance-automation-bot"
echo "  Stop bot:     docker stop finance-automation-bot"
echo "  Start bot:    docker start finance-automation-bot"
echo "  Restart bot:  docker restart finance-automation-bot"
echo ""
echo "� Troubleshooting:"
echo "  Force rebuild: ./run.sh --force-rebuild"
echo "  Test build:    ./run.sh --test"
echo ""
echo "�🔍 Bot status:"
docker ps --filter "name=finance-automation-bot" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
