# Chapter 8: The Singularity

Your agent can edit itself and it starts self-evolving. You don't need to write any code starting from now.

## Extensions

Everything from here is optional. Pick whichever interests you:

- **Streaming** -- Stream tokens as they arrive instead of waiting for the full response.
- **Parallel tool calls** -- Execute concurrent tool calls with `tokio::join!`.
- **System prompts** -- Prepend a system message for personality and constraints.
- **Token tracking** -- Truncate old messages when approaching the context limit.
- **Safety rails** -- Confirm before destructive operations like `rm -rf`.
- **More tools** -- Web search, database queries, HTTP requests. The `Tool` trait makes it easy.
- **A richer UI** -- Markdown rendering, spinners, collapsed tool calls. See `examples/tui.rs`.
- **MCP** -- Expose your tools as an MCP server or connect to external ones.
