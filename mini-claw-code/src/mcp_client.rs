use std::collections::BTreeMap;

use crate::mcp::{mcp_tool_prefix, normalize_name_for_mcp};

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum McpClientTransport {
    Stdio(McpStdioTransport),
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct McpStdioTransport {
    pub command: String,
    pub args: Vec<String>,
    pub env: BTreeMap<String, String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct McpClientBootstrap {
    pub server_name: String,
    pub normalized_name: String,
    pub tool_prefix: String,
    pub signature: String,
    pub transport: McpClientTransport,
}

impl McpClientBootstrap {
    pub fn stdio(
        server_name: impl Into<String>,
        command: impl Into<String>,
        args: Vec<String>,
        env: BTreeMap<String, String>,
    ) -> Self {
        let server_name = server_name.into();
        let command = command.into();
        let mut signature_parts = vec![command.clone()];
        signature_parts.extend(args.iter().cloned());
        Self {
            normalized_name: normalize_name_for_mcp(&server_name),
            tool_prefix: mcp_tool_prefix(&server_name),
            signature: format!("stdio:[{}]", signature_parts.join("|")),
            transport: McpClientTransport::Stdio(McpStdioTransport { command, args, env }),
            server_name,
        }
    }
}

#[cfg(test)]
mod tests {
    use std::collections::BTreeMap;

    use super::{McpClientBootstrap, McpClientTransport};

    #[test]
    fn builds_stdio_bootstrap() {
        let bootstrap = McpClientBootstrap::stdio(
            "alpha",
            "python3",
            vec!["server.py".into()],
            BTreeMap::from([("TOKEN".to_string(), "secret".to_string())]),
        );

        assert_eq!(bootstrap.server_name, "alpha");
        assert_eq!(bootstrap.normalized_name, "alpha");
        assert_eq!(bootstrap.tool_prefix, "mcp__alpha__");
        assert_eq!(bootstrap.signature, "stdio:[python3|server.py]");
        match bootstrap.transport {
            McpClientTransport::Stdio(transport) => {
                assert_eq!(transport.command, "python3");
                assert_eq!(transport.args, vec!["server.py"]);
                assert_eq!(
                    transport.env.get("TOKEN").map(String::as_str),
                    Some("secret")
                );
            }
        }
    }
}
