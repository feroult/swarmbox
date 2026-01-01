# SwarmBox Agent Configuration

You are operating in **SwarmBox**, a sandboxed container environment for safe AI agent execution.

## Memory Operations

**Always delegate memory operations to the memory sub-agent.** Do not use memory MCP tools directly.

Examples:
- ❌ "Let me store that in memory..." → uses MCP directly
- ✅ "I'll use the memory sub-agent to store that..." → delegates properly

The memory sub-agent provides intelligent semantic retrieval and quality-focused storage.

## Container Environment

- Working directory: `/home/agent` (persistent across sessions via mounted volume)
- Memory databases: `~/.swarmbox/memory/` (SQLite with vector embeddings)
- MCP servers: chrome-devtools, memory (HTTP dashboard on :8889)

## Best Practices

- Use sub-agents for specialized tasks (memory, research, analysis)
- Check existing memories before creating new ones
- Prefer semantic search over exact matches
- Tag memories consistently for better retrieval
