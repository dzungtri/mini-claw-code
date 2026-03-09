use anyhow::Context;
use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::types::*;

// ---------------------------------------------------------------------------
// OpenAI-compatible request/response types (used by OpenRouter, OpenAI, etc.)
// ---------------------------------------------------------------------------

#[derive(Serialize)]
pub(crate) struct ChatRequest<'a> {
    pub(crate) model: &'a str,
    pub(crate) messages: Vec<ApiMessage>,
    #[serde(skip_serializing_if = "Vec::is_empty")]
    pub(crate) tools: Vec<ApiTool>,
    #[serde(skip_serializing_if = "std::ops::Not::not")]
    pub(crate) stream: bool,
}

#[derive(Serialize, Deserialize, Clone, Debug)]
pub(crate) struct ApiMessage {
    pub(crate) role: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub(crate) content: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub(crate) tool_calls: Option<Vec<ApiToolCall>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub(crate) tool_call_id: Option<String>,
}

#[derive(Serialize, Deserialize, Clone, Debug)]
pub(crate) struct ApiToolCall {
    pub(crate) id: String,
    #[serde(rename = "type")]
    pub(crate) type_: String,
    pub(crate) function: ApiFunction,
}

#[derive(Serialize, Deserialize, Clone, Debug)]
pub(crate) struct ApiFunction {
    pub(crate) name: String,
    pub(crate) arguments: String,
}

#[derive(Serialize, Debug)]
pub(crate) struct ApiTool {
    #[serde(rename = "type")]
    pub(crate) type_: &'static str,
    pub(crate) function: ApiToolDef,
}

#[derive(Serialize, Debug)]
pub(crate) struct ApiToolDef {
    pub(crate) name: &'static str,
    pub(crate) description: &'static str,
    pub(crate) parameters: Value,
}

#[derive(Deserialize)]
struct ChatResponse {
    choices: Vec<Choice>,
}

#[derive(Deserialize)]
struct Choice {
    message: ResponseMessage,
    finish_reason: Option<String>,
}

#[derive(Deserialize)]
struct ResponseMessage {
    content: Option<String>,
    tool_calls: Option<Vec<ApiToolCall>>,
}

// ---------------------------------------------------------------------------
// Provider
// ---------------------------------------------------------------------------

pub struct OpenRouterProvider {
    client: reqwest::Client,
    api_key: String,
    model: String,
    base_url: String,
}

impl OpenRouterProvider {
    const OPENROUTER_BASE_URL: &'static str = "https://openrouter.ai/api/v1";
    const OPENAI_BASE_URL: &'static str = "https://api.openai.com/v1";
    const DEFAULT_OPENROUTER_MODEL: &'static str = "openrouter/free";
    const DEFAULT_OPENAI_MODEL: &'static str = "gpt-4.1-mini";

    pub fn new(api_key: impl Into<String>, model: impl Into<String>) -> Self {
        Self {
            client: reqwest::Client::new(),
            api_key: api_key.into(),
            model: model.into(),
            base_url: Self::OPENROUTER_BASE_URL.into(),
        }
    }

    pub fn base_url(mut self, url: impl Into<String>) -> Self {
        self.base_url = url.into();
        self
    }

    fn read_non_empty_env(name: &str) -> Option<String> {
        std::env::var(name)
            .ok()
            .map(|v| v.trim().to_string())
            .filter(|v| !v.is_empty())
    }

    pub fn from_env_with_model(model: impl Into<String>) -> anyhow::Result<Self> {
        let _ = dotenvy::dotenv();
        let model = model.into();

        if let Some(api_key) = Self::read_non_empty_env("OPENROUTER_API_KEY") {
            return Ok(Self::new(api_key, model));
        }

        if let Some(api_key) = Self::read_non_empty_env("OPENAI_API_KEY") {
            return Ok(Self::new(api_key, model).base_url(Self::OPENAI_BASE_URL));
        }

        anyhow::bail!(
            "No API key found. Set OPENROUTER_API_KEY or OPENAI_API_KEY in environment or .env"
        )
    }

    pub fn from_env() -> anyhow::Result<Self> {
        let _ = dotenvy::dotenv();

        if let Some(api_key) = Self::read_non_empty_env("OPENROUTER_API_KEY") {
            let model = Self::read_non_empty_env("OPENROUTER_MODEL")
                .unwrap_or_else(|| Self::DEFAULT_OPENROUTER_MODEL.to_string());
            return Ok(Self::new(api_key, model));
        }

        if let Some(api_key) = Self::read_non_empty_env("OPENAI_API_KEY") {
            let model = Self::read_non_empty_env("OPENAI_MODEL")
                .unwrap_or_else(|| Self::DEFAULT_OPENAI_MODEL.to_string());
            return Ok(Self::new(api_key, model).base_url(Self::OPENAI_BASE_URL));
        }

        anyhow::bail!(
            "No API key found. Set OPENROUTER_API_KEY or OPENAI_API_KEY in environment or .env"
        )
    }

    pub(crate) fn convert_messages(messages: &[Message]) -> Vec<ApiMessage> {
        let mut out = Vec::new();
        for msg in messages {
            match msg {
                Message::System(text) => out.push(ApiMessage {
                    role: "system".into(),
                    content: Some(text.clone()),
                    tool_calls: None,
                    tool_call_id: None,
                }),
                Message::User(text) => out.push(ApiMessage {
                    role: "user".into(),
                    content: Some(text.clone()),
                    tool_calls: None,
                    tool_call_id: None,
                }),
                Message::Assistant(turn) => out.push(ApiMessage {
                    role: "assistant".into(),
                    content: turn.text.clone(),
                    tool_calls: if turn.tool_calls.is_empty() {
                        None
                    } else {
                        Some(
                            turn.tool_calls
                                .iter()
                                .map(|c| ApiToolCall {
                                    id: c.id.clone(),
                                    type_: "function".into(),
                                    function: ApiFunction {
                                        name: c.name.clone(),
                                        arguments: c.arguments.to_string(),
                                    },
                                })
                                .collect(),
                        )
                    },
                    tool_call_id: None,
                }),
                Message::ToolResult { id, content } => out.push(ApiMessage {
                    role: "tool".into(),
                    content: Some(content.clone()),
                    tool_calls: None,
                    tool_call_id: Some(id.clone()),
                }),
            }
        }
        out
    }

    pub(crate) fn convert_tools(tools: &[&ToolDefinition]) -> Vec<ApiTool> {
        tools
            .iter()
            .map(|t| ApiTool {
                type_: "function",
                function: ApiToolDef {
                    name: t.name,
                    description: t.description,
                    parameters: t.parameters.clone(),
                },
            })
            .collect()
    }
}

impl crate::streaming::StreamProvider for OpenRouterProvider {
    async fn stream_chat(
        &self,
        messages: &[Message],
        tools: &[&ToolDefinition],
        tx: tokio::sync::mpsc::UnboundedSender<crate::streaming::StreamEvent>,
    ) -> anyhow::Result<AssistantTurn> {
        use crate::streaming::{StreamAccumulator, parse_sse_line};

        let body = ChatRequest {
            model: &self.model,
            messages: Self::convert_messages(messages),
            tools: Self::convert_tools(tools),
            stream: true,
        };

        let mut resp = self
            .client
            .post(format!("{}/chat/completions", self.base_url))
            .bearer_auth(&self.api_key)
            .json(&body)
            .send()
            .await
            .context("request failed")?
            .error_for_status()
            .context("API returned error status")?;

        let mut acc = StreamAccumulator::new();
        let mut buffer = String::new();

        while let Some(chunk) = resp.chunk().await.context("failed to read chunk")? {
            buffer.push_str(&String::from_utf8_lossy(&chunk));

            while let Some(newline_pos) = buffer.find('\n') {
                let line = buffer[..newline_pos].trim_end_matches('\r').to_string();
                buffer = buffer[newline_pos + 1..].to_string();

                if line.is_empty() {
                    continue;
                }

                if let Some(events) = parse_sse_line(&line) {
                    for event in events {
                        acc.feed(&event);
                        let _ = tx.send(event);
                    }
                }
            }
        }

        Ok(acc.finish())
    }
}

impl Provider for OpenRouterProvider {
    async fn chat(
        &self,
        messages: &[Message],
        tools: &[&ToolDefinition],
    ) -> anyhow::Result<AssistantTurn> {
        let body = ChatRequest {
            model: &self.model,
            messages: Self::convert_messages(messages),
            tools: Self::convert_tools(tools),
            stream: false,
        };

        let resp: ChatResponse = self
            .client
            .post(format!("{}/chat/completions", self.base_url))
            .bearer_auth(&self.api_key)
            .json(&body)
            .send()
            .await
            .context("request failed")?
            .error_for_status()
            .context("API returned error status")?
            .json()
            .await
            .context("failed to parse response")?;

        let choice = resp.choices.into_iter().next().context("no choices")?;

        let tool_calls = choice
            .message
            .tool_calls
            .unwrap_or_default()
            .into_iter()
            .map(|tc| {
                let arguments = serde_json::from_str(&tc.function.arguments).unwrap_or(Value::Null);
                ToolCall {
                    id: tc.id,
                    name: tc.function.name,
                    arguments,
                }
            })
            .collect();

        let stop_reason = match choice.finish_reason.as_deref() {
            Some("tool_calls") => StopReason::ToolUse,
            _ => StopReason::Stop,
        };

        Ok(AssistantTurn {
            text: choice.message.content,
            tool_calls,
            stop_reason,
        })
    }
}
