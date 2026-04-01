use anyhow::Context;
use serde_json::Value;
use tokio::time::{Duration, timeout};

use crate::permissions::PermissionMode;
use crate::sandbox::{
    FilesystemIsolationMode, SandboxConfig, build_linux_sandbox_command,
    resolve_sandbox_status_for_request,
};
use crate::types::*;

pub struct BashTool {
    definition: ToolDefinition,
}

impl Default for BashTool {
    fn default() -> Self {
        Self::new()
    }
}

impl BashTool {
    pub fn new() -> Self {
        Self {
            definition: ToolDefinition::new("bash", "Run a bash command and return its output.")
                .required_permission(PermissionMode::DangerFullAccess)
                .param("command", "string", "The bash command to run", true)
                .param(
                    "timeout",
                    "integer",
                    "Optional timeout in milliseconds",
                    false,
                )
                .param(
                    "dangerouslyDisableSandbox",
                    "boolean",
                    "Disable sandboxing for this command",
                    false,
                )
                .param(
                    "namespaceRestrictions",
                    "boolean",
                    "Enable namespace restrictions where supported",
                    false,
                )
                .param(
                    "isolateNetwork",
                    "boolean",
                    "Disable network access where supported",
                    false,
                )
                .param(
                    "filesystemMode",
                    "string",
                    "Filesystem mode: off, workspace-only, or allow-list",
                    false,
                )
                .param_raw(
                    "allowedMounts",
                    serde_json::json!({
                        "type": "array",
                        "items": { "type": "string" }
                    }),
                    false,
                ),
        }
    }
}

#[async_trait::async_trait]
impl Tool for BashTool {
    fn definition(&self) -> &ToolDefinition {
        &self.definition
    }

    async fn call(&self, args: Value) -> anyhow::Result<ToolOutput> {
        let command = args["command"]
            .as_str()
            .context("missing 'command' argument")?;
        let timeout_ms = args.get("timeout").and_then(|value| value.as_u64());
        let dangerously_disable_sandbox = args
            .get("dangerouslyDisableSandbox")
            .and_then(|value| value.as_bool())
            .unwrap_or(false);
        let namespace_restrictions = args
            .get("namespaceRestrictions")
            .and_then(|value| value.as_bool());
        let isolate_network = args.get("isolateNetwork").and_then(|value| value.as_bool());
        let filesystem_mode = args
            .get("filesystemMode")
            .and_then(|value| value.as_str())
            .and_then(|value| match value {
                "off" => Some(FilesystemIsolationMode::Off),
                "workspace-only" => Some(FilesystemIsolationMode::WorkspaceOnly),
                "allow-list" => Some(FilesystemIsolationMode::AllowList),
                _ => None,
            });
        let allowed_mounts = args
            .get("allowedMounts")
            .and_then(|value| value.as_array())
            .map(|items| {
                items
                    .iter()
                    .filter_map(|item| item.as_str().map(ToString::to_string))
                    .collect::<Vec<_>>()
            });

        let cwd = std::env::current_dir().context("failed to resolve current working directory")?;
        let config = SandboxConfig {
            enabled: Some(!dangerously_disable_sandbox),
            namespace_restrictions: Some(namespace_restrictions.unwrap_or(true)),
            network_isolation: Some(isolate_network.unwrap_or(false)),
            filesystem_mode: Some(
                filesystem_mode.unwrap_or(FilesystemIsolationMode::WorkspaceOnly),
            ),
            allowed_mounts: allowed_mounts.clone().unwrap_or_default(),
        };
        let request = config.resolve_request(
            Some(!dangerously_disable_sandbox),
            namespace_restrictions,
            isolate_network,
            filesystem_mode,
            allowed_mounts,
        );
        let sandbox_status = resolve_sandbox_status_for_request(&request, &cwd);
        let mut process =
            if let Some(launcher) = build_linux_sandbox_command(command, &cwd, &sandbox_status) {
                let mut process = tokio::process::Command::new(launcher.program);
                process.args(launcher.args);
                process.current_dir(&cwd);
                process.envs(launcher.env);
                process
            } else {
                let mut process = tokio::process::Command::new("bash");
                process.arg("-c").arg(command).current_dir(&cwd);
                if sandbox_status.filesystem_active {
                    let sandbox_home = cwd.join(".sandbox-home");
                    let sandbox_tmp = cwd.join(".sandbox-tmp");
                    let _ = tokio::fs::create_dir_all(&sandbox_home).await;
                    let _ = tokio::fs::create_dir_all(&sandbox_tmp).await;
                    process.env("HOME", sandbox_home);
                    process.env("TMPDIR", sandbox_tmp);
                }
                process
            };

        let output = if let Some(timeout_ms) = timeout_ms {
            match timeout(Duration::from_millis(timeout_ms), process.output()).await {
                Ok(result) => result.context("failed to run bash command")?,
                Err(_) => {
                    return Ok(ToolOutput::rich(
                        format!("Command exceeded timeout of {timeout_ms} ms"),
                        serde_json::json!({
                            "interrupted": true,
                            "timeoutMs": timeout_ms,
                            "sandboxStatus": sandbox_status,
                        }),
                    ));
                }
            }
        } else {
            process
                .output()
                .await
                .context("failed to run bash command")?
        };

        let stdout = String::from_utf8_lossy(&output.stdout);
        let stderr = String::from_utf8_lossy(&output.stderr);

        let mut result = String::new();
        if !stdout.is_empty() {
            result.push_str(&stdout);
        }
        if !stderr.is_empty() {
            if !result.is_empty() {
                result.push('\n');
            }
            result.push_str("stderr: ");
            result.push_str(&stderr);
        }
        if result.is_empty() {
            result.push_str("(no output)");
        }

        Ok(ToolOutput::rich(
            result,
            serde_json::json!({
                "returnCode": output.status.code(),
                "sandboxStatus": sandbox_status,
            }),
        ))
    }
}
