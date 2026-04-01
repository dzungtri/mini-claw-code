use std::collections::HashSet;

use tokio::sync::mpsc;

use crate::agent::{AgentEvent, tool_summary};
use crate::dispatch::{execute_tool_calls, push_tool_results, tool_error};
use crate::permissions::{PermissionMode, PermissionPolicy};
use crate::streaming::{StreamEvent, StreamProvider};
use crate::types::*;

pub const DEFAULT_PLAN_PROMPT_TEMPLATE: &str = include_str!("../prompts/planning_prompt.md");

/// A two-phase agent that separates planning (read-only) from execution (all tools).
///
/// During the **plan** phase a system prompt is injected telling the LLM it is
/// in planning mode, and only read-only tools (plus `exit_plan`) are visible.
/// The LLM calls `exit_plan` when its plan is ready, or stops naturally.
/// During the **execute** phase all registered tools are available.
/// The caller drives the approval flow between the two phases.
pub struct PlanAgent<P: StreamProvider> {
    provider: P,
    tools: ToolSet,
    read_only: HashSet<String>,
    permission_policy: PermissionPolicy,
    plan_system_prompt: String,
    exit_plan_def: ToolDefinition,
}

impl<P: StreamProvider> PlanAgent<P> {
    /// Create a new `PlanAgent` with default read-only tools: `bash`, `read`, and `ask_user`.
    pub fn new(provider: P) -> Self {
        Self {
            provider,
            tools: ToolSet::new(),
            read_only: HashSet::from([String::from("read"), String::from("ask_user")]),
            permission_policy: PermissionPolicy::new(PermissionMode::DangerFullAccess),
            plan_system_prompt: DEFAULT_PLAN_PROMPT_TEMPLATE.to_string(),
            exit_plan_def: ToolDefinition::new(
                "exit_plan",
                "Signal that your plan is complete and ready for user review. \
                 Call this when you have finished exploring and are ready to present your plan.",
            )
            .required_permission(PermissionMode::ReadOnly),
        }
    }

    /// Register a tool (builder pattern, same as `SimpleAgent`).
    pub fn tool(mut self, t: impl Tool + 'static) -> Self {
        self.tools.push(t);
        self
    }

    /// Override the set of tool names allowed during the planning phase.
    pub fn read_only(mut self, names: &[&str]) -> Self {
        self.read_only = names.iter().map(|name| (*name).to_string()).collect();
        self
    }

    /// Override the system prompt injected at the start of the planning phase.
    pub fn plan_prompt(mut self, prompt: impl Into<String>) -> Self {
        self.plan_system_prompt = prompt.into();
        self
    }

    pub fn permission_mode(mut self, mode: PermissionMode) -> Self {
        self.permission_policy = PermissionPolicy::new(mode);
        self
    }

    pub fn permission_policy(mut self, policy: PermissionPolicy) -> Self {
        self.permission_policy = policy;
        self
    }

    /// Run the **planning** phase: only read-only tools (plus `exit_plan`) are visible.
    ///
    /// Injects a system prompt if one is not already present, telling the LLM
    /// it is in planning mode. Returns when the LLM either calls `exit_plan`
    /// or stops naturally.
    pub async fn plan(
        &self,
        messages: &mut Vec<Message>,
        events: mpsc::UnboundedSender<AgentEvent>,
    ) -> anyhow::Result<String> {
        if !messages
            .first()
            .is_some_and(|m| matches!(m, Message::System(_)))
        {
            messages.insert(0, Message::System(self.plan_system_prompt.clone()));
        }
        self.run_loop(messages, Some(&self.read_only), events).await
    }

    /// Run the **execution** phase: all registered tools are available.
    pub async fn execute(
        &self,
        messages: &mut Vec<Message>,
        events: mpsc::UnboundedSender<AgentEvent>,
    ) -> anyhow::Result<String> {
        self.run_loop(messages, None, events).await
    }

    /// Shared agent loop. When `allowed` is `Some`, only those tool names
    /// (plus `exit_plan`) are sent to the LLM and permitted for execution.
    async fn run_loop(
        &self,
        messages: &mut Vec<Message>,
        allowed: Option<&HashSet<String>>,
        events: mpsc::UnboundedSender<AgentEvent>,
    ) -> anyhow::Result<String> {
        let all_defs = self.tools.definitions();
        let defs: Vec<&ToolDefinition> = match allowed {
            Some(names) => {
                let mut filtered: Vec<&ToolDefinition> = all_defs
                    .into_iter()
                    .filter(|d| names.contains(d.name.as_str()))
                    .collect();
                filtered.push(&self.exit_plan_def);
                filtered
            }
            None => all_defs,
        };

        loop {
            // Set up stream channel and forward text deltas to the UI
            let (stream_tx, mut stream_rx) = mpsc::unbounded_channel();
            let events_clone = events.clone();
            let forwarder = tokio::spawn(async move {
                while let Some(event) = stream_rx.recv().await {
                    if let StreamEvent::TextDelta(text) = event {
                        let _ = events_clone.send(AgentEvent::TextDelta(text));
                    }
                }
            });

            let turn = match self.provider.stream_chat(messages, &defs, stream_tx).await {
                Ok(t) => t,
                Err(e) => {
                    let _ = events.send(AgentEvent::Error(e.to_string()));
                    return Err(e);
                }
            };
            let _ = forwarder.await;

            match turn.stop_reason {
                StopReason::Stop => {
                    let text = turn.text.clone().unwrap_or_default();
                    let _ = events.send(AgentEvent::Done(text.clone()));
                    messages.push(Message::Assistant(turn));
                    return Ok(text);
                }
                StopReason::ToolUse => {
                    let mut results = Vec::with_capacity(turn.tool_calls.len());
                    let mut exit_plan = false;
                    let mut executable_calls = Vec::new();

                    for call in &turn.tool_calls {
                        // Handle exit_plan: signal plan completion
                        if allowed.is_some() && call.name == "exit_plan" {
                            results
                                .push((call.id.clone(), tool_error("Plan submitted for review.")));
                            exit_plan = true;
                            continue;
                        }

                        // Execution guard: block tools not in the allowed set
                        if let Some(names) = allowed
                            && !names.contains(call.name.as_str())
                        {
                            results.push((
                                call.id.clone(),
                                tool_error(format!(
                                    "error: tool '{}' is not available in planning mode",
                                    call.name
                                )),
                            ));
                            continue;
                        }

                        let _ = events.send(AgentEvent::ToolCall {
                            name: call.name.clone(),
                            summary: tool_summary(call),
                        });
                        executable_calls.push(call.clone());
                    }
                    results.extend(
                        execute_tool_calls(
                            &self.tools,
                            &executable_calls,
                            Some(&self.permission_policy),
                        )
                        .await,
                    );

                    let plan_text = turn.text.clone().unwrap_or_default();
                    push_tool_results(messages, turn, results);

                    // If exit_plan was called, return the plan text to the caller
                    if exit_plan {
                        let _ = events.send(AgentEvent::Done(plan_text.clone()));
                        return Ok(plan_text);
                    }
                }
            }
        }
    }
}
