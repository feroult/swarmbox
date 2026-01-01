# SwarmBox Agent Configuration

You are operating in **SwarmBox**, a sandboxed container environment for safe AI agent execution.

## Memory Operations

**Proactively delegate to memory sub-agent** when user intent relates to memory, even implicitly.

### Recognition Patterns

**Storage:** remember, store, save, keep, note, track, "for later", "don't forget"
**Retrieval:** recall, find, "what/how/when did we", "do you remember"
**Organization:** organize, categorize, update, cleanup, refine

### Context Inference

Recognize implicit intent:
- "We use X pattern" → Store for future reference
- "How do we handle Y?" → Retrieve past decisions
- "Keep this in mind" → Store information

### Delegation Format

✅ "I'll use the memory sub-agent to store/retrieve..."
❌ "Let me store in memory..." (don't use MCP directly)

**Principle:** Be proactive. Memory sub-agent provides persistent semantic storage with intelligent RAG-based retrieval across sessions.
