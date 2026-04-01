use std::collections::HashMap;
use std::future::Future;
use std::sync::Arc;

use serde_json::Value;

use crate::permissions::PermissionMode;

#[derive(Debug, Clone, PartialEq)]
pub struct ToolDefinition {
    pub name: String,
    pub description: String,
    pub parameters: Value,
    pub required_permission: PermissionMode,
}

impl ToolDefinition {
    /// Create a new tool definition with no parameters.
    pub fn new(name: impl Into<String>, description: impl Into<String>) -> Self {
        Self {
            name: name.into(),
            description: description.into(),
            parameters: serde_json::json!({
                "type": "object",
                "properties": {},
                "required": []
            }),
            required_permission: PermissionMode::DangerFullAccess,
        }
    }

    /// Add a parameter to the tool definition.
    ///
    /// - `name`: parameter name (e.g. "path")
    /// - `type_`: JSON schema type (e.g. "string")
    /// - `description`: what this parameter is for
    /// - `required`: whether the parameter is required
    pub fn param(mut self, name: &str, type_: &str, description: &str, required: bool) -> Self {
        self.parameters["properties"][name] = serde_json::json!({
            "type": type_,
            "description": description
        });
        if required {
            self.parameters["required"]
                .as_array_mut()
                .unwrap()
                .push(serde_json::Value::String(name.to_string()));
        }
        self
    }

    /// Add a parameter with a raw JSON schema value.
    ///
    /// Use this for complex types (arrays, nested objects) that `param()` can't express.
    pub fn param_raw(mut self, name: &str, schema: Value, required: bool) -> Self {
        self.parameters["properties"][name] = schema;
        if required {
            self.parameters["required"]
                .as_array_mut()
                .unwrap()
                .push(serde_json::Value::String(name.to_string()));
        }
        self
    }

    pub fn required_permission(mut self, mode: PermissionMode) -> Self {
        self.required_permission = mode;
        self
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct ToolCall {
    pub id: String,
    pub name: String,
    pub arguments: Value,
}

/// Why the model stopped generating.
#[derive(Debug, Clone, PartialEq)]
pub enum StopReason {
    /// The model finished — check `text` for the response.
    Stop,
    /// The model wants to use tools — check `tool_calls`.
    ToolUse,
}

#[derive(Debug, Clone, PartialEq)]
pub struct AssistantTurn {
    pub text: Option<String>,
    pub tool_calls: Vec<ToolCall>,
    pub stop_reason: StopReason,
}

#[derive(Debug, Clone, PartialEq)]
pub enum ToolOutput {
    Text(String),
    Rich { content: String, structured: Value },
}

impl ToolOutput {
    pub fn text(content: impl Into<String>) -> Self {
        Self::Text(content.into())
    }

    pub fn rich(content: impl Into<String>, structured: Value) -> Self {
        Self::Rich {
            content: content.into(),
            structured,
        }
    }

    pub fn content(&self) -> &str {
        match self {
            Self::Text(content) | Self::Rich { content, .. } => content,
        }
    }

    pub fn structured(&self) -> Option<&Value> {
        match self {
            Self::Text(_) => None,
            Self::Rich { structured, .. } => Some(structured),
        }
    }

    pub fn contains(&self, needle: &str) -> bool {
        self.content().contains(needle)
    }

    pub fn len(&self) -> usize {
        self.content().len()
    }

    pub fn is_empty(&self) -> bool {
        self.content().is_empty()
    }
}

impl From<String> for ToolOutput {
    fn from(value: String) -> Self {
        Self::Text(value)
    }
}

impl From<&str> for ToolOutput {
    fn from(value: &str) -> Self {
        Self::Text(value.to_string())
    }
}

impl PartialEq<&str> for ToolOutput {
    fn eq(&self, other: &&str) -> bool {
        self.content() == *other
    }
}

impl PartialEq<ToolOutput> for &str {
    fn eq(&self, other: &ToolOutput) -> bool {
        *self == other.content()
    }
}

#[derive(Debug, Clone, PartialEq)]
pub enum Message {
    System(String),
    User(String),
    Assistant(AssistantTurn),
    ToolResult {
        id: String,
        content: String,
    },
    ToolResultStructured {
        id: String,
        content: String,
        structured: Value,
    },
}

/// The `Tool` trait uses `#[async_trait]` (instead of RPITIT like `Provider`)
/// because tools are stored as `Box<dyn Tool>` in `ToolSet`, which requires
/// object safety. RPITIT methods (`-> impl Future`) are not object-safe,
/// so `async_trait` desugars them into `-> Pin<Box<dyn Future>>` which is.
#[async_trait::async_trait]
pub trait Tool: Send + Sync {
    fn definition(&self) -> &ToolDefinition;
    async fn call(&self, args: Value) -> anyhow::Result<ToolOutput>;
}

/// A named collection of tools backed by a HashMap for O(1) lookup.
pub struct ToolSet {
    tools: HashMap<String, Box<dyn Tool>>,
}

impl ToolSet {
    pub fn new() -> Self {
        Self {
            tools: HashMap::new(),
        }
    }

    /// Add a tool (builder pattern).
    pub fn with(mut self, tool: impl Tool + 'static) -> Self {
        self.push(tool);
        self
    }

    /// Add a tool by mutable reference.
    pub fn push(&mut self, tool: impl Tool + 'static) {
        let name = tool.definition().name.to_string();
        self.tools.insert(name, Box::new(tool));
    }

    /// Look up a tool by name.
    pub fn get(&self, name: &str) -> Option<&dyn Tool> {
        self.tools.get(name).map(|t| t.as_ref())
    }

    /// Collect all tool definitions.
    pub fn definitions(&self) -> Vec<&ToolDefinition> {
        self.tools.values().map(|t| t.definition()).collect()
    }
}

impl Default for ToolSet {
    fn default() -> Self {
        Self::new()
    }
}

/// `Provider` uses RPITIT (return-position `impl Trait` in trait) because it
/// is always used as a generic parameter (`P: Provider`), never as `dyn Provider`.
/// This avoids the heap allocation that `#[async_trait]` requires.
pub trait Provider: Send + Sync {
    fn chat<'a>(
        &'a self,
        messages: &'a [Message],
        tools: &'a [&'a ToolDefinition],
    ) -> impl Future<Output = anyhow::Result<AssistantTurn>> + Send + 'a;
}

/// Blanket impl: `Arc<P>` is a `Provider` whenever `P` is.
///
/// This lets parent and child agents share the same provider via `Arc`
/// without cloning. Needed for subagents (Chapter 13).
impl<P: Provider> Provider for Arc<P> {
    fn chat<'a>(
        &'a self,
        messages: &'a [Message],
        tools: &'a [&'a ToolDefinition],
    ) -> impl Future<Output = anyhow::Result<AssistantTurn>> + Send + 'a {
        (**self).chat(messages, tools)
    }
}
