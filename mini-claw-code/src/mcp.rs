pub fn normalize_name_for_mcp(name: &str) -> String {
    name.chars()
        .map(|ch| match ch {
            'a'..='z' | 'A'..='Z' | '0'..='9' | '_' | '-' => ch,
            _ => '_',
        })
        .collect()
}

pub fn mcp_tool_prefix(server_name: &str) -> String {
    format!("mcp__{}__", normalize_name_for_mcp(server_name))
}

pub fn mcp_tool_name(server_name: &str, tool_name: &str) -> String {
    format!(
        "{}{}",
        mcp_tool_prefix(server_name),
        normalize_name_for_mcp(tool_name)
    )
}

#[cfg(test)]
mod tests {
    use super::{mcp_tool_name, mcp_tool_prefix, normalize_name_for_mcp};

    #[test]
    fn normalizes_names() {
        assert_eq!(normalize_name_for_mcp("github.com"), "github_com");
        assert_eq!(normalize_name_for_mcp("tool name!"), "tool_name_");
        assert_eq!(mcp_tool_prefix("github.com"), "mcp__github_com__");
        assert_eq!(
            mcp_tool_name("github.com", "search issues"),
            "mcp__github_com__search_issues"
        );
    }
}
