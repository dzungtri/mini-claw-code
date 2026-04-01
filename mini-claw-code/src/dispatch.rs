use tokio::task_local;

use crate::permissions::PermissionPolicy;
use crate::types::*;

task_local! {
    static CURRENT_PERMISSION_POLICY: PermissionPolicy;
}

pub fn tool_error(error: impl Into<String>) -> ToolOutput {
    ToolOutput::text(error.into())
}

pub fn current_permission_policy() -> Option<PermissionPolicy> {
    CURRENT_PERMISSION_POLICY.try_with(Clone::clone).ok()
}

pub async fn execute_tool_call(
    tools: &ToolSet,
    call: &ToolCall,
    policy: Option<&PermissionPolicy>,
) -> (String, ToolOutput) {
    let output = match tools.get(&call.name) {
        Some(tool) => {
            if let Some(policy) = policy {
                match policy.authorize(
                    &call.name,
                    &call.arguments.to_string(),
                    None,
                    tool.definition().required_permission,
                ) {
                    crate::permissions::PermissionOutcome::Allow => CURRENT_PERMISSION_POLICY
                        .scope(policy.clone(), tool.call(call.arguments.clone()))
                        .await
                        .unwrap_or_else(|error| tool_error(format!("error: {error}"))),
                    crate::permissions::PermissionOutcome::Deny { reason } => tool_error(reason),
                }
            } else {
                tool.call(call.arguments.clone())
                    .await
                    .unwrap_or_else(|error| tool_error(format!("error: {error}")))
            }
        }
        None => tool_error(format!("error: unknown tool `{}`", call.name)),
    };
    (call.id.clone(), output)
}

pub async fn execute_tool_calls(
    tools: &ToolSet,
    calls: &[ToolCall],
    policy: Option<&PermissionPolicy>,
) -> Vec<(String, ToolOutput)> {
    let mut results = Vec::with_capacity(calls.len());
    for call in calls {
        results.push(execute_tool_call(tools, call, policy).await);
    }
    results
}

pub fn push_tool_results(
    messages: &mut Vec<Message>,
    turn: AssistantTurn,
    results: Vec<(String, ToolOutput)>,
) {
    messages.push(Message::Assistant(turn));
    for (id, output) in results {
        match output {
            ToolOutput::Text(content) => messages.push(Message::ToolResult { id, content }),
            ToolOutput::Rich {
                content,
                structured,
            } => messages.push(Message::ToolResultStructured {
                id,
                content,
                structured,
            }),
        }
    }
}
