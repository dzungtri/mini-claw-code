pub mod agent;
pub mod dispatch;
pub mod mcp;
pub mod mcp_client;
pub mod mcp_stdio;
pub mod mock;
pub mod permissions;
pub mod planning;
pub mod providers;
pub mod sandbox;
pub mod streaming;
pub mod subagent;
pub mod tools;
pub mod types;

#[cfg(test)]
mod tests;

use std::fs;

pub const DEFAULT_SYSTEM_PROMPT_TEMPLATE: &str = include_str!("../prompts/prompt.md");
pub const SYSTEM_PROMPT_FILE_ENV: &str = "MINI_CLAW_SYSTEM_PROMPT_FILE";
pub const PLAN_PROMPT_FILE_ENV: &str = "MINI_CLAW_PLAN_PROMPT_FILE";

pub fn load_prompt_template(env_var: &str, default_template: &str) -> anyhow::Result<String> {
    match std::env::var(env_var) {
        Ok(path) if !path.trim().is_empty() => fs::read_to_string(&path)
            .map_err(|e| anyhow::anyhow!("failed to read prompt file from {env_var}={path}: {e}")),
        _ => Ok(default_template.to_string()),
    }
}

pub use agent::{AgentEvent, SimpleAgent, single_turn};
pub use mcp::{mcp_tool_name, mcp_tool_prefix, normalize_name_for_mcp};
pub use mcp_client::{McpClientBootstrap, McpClientTransport, McpStdioTransport};
pub use mcp_stdio::{
    JsonRpcError, JsonRpcId, JsonRpcRequest, JsonRpcResponse, ManagedMcpResource, ManagedMcpTool,
    McpInitializeClientInfo, McpInitializeParams, McpInitializeResult, McpInitializeServerInfo,
    McpListResourcesParams, McpListResourcesResult, McpListToolsParams, McpListToolsResult,
    McpReadResourceParams, McpReadResourceResult, McpResource, McpResourceContents,
    McpServerManager, McpServerManagerError, McpStdioProcess, McpTool, McpToolAdapter,
    McpToolCallContent, McpToolCallParams, McpToolCallResult,
};
pub use mock::MockProvider;
pub use permissions::{
    PermissionMode, PermissionOutcome, PermissionPolicy, PermissionPromptDecision,
    PermissionPrompter, PermissionRequest,
};
pub use planning::{DEFAULT_PLAN_PROMPT_TEMPLATE, PlanAgent};
pub use providers::{OpenRouterProvider, ProviderKind};
pub use sandbox::{
    FilesystemIsolationMode, LinuxSandboxCommand, SandboxConfig, SandboxRequest, SandboxStatus,
    build_linux_sandbox_command, resolve_sandbox_status_for_request,
};
pub use streaming::{
    MockStreamProvider, StreamAccumulator, StreamEvent, StreamProvider, StreamingAgent,
    parse_sse_line,
};
pub use subagent::SubagentTool;
pub use tools::{
    AskTool, BashTool, ChannelInputHandler, CliInputHandler, EditTool, InputHandler,
    MockInputHandler, ReadTool, UserInputRequest, WriteTool,
};
pub use types::*;
