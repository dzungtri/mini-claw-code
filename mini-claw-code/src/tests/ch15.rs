use std::collections::VecDeque;
use std::sync::{Arc, Mutex};

use serde_json::json;
use tokio::sync::mpsc;

use crate::dispatch::execute_tool_calls;
use crate::permissions::{PermissionMode, PermissionPolicy};
use crate::planning::PlanAgent;
use crate::streaming::{MockStreamProvider, StreamEvent, StreamProvider, StreamingAgent};
use crate::subagent::SubagentTool;
use crate::tools::{BashTool, ReadTool, WriteTool};
use crate::types::*;

struct InspectDeniedBashProvider {
    stage: Mutex<usize>,
}

impl InspectDeniedBashProvider {
    fn new() -> Self {
        Self {
            stage: Mutex::new(0),
        }
    }
}

impl Provider for InspectDeniedBashProvider {
    async fn chat(
        &self,
        messages: &[Message],
        _tools: &[&ToolDefinition],
    ) -> anyhow::Result<AssistantTurn> {
        let mut stage = self.stage.lock().unwrap();
        let response = match *stage {
            0 => AssistantTurn {
                text: None,
                tool_calls: vec![ToolCall {
                    id: "call_bash".into(),
                    name: "bash".into(),
                    arguments: json!({"command": "echo hi"}),
                }],
                stop_reason: StopReason::ToolUse,
            },
            1 => {
                assert!(messages.iter().any(|message| matches!(
                    message,
                    Message::ToolResult { content, .. }
                        if content.contains("requires approval")
                            || content.contains("requires danger-full-access")
                )));
                AssistantTurn {
                    text: Some("child observed denial".into()),
                    tool_calls: vec![],
                    stop_reason: StopReason::Stop,
                }
            }
            _ => anyhow::bail!("unexpected extra call"),
        };
        *stage += 1;
        Ok(response)
    }
}

struct DeniedWriteStreamProvider {
    inner: crate::mock::MockProvider,
}

impl DeniedWriteStreamProvider {
    fn new() -> Self {
        Self {
            inner: crate::mock::MockProvider::new(VecDeque::from([
                AssistantTurn {
                    text: None,
                    tool_calls: vec![ToolCall {
                        id: "write_call".into(),
                        name: "write".into(),
                        arguments: json!({"path": "tmp.txt", "content": "hello"}),
                    }],
                    stop_reason: StopReason::ToolUse,
                },
                AssistantTurn {
                    text: Some("done".into()),
                    tool_calls: vec![],
                    stop_reason: StopReason::Stop,
                },
            ])),
        }
    }
}

impl StreamProvider for DeniedWriteStreamProvider {
    async fn stream_chat(
        &self,
        messages: &[Message],
        tools: &[&ToolDefinition],
        tx: mpsc::UnboundedSender<StreamEvent>,
    ) -> anyhow::Result<AssistantTurn> {
        let turn = self.inner.chat(messages, tools).await?;
        if let Some(ref text) = turn.text {
            for ch in text.chars() {
                let _ = tx.send(StreamEvent::TextDelta(ch.to_string()));
            }
        }
        for (index, call) in turn.tool_calls.iter().enumerate() {
            let _ = tx.send(StreamEvent::ToolCallStart {
                index,
                id: call.id.clone(),
                name: call.name.clone(),
            });
            let _ = tx.send(StreamEvent::ToolCallDelta {
                index,
                arguments: call.arguments.to_string(),
            });
        }
        let _ = tx.send(StreamEvent::Done);
        Ok(turn)
    }
}

#[test]
fn test_ch15_permission_policy_denies_write_in_read_only_mode() {
    let policy = PermissionPolicy::new(PermissionMode::ReadOnly);
    let result = policy.authorize(
        "write",
        "{\"path\":\"a.txt\"}",
        None,
        PermissionMode::WorkspaceWrite,
    );

    assert!(matches!(
        result,
        crate::PermissionOutcome::Deny { reason }
            if reason.contains("workspace-write")
    ));
}

#[test]
fn test_ch15_permission_policy_requires_approval_for_bash_from_workspace_write() {
    let policy = PermissionPolicy::new(PermissionMode::WorkspaceWrite);
    let result = policy.authorize(
        "bash",
        "{\"command\":\"echo hi\"}",
        None,
        PermissionMode::DangerFullAccess,
    );

    assert!(matches!(
        result,
        crate::PermissionOutcome::Deny { reason }
            if reason.contains("requires approval")
    ));
}

#[tokio::test]
async fn test_ch15_simple_agent_read_only_denies_write() {
    let provider = crate::mock::MockProvider::new(VecDeque::from([
        AssistantTurn {
            text: None,
            tool_calls: vec![ToolCall {
                id: "write_call".into(),
                name: "write".into(),
                arguments: json!({"path": "tmp.txt", "content": "hello"}),
            }],
            stop_reason: StopReason::ToolUse,
        },
        AssistantTurn {
            text: Some("done".into()),
            tool_calls: vec![],
            stop_reason: StopReason::Stop,
        },
    ]));
    let agent = crate::agent::SimpleAgent::new(provider)
        .tool(WriteTool::new())
        .permission_mode(PermissionMode::ReadOnly);
    let (tx, _rx) = mpsc::unbounded_channel();

    let messages = agent
        .run_with_history(vec![Message::User("write tmp.txt".into())], tx)
        .await;
    assert!(messages.iter().any(|message| matches!(
        message,
        Message::ToolResult { content, .. } if content.contains("workspace-write")
    )));
}

#[tokio::test]
async fn test_ch15_streaming_agent_read_only_denies_write() {
    let agent = StreamingAgent::new(DeniedWriteStreamProvider::new())
        .tool(WriteTool::new())
        .permission_mode(PermissionMode::ReadOnly);
    let (tx, _rx) = mpsc::unbounded_channel();
    let mut messages = vec![Message::User("write tmp.txt".into())];

    let _ = agent.chat(&mut messages, tx).await.unwrap();
    assert!(messages.iter().any(|message| matches!(
        message,
        Message::ToolResult { content, .. } if content.contains("workspace-write")
    )));
}

#[tokio::test]
async fn test_ch15_plan_default_read_only_excludes_bash() {
    let provider = MockStreamProvider::new(VecDeque::from([
        AssistantTurn {
            text: None,
            tool_calls: vec![ToolCall {
                id: "bash_call".into(),
                name: "bash".into(),
                arguments: json!({"command": "echo hi"}),
            }],
            stop_reason: StopReason::ToolUse,
        },
        AssistantTurn {
            text: Some("plan done".into()),
            tool_calls: vec![],
            stop_reason: StopReason::Stop,
        },
    ]));
    let agent = PlanAgent::new(provider)
        .tool(BashTool::new())
        .tool(ReadTool::new());
    let (tx, _rx) = mpsc::unbounded_channel();
    let mut messages = vec![Message::User("plan this".into())];

    let _ = agent.plan(&mut messages, tx).await.unwrap();
    assert!(messages.iter().any(|message| matches!(
        message,
        Message::ToolResult { content, .. }
            if content.contains("not available in planning mode")
    )));
}

#[tokio::test]
async fn test_ch15_subagent_inherits_parent_policy_and_cannot_widen() {
    let provider = Arc::new(InspectDeniedBashProvider::new());
    let subagent = SubagentTool::new(provider, || ToolSet::new().with(BashTool::new()))
        .permission_policy(PermissionPolicy::new(PermissionMode::DangerFullAccess));

    let mut tools = ToolSet::new();
    tools.push(subagent);

    let calls = vec![ToolCall {
        id: "sub_call".into(),
        name: "subagent".into(),
        arguments: json!({"task": "run bash"}),
    }];

    let results = execute_tool_calls(
        &tools,
        &calls,
        Some(&PermissionPolicy::new(PermissionMode::WorkspaceWrite)),
    )
    .await;

    assert_eq!(results.len(), 1);
    assert_eq!(results[0].1, ToolOutput::text("child observed denial"));
}

#[tokio::test]
async fn test_ch15_bash_timeout_returns_structured_output() {
    let tool = BashTool::new();
    let result = tool
        .call(json!({"command": "sleep 0.1", "timeout": 1}))
        .await
        .unwrap();

    assert!(result.contains("Command exceeded timeout"));
    assert_eq!(result.structured().unwrap()["interrupted"], json!(true));
}

#[tokio::test]
async fn test_ch15_bash_reports_sandbox_status() {
    let tool = BashTool::new();
    let result = tool
        .call(json!({
            "command": "printf hi",
            "filesystemMode": "workspace-only",
            "namespaceRestrictions": false,
            "isolateNetwork": false
        }))
        .await
        .unwrap();

    assert_eq!(result, "hi");
    assert_eq!(
        result.structured().unwrap()["sandboxStatus"]["filesystem_mode"],
        json!("workspace-only")
    );
}
