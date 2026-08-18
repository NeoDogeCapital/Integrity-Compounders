# Fiscal Account Tools

Read [the Fiscal MCP contract](mcp-workflow.md). Account-scoped helpers are live, consent-dependent tools for the
signed-in user's Fiscal data. Their exact names and schemas can change independently of this skill.

## Discover safely

1. Discover the session's consented `terminal_` helpers through `api_docs`. If the capability name is unknown, request
   the full catalog once; otherwise request all planned helper declarations together.
2. Use only the exact helper names and signatures returned by that catalog. Never infer a helper name, field, ID, or
   request body from a similar action.
3. Reuse IDs returned by list or lookup helpers. Resolve the exact target before any mutation.

## Read, write, and delete

- Read-only requests may combine up to six independent helpers in one invocation and should return a reduced result.
- Call a write helper only when the user explicitly asks to create or change the identified account object. Keep the
  mutation separate from public-company research and report the confirmed result.
- Call a delete helper only when the user explicitly asks to delete the exact resolved object. Do not broaden the
  target, infer an ID, or retry an ambiguous deletion.
- If the helper reports missing consent, tell the user which consent group and access level must be enabled by
  reconnecting the Fiscal.ai connector. Do not substitute a differently scoped tool.

## Output

For reads, return the requested account data and relevant object IDs. For writes or deletes, state the exact object
changed and the confirmed outcome. Never claim success from a planned call or from an empty response.
