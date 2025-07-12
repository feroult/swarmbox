# Claude Flow Docker Environment

A Docker setup for running claude-flow CLI in an isolated, persistent environment.

## Features

- 🔒 Isolated environment for safe CLI execution
- 💾 Persistent authentication across container restarts and reboots
- 🛠️ Full Linux toolkit (ps, vim, nano, htop, tree, jq, etc.)
- 📁 Shared workspace directory between host and container
- 🔄 Long-lived container that survives exits

## Quick Start

### 1. Build the Docker Image

```bash
./build.sh
```

### 2. Start/Resume Container

```bash
./start.sh
# or
./resume.sh
```

Both commands will:
- Create a new container if none exists
- Connect to existing container if already running
- Show welcome message with setup instructions on first run

### 3. First Time Setup (Inside Container)

```bash
# 1. Authenticate with Claude (one-time setup)
claude --dangerously-skip-permissions

# 2. Follow the authentication link in your browser
# 3. Enter the verification code when prompted

# 4. Initialize Claude Flow
npx claude-flow@alpha init --force

# 5. Start using Claude Flow!
npx claude-flow@alpha --help
```

## Directory Structure

- `~/.claude-flow-docker/` - Persistent storage on host for:
  - `.claude/` - Claude authentication and configuration
  - `.npm/` - NPM cache
  - `.config/` - Application configs
- `./workspace/` - Shared workspace between host and container

## Common Commands

### Claude Flow Examples

```bash
# Interactive hive-mind wizard
npx claude-flow@alpha hive-mind wizard

# Build something with AI coordination
npx claude-flow@alpha hive-mind spawn "build me something amazing" --claude

# Explore capabilities
npx claude-flow@alpha --help
```

### Container Management

```bash
# Stop the container
docker stop claude-flow-session

# Remove the container (preserves data)
docker rm claude-flow-session

# View container logs
docker logs claude-flow-session

# Execute commands without entering container
docker exec claude-flow-session <command>
```

## Available Tools

The container includes a comprehensive Linux environment:

- **Editors**: vim, nano
- **System**: ps, htop, tree, file
- **Network**: ping, dig, nslookup, netstat, curl, wget
- **Development**: git, python3, pip, build-essential
- **Utilities**: jq, zip, tar, rsync, ssh client
- **And more**: bash-completion, man pages

## Troubleshooting

### Permission Issues
If you encounter permission errors, the container user has sudo access:
```bash
sudo chown -R claude-user:claude-user /home/claude-user/.claude
```

### Container Won't Start
```bash
# Check if container exists
docker ps -a | grep claude-flow

# Remove and recreate if needed
docker rm claude-flow-session
./start.sh
```

### Lost Authentication
Your authentication is stored in `~/.claude-flow-docker/.claude/` on the host. If lost, simply re-authenticate inside the container.

## Security Notes

- The container runs with a non-root user (`claude-user`) by default
- Sudo access is available without password for system tasks
- All data persists in your home directory (`~/.claude-flow-docker/`)
- The `--dangerously-skip-permissions` flag is required for Claude Code in containers

## License

This Docker setup is provided as-is for running claude-flow safely in isolation.