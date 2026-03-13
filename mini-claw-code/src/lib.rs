pub mod agent;
pub mod mock;
pub mod planning;
pub mod providers;
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
pub use mock::MockProvider;
pub use planning::{DEFAULT_PLAN_PROMPT_TEMPLATE, PlanAgent};
pub use providers::OpenRouterProvider;
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
