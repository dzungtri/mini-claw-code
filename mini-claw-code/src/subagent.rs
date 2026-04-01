use std::sync::Arc;

use serde_json::Value;

use crate::dispatch::current_permission_policy;
use crate::dispatch::{execute_tool_calls, push_tool_results};
use crate::permissions::{PermissionMode, PermissionPolicy};
use crate::types::*;

/// A tool that spawns a child agent to handle a subtask independently.
///
/// When the parent LLM calls this tool with a `task` description, it creates an
/// ephemeral child agent with its own message history and tools, runs it to
/// completion, and returns the result as tool output. The parent sees only the
/// final answer — the child's internal messages never leak into the parent's
/// conversation.
///
/// Provider sharing uses `Arc<P>` — the blanket `impl Provider for Arc<P>`
/// (in `types.rs`) makes this work without cloning the provider.
///
/// Tools are produced by a closure factory because `Box<dyn Tool>` is not
/// cloneable. Each child spawn gets a fresh `ToolSet`.
pub struct SubagentTool<P: Provider> {
    provider: Arc<P>,
    tools_factory: Box<dyn Fn() -> ToolSet + Send + Sync>,
    permission_policy: Option<PermissionPolicy>,
    system_prompt: Option<String>,
    max_turns: usize,
    definition: ToolDefinition,
}

impl<P: Provider> SubagentTool<P> {
    /// Create a new `SubagentTool` with a shared provider and a closure that
    /// produces a fresh `ToolSet` for each child spawn.
    pub fn new(
        provider: Arc<P>,
        tools_factory: impl Fn() -> ToolSet + Send + Sync + 'static,
    ) -> Self {
        Self {
            provider,
            tools_factory: Box::new(tools_factory),
            permission_policy: None,
            system_prompt: None,
            max_turns: 10,
            definition: ToolDefinition::new(
                "subagent",
                "Spawn a child agent to handle a subtask independently. \
                 The child has its own message history and tools.",
            )
            .required_permission(PermissionMode::WorkspaceWrite)
            .param(
                "task",
                "string",
                "A clear description of the subtask for the child agent to complete.",
                true,
            ),
        }
    }

    /// Set an optional system prompt for the child agent.
    pub fn system_prompt(mut self, prompt: impl Into<String>) -> Self {
        self.system_prompt = Some(prompt.into());
        self
    }

    /// Set the maximum number of agent loop turns before the child is stopped.
    /// Defaults to 10.
    pub fn max_turns(mut self, max: usize) -> Self {
        self.max_turns = max;
        self
    }

    /// Override the child agent's permission policy. If the parent has a more
    /// restrictive policy, that narrower policy wins.
    pub fn permission_policy(mut self, policy: PermissionPolicy) -> Self {
        self.permission_policy = Some(policy);
        self
    }
}

#[async_trait::async_trait]
impl<P: Provider + 'static> Tool for SubagentTool<P> {
    fn definition(&self) -> &ToolDefinition {
        &self.definition
    }

    async fn call(&self, args: Value) -> anyhow::Result<ToolOutput> {
        let task = args
            .get("task")
            .and_then(|v| v.as_str())
            .ok_or_else(|| anyhow::anyhow!("missing required parameter: task"))?;

        let tools = (self.tools_factory)();
        let defs = tools.definitions();
        let inherited_policy = current_permission_policy();
        let effective_policy = match (inherited_policy, self.permission_policy.clone()) {
            (Some(parent), Some(child)) if child.active_mode() > parent.active_mode() => parent,
            (Some(_), Some(child)) => child,
            (Some(parent), None) => parent,
            (None, Some(child)) => child,
            (None, None) => PermissionPolicy::new(PermissionMode::DangerFullAccess),
        };

        let mut messages = Vec::new();
        if let Some(ref prompt) = self.system_prompt {
            messages.push(Message::System(prompt.clone()));
        }
        messages.push(Message::User(task.to_string()));

        for _ in 0..self.max_turns {
            let turn = self.provider.chat(&messages, &defs).await?;

            match turn.stop_reason {
                StopReason::Stop => {
                    return Ok(ToolOutput::text(turn.text.unwrap_or_default()));
                }
                StopReason::ToolUse => {
                    let results =
                        execute_tool_calls(&tools, &turn.tool_calls, Some(&effective_policy)).await;
                    push_tool_results(&mut messages, turn, results);
                }
            }
        }

        Ok(ToolOutput::text("error: max turns exceeded".to_string()))
    }
}
