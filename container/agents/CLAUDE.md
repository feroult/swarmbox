# SwarmBox Agent Configuration

You are operating in **SwarmBox**, a sandboxed container environment for safe AI agent execution.

## Memory Operations

**Always delegate memory operations to the memory sub-agent.** Do not use memory MCP tools directly.

Examples:
- ❌ "Let me store that in memory..." → uses MCP directly
- ✅ "I'll use the memory sub-agent to store that..." → delegates properly

The memory sub-agent provides intelligent semantic retrieval and quality-focused storage.
