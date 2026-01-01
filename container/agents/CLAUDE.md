# SwarmBox Agent Configuration

You are operating in **SwarmBox**, a sandboxed container environment for safe AI agent execution.

## Memory Operations - Smart Delegation

**Proactively recognize and delegate memory-related requests to the memory sub-agent.**

### When to Delegate (Pattern Recognition)

Delegate when the user's request involves:

**Storage patterns:**
- "remember", "store", "save", "keep", "note"
- "don't forget", "make a note", "track"
- "I want you to know", "for future reference"
- Context: Sharing information for later use

**Retrieval patterns:**
- "recall", "retrieve", "find", "search", "look up"
- "what did we", "how did we", "when did we"
- "do you remember", "did I tell you about"
- Context: Asking about past information

**Organization patterns:**
- "organize", "categorize", "tag", "cleanup"
- "update", "refine", "delete old"
- Context: Managing existing memories

### Smart Recognition Examples

**Implicit memory requests (recognize these):**
```
User: "We use connection pooling with max 20 connections"
→ Infer: User is sharing a pattern to remember
→ Action: Delegate to memory sub-agent to store

User: "How do we handle database migrations?"
→ Infer: User is asking about past decisions
→ Action: Delegate to memory sub-agent to retrieve

User: "Keep this in mind for next time"
→ Infer: User wants information stored
→ Action: Delegate to memory sub-agent
```

**Explicit memory requests (obvious):**
```
User: "Remember that my name is Fernando"
User: "Store this API key pattern"
User: "What did we decide about authentication?"
→ Always delegate to memory sub-agent
```

### How to Delegate

✅ **Correct:**
```
"I'll use the memory sub-agent to store that information..."
"Let me consult the memory sub-agent about our past approach..."
```

❌ **Incorrect:**
```
"Let me store that in memory..." → Don't use MCP directly
"I'll remember that..." → Don't store in conversation context only
```

### Key Principle

**Proactive, not reactive.** Recognize memory-related intent even when not explicitly stated. The memory sub-agent provides:
- Persistent semantic storage across sessions
- Intelligent RAG-based retrieval
- Quality-focused synthesis
