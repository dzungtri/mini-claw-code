use std::sync::Mutex;

use serde_json::json;
use tokio::sync::mpsc;

use crate::agent::{SimpleAgent, single_turn};
use crate::permissions::PermissionMode;
use crate::planning::PlanAgent;
use crate::streaming::{StreamEvent, StreamProvider, StreamingAgent};
use crate::subagent::SubagentTool;
use crate::types::*;

struct RichTool {
    definition: ToolDefinition,
}

impl RichTool {
    fn new() -> Self {
        Self {
            definition: ToolDefinition::new("rich", "Return a structured tool result.")
                .required_permission(PermissionMode::ReadOnly),
        }
    }
}

#[async_trait::async_trait]
impl Tool for RichTool {
    fn definition(&self) -> &ToolDefinition {
        &self.definition
    }

    async fn call(&self, _args: serde_json::Value) -> anyhow::Result<ToolOutput> {
        Ok(ToolOutput::rich(
            "rich text",
            json!({"ok": true, "source": "rich-tool"}),
        ))
    }
}

struct InspectingProvider {
    stage: Mutex<usize>,
}

impl InspectingProvider {
    fn new() -> Self {
        Self {
            stage: Mutex::new(0),
        }
    }

    fn rich_turn() -> AssistantTurn {
        AssistantTurn {
            text: None,
            tool_calls: vec![ToolCall {
                id: "call_rich".into(),
                name: "rich".into(),
                arguments: json!({}),
            }],
            stop_reason: StopReason::ToolUse,
        }
    }
}

impl Provider for InspectingProvider {
    async fn chat(
        &self,
        messages: &[Message],
        _tools: &[&ToolDefinition],
    ) -> anyhow::Result<AssistantTurn> {
        let mut stage = self.stage.lock().unwrap();
        let response = match *stage {
            0 => Self::rich_turn(),
            1 => {
                assert!(messages.iter().any(|message| matches!(
                    message,
                    Message::ToolResultStructured { id, content, structured }
                        if id == "call_rich"
                            && content == "rich text"
                            && structured["ok"] == json!(true)
                )));
                AssistantTurn {
                    text: Some("verified".into()),
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

struct InspectingStreamProvider {
    inner: InspectingProvider,
}

impl InspectingStreamProvider {
    fn new() -> Self {
        Self {
            inner: InspectingProvider::new(),
        }
    }
}

impl StreamProvider for InspectingStreamProvider {
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
fn test_ch14_tool_definition_supports_owned_metadata() {
    let dynamic_name = format!("mcp__{}__{}", "alpha", "echo");
    let dynamic_description = format!("Tool from {}", "alpha");
    let definition = ToolDefinition::new(dynamic_name.clone(), dynamic_description.clone());

    assert_eq!(definition.name, dynamic_name);
    assert_eq!(definition.description, dynamic_description);
}

#[test]
fn test_ch14_convert_messages_preserves_structured_tool_result_text() {
    let messages = vec![Message::ToolResultStructured {
        id: "call_rich".into(),
        content: "rich text".into(),
        structured: json!({"ok": true}),
    }];

    let converted = crate::providers::openrouter::OpenRouterProvider::convert_messages(&messages);
    assert_eq!(converted.len(), 1);
    assert_eq!(converted[0].role, "tool");
    assert_eq!(converted[0].content.as_deref(), Some("rich text"));
    assert_eq!(converted[0].tool_call_id.as_deref(), Some("call_rich"));
}

#[tokio::test]
async fn test_ch14_single_turn_uses_structured_tool_results() {
    let provider = InspectingProvider::new();
    let tools = ToolSet::new().with(RichTool::new());

    let result = single_turn(&provider, &tools, "run rich").await.unwrap();
    assert_eq!(result, "verified");
}

#[tokio::test]
async fn test_ch14_simple_agent_uses_structured_tool_results() {
    let provider = InspectingProvider::new();
    let agent = SimpleAgent::new(provider).tool(RichTool::new());
    let (tx, _rx) = mpsc::unbounded_channel();

    let messages = agent
        .run_with_history(vec![Message::User("run rich".into())], tx)
        .await;
    assert!(matches!(
        &messages[2],
        Message::ToolResultStructured { content, structured, .. }
            if content == "rich text" && structured["source"] == json!("rich-tool")
    ));
}

#[tokio::test]
async fn test_ch14_streaming_agent_uses_structured_tool_results() {
    let provider = InspectingStreamProvider::new();
    let agent = StreamingAgent::new(provider).tool(RichTool::new());
    let (tx, _rx) = mpsc::unbounded_channel();
    let mut messages = vec![Message::User("run rich".into())];

    let result = agent.chat(&mut messages, tx).await.unwrap();
    assert_eq!(result, "verified");
    assert!(messages.iter().any(|message| matches!(
        message,
        Message::ToolResultStructured { content, structured, .. }
            if content == "rich text" && structured["source"] == json!("rich-tool")
    )));
}

#[tokio::test]
async fn test_ch14_plan_execute_uses_structured_tool_results() {
    let provider = InspectingStreamProvider::new();
    let agent = PlanAgent::new(provider).tool(RichTool::new());
    let (tx, _rx) = mpsc::unbounded_channel();
    let mut messages = vec![Message::User("run rich".into())];

    let result = agent.execute(&mut messages, tx).await.unwrap();
    assert_eq!(result, "verified");
    assert!(messages.iter().any(|message| matches!(
        message,
        Message::ToolResultStructured { content, structured, .. }
            if content == "rich text" && structured["source"] == json!("rich-tool")
    )));
}

#[tokio::test]
async fn test_ch14_subagent_uses_structured_tool_results() {
    let provider = std::sync::Arc::new(InspectingProvider::new());
    let tool = SubagentTool::new(provider, || ToolSet::new().with(RichTool::new()));

    let result = tool.call(json!({"task": "run rich"})).await.unwrap();
    assert_eq!(result, "verified");
}
