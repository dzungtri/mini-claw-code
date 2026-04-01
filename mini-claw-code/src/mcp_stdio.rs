use std::collections::BTreeMap;
use std::io;
use std::process::Stdio;
use std::sync::Arc;

use serde::de::DeserializeOwned;
use serde::{Deserialize, Serialize};
use serde_json::Value as JsonValue;
use tokio::io::{AsyncBufReadExt, AsyncReadExt, AsyncWriteExt, BufReader};
use tokio::process::{Child, ChildStdin, ChildStdout, Command};
use tokio::sync::Mutex;

use crate::mcp::mcp_tool_name;
use crate::mcp_client::{McpClientBootstrap, McpClientTransport, McpStdioTransport};
use crate::permissions::PermissionMode;
use crate::types::{Tool, ToolDefinition, ToolOutput};

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(untagged)]
pub enum JsonRpcId {
    Number(u64),
    String(String),
    Null,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct JsonRpcRequest<T = JsonValue> {
    pub jsonrpc: String,
    pub id: JsonRpcId,
    pub method: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub params: Option<T>,
}

impl<T> JsonRpcRequest<T> {
    pub fn new(id: JsonRpcId, method: impl Into<String>, params: Option<T>) -> Self {
        Self {
            jsonrpc: "2.0".to_string(),
            id,
            method: method.into(),
            params,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct JsonRpcError {
    pub code: i64,
    pub message: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub data: Option<JsonValue>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct JsonRpcResponse<T = JsonValue> {
    pub jsonrpc: String,
    pub id: JsonRpcId,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub result: Option<T>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<JsonRpcError>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct McpInitializeParams {
    pub protocol_version: String,
    pub capabilities: JsonValue,
    pub client_info: McpInitializeClientInfo,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct McpInitializeClientInfo {
    pub name: String,
    pub version: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct McpInitializeResult {
    pub protocol_version: String,
    pub capabilities: JsonValue,
    pub server_info: McpInitializeServerInfo,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct McpInitializeServerInfo {
    pub name: String,
    pub version: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct McpListToolsParams {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub cursor: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct McpTool {
    pub name: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub description: Option<String>,
    #[serde(rename = "inputSchema", skip_serializing_if = "Option::is_none")]
    pub input_schema: Option<JsonValue>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct McpListToolsResult {
    pub tools: Vec<McpTool>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub next_cursor: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct McpToolCallParams {
    pub name: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub arguments: Option<JsonValue>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct McpToolCallContent {
    #[serde(rename = "type")]
    pub kind: String,
    #[serde(flatten)]
    pub data: BTreeMap<String, JsonValue>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct McpToolCallResult {
    #[serde(default)]
    pub content: Vec<McpToolCallContent>,
    #[serde(default)]
    pub structured_content: Option<JsonValue>,
    #[serde(default)]
    pub is_error: Option<bool>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct McpListResourcesParams {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub cursor: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct McpResource {
    pub uri: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub name: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub description: Option<String>,
    #[serde(rename = "mimeType", skip_serializing_if = "Option::is_none")]
    pub mime_type: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct McpListResourcesResult {
    pub resources: Vec<McpResource>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub next_cursor: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct McpReadResourceParams {
    pub uri: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct McpResourceContents {
    pub uri: String,
    #[serde(rename = "mimeType", skip_serializing_if = "Option::is_none")]
    pub mime_type: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub text: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct McpReadResourceResult {
    pub contents: Vec<McpResourceContents>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct ManagedMcpTool {
    pub server_name: String,
    pub qualified_name: String,
    pub raw_name: String,
    pub tool: McpTool,
}

#[derive(Debug, Clone, PartialEq)]
pub struct ManagedMcpResource {
    pub server_name: String,
    pub resource: McpResource,
}

#[derive(Debug)]
pub enum McpServerManagerError {
    Io(io::Error),
    JsonRpc {
        server_name: String,
        method: &'static str,
        error: JsonRpcError,
    },
    InvalidResponse {
        server_name: String,
        method: &'static str,
        details: String,
    },
    UnknownTool {
        qualified_name: String,
    },
    UnknownServer {
        server_name: String,
    },
}

impl std::fmt::Display for McpServerManagerError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Io(error) => write!(f, "{error}"),
            Self::JsonRpc {
                server_name,
                method,
                error,
            } => write!(
                f,
                "MCP server `{server_name}` returned JSON-RPC error for {method}: {} ({})",
                error.message, error.code
            ),
            Self::InvalidResponse {
                server_name,
                method,
                details,
            } => write!(
                f,
                "MCP server `{server_name}` returned invalid response for {method}: {details}"
            ),
            Self::UnknownTool { qualified_name } => {
                write!(f, "unknown MCP tool `{qualified_name}`")
            }
            Self::UnknownServer { server_name } => write!(f, "unknown MCP server `{server_name}`"),
        }
    }
}

impl std::error::Error for McpServerManagerError {}

impl From<io::Error> for McpServerManagerError {
    fn from(value: io::Error) -> Self {
        Self::Io(value)
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct ToolRoute {
    server_name: String,
    raw_name: String,
}

#[derive(Debug)]
struct ManagedMcpServer {
    bootstrap: McpClientBootstrap,
    process: Option<McpStdioProcess>,
    initialized: bool,
}

impl ManagedMcpServer {
    fn new(bootstrap: McpClientBootstrap) -> Self {
        Self {
            bootstrap,
            process: None,
            initialized: false,
        }
    }
}

#[derive(Debug)]
pub struct McpServerManager {
    servers: BTreeMap<String, ManagedMcpServer>,
    tool_index: BTreeMap<String, ToolRoute>,
    next_request_id: u64,
}

impl McpServerManager {
    pub fn from_bootstraps(bootstraps: impl IntoIterator<Item = McpClientBootstrap>) -> Self {
        let mut servers = BTreeMap::new();
        for bootstrap in bootstraps {
            servers.insert(
                bootstrap.server_name.clone(),
                ManagedMcpServer::new(bootstrap),
            );
        }
        Self {
            servers,
            tool_index: BTreeMap::new(),
            next_request_id: 1,
        }
    }

    pub async fn discover_tools(&mut self) -> Result<Vec<ManagedMcpTool>, McpServerManagerError> {
        let server_names = self.servers.keys().cloned().collect::<Vec<_>>();
        let mut discovered = Vec::new();
        for server_name in server_names {
            self.ensure_server_ready(&server_name).await?;
            self.clear_routes_for_server(&server_name);

            let request_id = self.take_request_id();
            let response = {
                let server = self.server_mut(&server_name)?;
                let process = server.process.as_mut().ok_or_else(|| {
                    McpServerManagerError::InvalidResponse {
                        server_name: server_name.clone(),
                        method: "tools/list",
                        details: "server process missing after initialization".into(),
                    }
                })?;
                process
                    .list_tools(request_id, Some(McpListToolsParams { cursor: None }))
                    .await?
            };

            if let Some(error) = response.error {
                return Err(McpServerManagerError::JsonRpc {
                    server_name: server_name.clone(),
                    method: "tools/list",
                    error,
                });
            }
            let result = response
                .result
                .ok_or_else(|| McpServerManagerError::InvalidResponse {
                    server_name: server_name.clone(),
                    method: "tools/list",
                    details: "missing result payload".into(),
                })?;

            for tool in result.tools {
                let qualified_name = mcp_tool_name(&server_name, &tool.name);
                self.tool_index.insert(
                    qualified_name.clone(),
                    ToolRoute {
                        server_name: server_name.clone(),
                        raw_name: tool.name.clone(),
                    },
                );
                discovered.push(ManagedMcpTool {
                    server_name: server_name.clone(),
                    qualified_name,
                    raw_name: tool.name.clone(),
                    tool,
                });
            }
        }
        Ok(discovered)
    }

    pub async fn list_resources(
        &mut self,
        server_name: &str,
    ) -> Result<Vec<ManagedMcpResource>, McpServerManagerError> {
        self.ensure_server_ready(server_name).await?;
        let request_id = self.take_request_id();
        let response =
            {
                let server = self.server_mut(server_name)?;
                let process = server.process.as_mut().ok_or_else(|| {
                    McpServerManagerError::InvalidResponse {
                        server_name: server_name.to_string(),
                        method: "resources/list",
                        details: "server process missing after initialization".into(),
                    }
                })?;
                process
                    .list_resources(request_id, Some(McpListResourcesParams { cursor: None }))
                    .await?
            };

        if let Some(error) = response.error {
            return Err(McpServerManagerError::JsonRpc {
                server_name: server_name.to_string(),
                method: "resources/list",
                error,
            });
        }
        let result = response
            .result
            .ok_or_else(|| McpServerManagerError::InvalidResponse {
                server_name: server_name.to_string(),
                method: "resources/list",
                details: "missing result payload".into(),
            })?;
        Ok(result
            .resources
            .into_iter()
            .map(|resource| ManagedMcpResource {
                server_name: server_name.to_string(),
                resource,
            })
            .collect())
    }

    pub async fn read_resource(
        &mut self,
        server_name: &str,
        uri: &str,
    ) -> Result<McpReadResourceResult, McpServerManagerError> {
        self.ensure_server_ready(server_name).await?;
        let request_id = self.take_request_id();
        let response =
            {
                let server = self.server_mut(server_name)?;
                let process = server.process.as_mut().ok_or_else(|| {
                    McpServerManagerError::InvalidResponse {
                        server_name: server_name.to_string(),
                        method: "resources/read",
                        details: "server process missing after initialization".into(),
                    }
                })?;
                process
                    .read_resource(
                        request_id,
                        McpReadResourceParams {
                            uri: uri.to_string(),
                        },
                    )
                    .await?
            };

        if let Some(error) = response.error {
            return Err(McpServerManagerError::JsonRpc {
                server_name: server_name.to_string(),
                method: "resources/read",
                error,
            });
        }
        response
            .result
            .ok_or_else(|| McpServerManagerError::InvalidResponse {
                server_name: server_name.to_string(),
                method: "resources/read",
                details: "missing result payload".into(),
            })
    }

    pub async fn call_tool(
        &mut self,
        qualified_tool_name: &str,
        arguments: Option<JsonValue>,
    ) -> Result<McpToolCallResult, McpServerManagerError> {
        let route = self
            .tool_index
            .get(qualified_tool_name)
            .cloned()
            .ok_or_else(|| McpServerManagerError::UnknownTool {
                qualified_name: qualified_tool_name.to_string(),
            })?;
        self.ensure_server_ready(&route.server_name).await?;
        let request_id = self.take_request_id();
        let response =
            {
                let server = self.server_mut(&route.server_name)?;
                let process = server.process.as_mut().ok_or_else(|| {
                    McpServerManagerError::InvalidResponse {
                        server_name: route.server_name.clone(),
                        method: "tools/call",
                        details: "server process missing after initialization".into(),
                    }
                })?;
                process
                    .call_tool(
                        request_id,
                        McpToolCallParams {
                            name: route.raw_name,
                            arguments,
                        },
                    )
                    .await?
            };

        if let Some(error) = response.error {
            return Err(McpServerManagerError::JsonRpc {
                server_name: route.server_name.clone(),
                method: "tools/call",
                error,
            });
        }
        response
            .result
            .ok_or_else(|| McpServerManagerError::InvalidResponse {
                server_name: route.server_name,
                method: "tools/call",
                details: "missing result payload".into(),
            })
    }

    pub async fn shutdown(&mut self) -> Result<(), McpServerManagerError> {
        let server_names = self.servers.keys().cloned().collect::<Vec<_>>();
        for server_name in server_names {
            let server = self.server_mut(&server_name)?;
            if let Some(process) = server.process.as_mut() {
                process.shutdown().await?;
            }
            server.process = None;
            server.initialized = false;
        }
        Ok(())
    }

    fn clear_routes_for_server(&mut self, server_name: &str) {
        self.tool_index
            .retain(|_, route| route.server_name != server_name);
    }

    fn server_mut(
        &mut self,
        server_name: &str,
    ) -> Result<&mut ManagedMcpServer, McpServerManagerError> {
        self.servers
            .get_mut(server_name)
            .ok_or_else(|| McpServerManagerError::UnknownServer {
                server_name: server_name.to_string(),
            })
    }

    fn take_request_id(&mut self) -> JsonRpcId {
        let id = self.next_request_id;
        self.next_request_id = self.next_request_id.saturating_add(1);
        JsonRpcId::Number(id)
    }

    async fn ensure_server_ready(
        &mut self,
        server_name: &str,
    ) -> Result<(), McpServerManagerError> {
        let needs_spawn = self
            .servers
            .get(server_name)
            .map(|server| server.process.is_none())
            .ok_or_else(|| McpServerManagerError::UnknownServer {
                server_name: server_name.to_string(),
            })?;

        if needs_spawn {
            let server = self.server_mut(server_name)?;
            server.process = Some(spawn_mcp_stdio_process(&server.bootstrap)?);
            server.initialized = false;
        }

        let needs_initialize = self
            .servers
            .get(server_name)
            .map(|server| !server.initialized)
            .ok_or_else(|| McpServerManagerError::UnknownServer {
                server_name: server_name.to_string(),
            })?;

        if needs_initialize {
            let request_id = self.take_request_id();
            let response = {
                let server = self.server_mut(server_name)?;
                let process = server.process.as_mut().ok_or_else(|| {
                    McpServerManagerError::InvalidResponse {
                        server_name: server_name.to_string(),
                        method: "initialize",
                        details: "server process missing before initialize".into(),
                    }
                })?;
                process
                    .initialize(request_id, default_initialize_params())
                    .await?
            };

            if let Some(error) = response.error {
                return Err(McpServerManagerError::JsonRpc {
                    server_name: server_name.to_string(),
                    method: "initialize",
                    error,
                });
            }
            if response.result.is_none() {
                return Err(McpServerManagerError::InvalidResponse {
                    server_name: server_name.to_string(),
                    method: "initialize",
                    details: "missing result payload".into(),
                });
            }
            let server = self.server_mut(server_name)?;
            server.initialized = true;
        }

        Ok(())
    }
}

#[derive(Debug)]
pub struct McpStdioProcess {
    child: Child,
    stdin: ChildStdin,
    stdout: BufReader<ChildStdout>,
}

impl McpStdioProcess {
    pub fn spawn(transport: &McpStdioTransport) -> io::Result<Self> {
        let mut command = Command::new(&transport.command);
        command
            .args(&transport.args)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit());
        apply_env(&mut command, &transport.env);

        let mut child = command.spawn()?;
        let stdin = child
            .stdin
            .take()
            .ok_or_else(|| io::Error::other("stdio MCP process missing stdin pipe"))?;
        let stdout = child
            .stdout
            .take()
            .ok_or_else(|| io::Error::other("stdio MCP process missing stdout pipe"))?;
        Ok(Self {
            child,
            stdin,
            stdout: BufReader::new(stdout),
        })
    }

    async fn write_frame(&mut self, payload: &[u8]) -> io::Result<()> {
        let header = format!("Content-Length: {}\r\n\r\n", payload.len());
        self.stdin.write_all(header.as_bytes()).await?;
        self.stdin.write_all(payload).await?;
        self.stdin.flush().await
    }

    async fn read_frame(&mut self) -> io::Result<Vec<u8>> {
        let mut content_length = None;
        loop {
            let mut line = String::new();
            let bytes_read = self.stdout.read_line(&mut line).await?;
            if bytes_read == 0 {
                return Err(io::Error::new(
                    io::ErrorKind::UnexpectedEof,
                    "MCP stdio stream closed while reading headers",
                ));
            }
            if line == "\r\n" {
                break;
            }
            if let Some(value) = line.strip_prefix("Content-Length:") {
                content_length = Some(
                    value
                        .trim()
                        .parse::<usize>()
                        .map_err(|error| io::Error::new(io::ErrorKind::InvalidData, error))?,
                );
            }
        }

        let content_length = content_length.ok_or_else(|| {
            io::Error::new(io::ErrorKind::InvalidData, "missing Content-Length header")
        })?;
        let mut payload = vec![0_u8; content_length];
        self.stdout.read_exact(&mut payload).await?;
        Ok(payload)
    }

    async fn request<TParams: Serialize, TResult: DeserializeOwned>(
        &mut self,
        id: JsonRpcId,
        method: impl Into<String>,
        params: Option<TParams>,
    ) -> io::Result<JsonRpcResponse<TResult>> {
        let request = JsonRpcRequest::new(id, method, params);
        let body = serde_json::to_vec(&request)
            .map_err(|error| io::Error::new(io::ErrorKind::InvalidData, error))?;
        self.write_frame(&body).await?;
        let payload = self.read_frame().await?;
        serde_json::from_slice(&payload)
            .map_err(|error| io::Error::new(io::ErrorKind::InvalidData, error))
    }

    pub async fn initialize(
        &mut self,
        id: JsonRpcId,
        params: McpInitializeParams,
    ) -> io::Result<JsonRpcResponse<McpInitializeResult>> {
        self.request(id, "initialize", Some(params)).await
    }

    pub async fn list_tools(
        &mut self,
        id: JsonRpcId,
        params: Option<McpListToolsParams>,
    ) -> io::Result<JsonRpcResponse<McpListToolsResult>> {
        self.request(id, "tools/list", params).await
    }

    pub async fn call_tool(
        &mut self,
        id: JsonRpcId,
        params: McpToolCallParams,
    ) -> io::Result<JsonRpcResponse<McpToolCallResult>> {
        self.request(id, "tools/call", Some(params)).await
    }

    pub async fn list_resources(
        &mut self,
        id: JsonRpcId,
        params: Option<McpListResourcesParams>,
    ) -> io::Result<JsonRpcResponse<McpListResourcesResult>> {
        self.request(id, "resources/list", params).await
    }

    pub async fn read_resource(
        &mut self,
        id: JsonRpcId,
        params: McpReadResourceParams,
    ) -> io::Result<JsonRpcResponse<McpReadResourceResult>> {
        self.request(id, "resources/read", Some(params)).await
    }

    async fn shutdown(&mut self) -> io::Result<()> {
        if self.child.try_wait()?.is_none() {
            self.child.kill().await?;
        }
        let _ = self.child.wait().await?;
        Ok(())
    }
}

pub fn spawn_mcp_stdio_process(bootstrap: &McpClientBootstrap) -> io::Result<McpStdioProcess> {
    match &bootstrap.transport {
        McpClientTransport::Stdio(transport) => McpStdioProcess::spawn(transport),
    }
}

fn apply_env(command: &mut Command, env: &BTreeMap<String, String>) {
    for (key, value) in env {
        command.env(key, value);
    }
}

fn default_initialize_params() -> McpInitializeParams {
    McpInitializeParams {
        protocol_version: "2025-03-26".to_string(),
        capabilities: JsonValue::Object(serde_json::Map::new()),
        client_info: McpInitializeClientInfo {
            name: "mini-claw-code".to_string(),
            version: env!("CARGO_PKG_VERSION").to_string(),
        },
    }
}

fn extract_tool_output(result: &McpToolCallResult) -> ToolOutput {
    let mut texts = Vec::new();
    for item in &result.content {
        if item.kind == "text"
            && let Some(JsonValue::String(text)) = item.data.get("text")
        {
            texts.push(text.clone());
        }
    }
    let content = if texts.is_empty() {
        result
            .structured_content
            .clone()
            .map(|value| value.to_string())
            .unwrap_or_default()
    } else {
        texts.join("\n")
    };
    let structured = result
        .structured_content
        .clone()
        .unwrap_or_else(|| serde_json::to_value(result).unwrap_or(JsonValue::Null));
    ToolOutput::rich(content, structured)
}

pub struct McpToolAdapter {
    manager: Arc<Mutex<McpServerManager>>,
    definition: ToolDefinition,
    qualified_name: String,
}

impl McpToolAdapter {
    pub fn from_managed_tool(manager: Arc<Mutex<McpServerManager>>, tool: ManagedMcpTool) -> Self {
        let description = tool
            .tool
            .description
            .clone()
            .unwrap_or_else(|| format!("MCP tool `{}`", tool.raw_name));
        let parameters = tool
            .tool
            .input_schema
            .clone()
            .unwrap_or_else(|| serde_json::json!({"type": "object"}));
        Self {
            definition: ToolDefinition {
                name: tool.qualified_name.clone(),
                description,
                parameters,
                required_permission: PermissionMode::DangerFullAccess,
            },
            qualified_name: tool.qualified_name,
            manager,
        }
    }
}

#[async_trait::async_trait]
impl Tool for McpToolAdapter {
    fn definition(&self) -> &ToolDefinition {
        &self.definition
    }

    async fn call(&self, args: JsonValue) -> anyhow::Result<ToolOutput> {
        let mut manager = self.manager.lock().await;
        let result = manager
            .call_tool(&self.qualified_name, Some(args))
            .await
            .map_err(|error| anyhow::anyhow!("{error}"))?;
        Ok(extract_tool_output(&result))
    }
}

#[cfg(test)]
mod tests {
    use std::collections::BTreeMap;
    use std::fs;
    use std::os::unix::fs::PermissionsExt;
    use std::path::PathBuf;
    use std::sync::Arc;
    use std::time::{SystemTime, UNIX_EPOCH};

    use serde_json::json;
    use tokio::sync::Mutex;

    use crate::agent::SimpleAgent;

    use super::{McpClientBootstrap, McpServerManager, McpToolAdapter};

    fn temp_dir() -> PathBuf {
        let nanos = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("time should be after epoch")
            .as_nanos();
        std::env::temp_dir().join(format!("mini-claw-mcp-{nanos}"))
    }

    fn write_jsonrpc_script() -> PathBuf {
        let root = temp_dir();
        fs::create_dir_all(&root).expect("temp dir");
        let script_path = root.join("jsonrpc-mcp.py");
        let script = [
            "#!/usr/bin/env python3",
            "import json, sys",
            "",
            "def read_frame():",
            "    content_length = None",
            "    while True:",
            "        line = sys.stdin.buffer.readline()",
            "        if not line:",
            "            raise SystemExit(0)",
            "        if line == b'\\r\\n':",
            "            break",
            "        if line.lower().startswith(b'content-length:'):",
            "            content_length = int(line.split(b':', 1)[1].strip())",
            "    body = sys.stdin.buffer.read(content_length)",
            "    return json.loads(body.decode())",
            "",
            "def write_frame(payload):",
            "    body = json.dumps(payload).encode()",
            "    sys.stdout.buffer.write(f'Content-Length: {len(body)}\\r\\n\\r\\n'.encode())",
            "    sys.stdout.buffer.write(body)",
            "    sys.stdout.buffer.flush()",
            "",
            "while True:",
            "    req = read_frame()",
            "    method = req['method']",
            "    if method == 'initialize':",
            "        write_frame({",
            "            'jsonrpc': '2.0',",
            "            'id': req['id'],",
            "            'result': {",
            "                'protocolVersion': '2025-03-26',",
            "                'capabilities': {},",
            "                'serverInfo': {'name': 'test-server', 'version': '1.0.0'}",
            "            }",
            "        })",
            "    elif method == 'tools/list':",
            "        write_frame({",
            "            'jsonrpc': '2.0',",
            "            'id': req['id'],",
            "            'result': {",
            "                'tools': [",
            "                    {'name': 'echo', 'description': 'Echo text', 'inputSchema': {'type': 'object'}}",
            "                ]",
            "            }",
            "        })",
            "    elif method == 'tools/call':",
            "        text = req.get('params', {}).get('arguments', {}).get('text', 'missing')",
            "        write_frame({",
            "            'jsonrpc': '2.0',",
            "            'id': req['id'],",
            "            'result': {",
            "                'content': [{'type': 'text', 'text': f'ECHO:{text}'}],",
            "                'structuredContent': {'echoed': text}",
            "            }",
            "        })",
            "    elif method == 'resources/list':",
            "        write_frame({",
            "            'jsonrpc': '2.0',",
            "            'id': req['id'],",
            "            'result': {",
            "                'resources': [",
            "                    {'uri': 'resource://guide', 'name': 'Guide', 'mimeType': 'text/plain'}",
            "                ]",
            "            }",
            "        })",
            "    elif method == 'resources/read':",
            "        write_frame({",
            "            'jsonrpc': '2.0',",
            "            'id': req['id'],",
            "            'result': {",
            "                'contents': [",
            "                    {'uri': 'resource://guide', 'mimeType': 'text/plain', 'text': 'resource text'}",
            "                ]",
            "            }",
            "        })",
            "    else:",
            "        write_frame({'jsonrpc': '2.0', 'id': req['id'], 'error': {'code': -32601, 'message': 'unknown method'}})",
        ]
        .join("\n");
        fs::write(&script_path, script).expect("write script");
        let mut permissions = fs::metadata(&script_path).expect("metadata").permissions();
        permissions.set_mode(0o755);
        fs::set_permissions(&script_path, permissions).expect("chmod");
        script_path
    }

    #[tokio::test]
    async fn discovers_tools_and_resources_and_calls_tool() {
        let script = write_jsonrpc_script();
        let bootstrap = McpClientBootstrap::stdio(
            "alpha",
            script.display().to_string(),
            vec![],
            BTreeMap::new(),
        );
        let mut manager = McpServerManager::from_bootstraps([bootstrap]);

        let tools = manager.discover_tools().await.expect("discover tools");
        assert_eq!(tools.len(), 1);
        assert_eq!(tools[0].qualified_name, "mcp__alpha__echo");

        let resources = manager.list_resources("alpha").await.expect("resources");
        assert_eq!(resources.len(), 1);
        assert_eq!(resources[0].resource.uri, "resource://guide");

        let resource = manager
            .read_resource("alpha", "resource://guide")
            .await
            .expect("read resource");
        assert_eq!(resource.contents[0].text.as_deref(), Some("resource text"));

        let result = manager
            .call_tool("mcp__alpha__echo", Some(json!({"text": "hello"})))
            .await
            .expect("call tool");
        assert_eq!(result.structured_content, Some(json!({"echoed": "hello"})));
        assert_eq!(
            result.content[0].data.get("text"),
            Some(&json!("ECHO:hello"))
        );
    }

    #[tokio::test]
    async fn adapter_integrates_with_simple_agent() {
        let script = write_jsonrpc_script();
        let bootstrap = McpClientBootstrap::stdio(
            "alpha",
            script.display().to_string(),
            vec![],
            BTreeMap::new(),
        );
        let mut manager = McpServerManager::from_bootstraps([bootstrap]);
        let tools = manager.discover_tools().await.expect("discover tools");
        let adapter =
            McpToolAdapter::from_managed_tool(Arc::new(Mutex::new(manager)), tools[0].clone());

        let provider = crate::mock::MockProvider::new(std::collections::VecDeque::from([
            crate::types::AssistantTurn {
                text: None,
                tool_calls: vec![crate::types::ToolCall {
                    id: "call_mcp".into(),
                    name: tools[0].qualified_name.clone(),
                    arguments: json!({"text": "hello"}),
                }],
                stop_reason: crate::types::StopReason::ToolUse,
            },
            crate::types::AssistantTurn {
                text: Some("done".into()),
                tool_calls: vec![],
                stop_reason: crate::types::StopReason::Stop,
            },
        ]));
        let (tx, _rx) = tokio::sync::mpsc::unbounded_channel();
        let messages = SimpleAgent::new(provider)
            .tool(adapter)
            .run_with_history(vec![crate::types::Message::User("call MCP".into())], tx)
            .await;

        assert!(messages.iter().any(|message| matches!(
            message,
            crate::types::Message::ToolResultStructured { content, structured, .. }
                if content == "ECHO:hello" && structured["echoed"] == json!("hello")
        )));
    }
}
