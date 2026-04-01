use std::io::{self, BufRead, Write};
use std::sync::Arc;
use std::time::Duration;

use mini_claw_code::{
    AgentEvent, AskTool, BashTool, ChannelInputHandler, DEFAULT_PLAN_PROMPT_TEMPLATE, EditTool,
    McpClientBootstrap, McpServerManager, McpToolAdapter, Message, OpenRouterProvider,
    PLAN_PROMPT_FILE_ENV, PermissionMode, PlanAgent, ProviderKind, ReadTool, SubagentTool, ToolSet,
    UserInputRequest, WriteTool, load_prompt_template,
};
use serde_json::Value;
use tokio::sync::Mutex;
use tokio::sync::mpsc;

const SPINNER: &[char] = &['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏'];

// ANSI helpers
const BOLD_CYAN: &str = "\x1b[1;36m";
const BOLD_MAGENTA: &str = "\x1b[1;35m";
const BOLD_GREEN: &str = "\x1b[1;32m";
const YELLOW: &str = "\x1b[33m";
const RED: &str = "\x1b[31m";
const DIM: &str = "\x1b[2m";
const RESET: &str = "\x1b[0m";
const CLEAR_LINE: &str = "\x1b[2K\r";
const PERMISSION_MODE_ENV: &str = "MINI_CLAW_PERMISSION_MODE";
const ENABLE_SUBAGENT_ENV: &str = "MINI_CLAW_ENABLE_SUBAGENT";
const SUBAGENT_MAX_TURNS_ENV: &str = "MINI_CLAW_SUBAGENT_MAX_TURNS";
const SUBAGENT_SYSTEM_PROMPT_ENV: &str = "MINI_CLAW_SUBAGENT_SYSTEM_PROMPT";
const MCP_SERVERS_JSON_ENV: &str = "MINI_CLAW_MCP_SERVERS_JSON";

fn read_bool_env(name: &str, default: bool) -> bool {
    std::env::var(name)
        .ok()
        .map(|v| match v.trim().to_ascii_lowercase().as_str() {
            "1" | "true" | "yes" | "on" => true,
            "0" | "false" | "no" | "off" => false,
            _ => default,
        })
        .unwrap_or(default)
}

fn parse_permission_mode_from_env() -> PermissionMode {
    let Ok(raw) = std::env::var(PERMISSION_MODE_ENV) else {
        return PermissionMode::DangerFullAccess;
    };
    match raw.trim().to_ascii_lowercase().as_str() {
        "read-only" | "readonly" => PermissionMode::ReadOnly,
        "workspace-write" | "workspacewrite" => PermissionMode::WorkspaceWrite,
        "danger-full-access" | "dangerfullaccess" | "danger" => PermissionMode::DangerFullAccess,
        "prompt" => PermissionMode::Prompt,
        "allow" => PermissionMode::Allow,
        _ => PermissionMode::DangerFullAccess,
    }
}

fn read_subagent_max_turns() -> usize {
    std::env::var(SUBAGENT_MAX_TURNS_ENV)
        .ok()
        .and_then(|v| v.parse::<usize>().ok())
        .filter(|v| *v > 0)
        .unwrap_or(8)
}

async fn load_mcp_adapters_from_env() -> anyhow::Result<Vec<McpToolAdapter>> {
    let raw = match std::env::var(MCP_SERVERS_JSON_ENV) {
        Ok(v) if !v.trim().is_empty() => v,
        _ => return Ok(Vec::new()),
    };

    let json: Value =
        serde_json::from_str(&raw).map_err(|e| anyhow::anyhow!("{MCP_SERVERS_JSON_ENV}: {e}"))?;
    let servers = json.as_array().ok_or_else(|| {
        anyhow::anyhow!("{MCP_SERVERS_JSON_ENV} must be a JSON array of server objects")
    })?;

    let mut bootstraps = Vec::new();
    for entry in servers {
        let name = entry
            .get("name")
            .and_then(Value::as_str)
            .filter(|v| !v.trim().is_empty())
            .ok_or_else(|| anyhow::anyhow!("MCP server entry missing non-empty `name`"))?;
        let command = entry
            .get("command")
            .and_then(Value::as_str)
            .filter(|v| !v.trim().is_empty())
            .ok_or_else(|| anyhow::anyhow!("MCP server `{name}` missing non-empty `command`"))?;

        let args = entry
            .get("args")
            .and_then(Value::as_array)
            .map(|items| {
                items
                    .iter()
                    .filter_map(|item| item.as_str().map(ToString::to_string))
                    .collect::<Vec<_>>()
            })
            .unwrap_or_default();

        let env = entry
            .get("env")
            .and_then(Value::as_object)
            .map(|map| {
                map.iter()
                    .filter_map(|(k, v)| v.as_str().map(|s| (k.clone(), s.to_string())))
                    .collect::<std::collections::BTreeMap<_, _>>()
            })
            .unwrap_or_default();

        bootstraps.push(McpClientBootstrap::stdio(name, command, args, env));
    }

    if bootstraps.is_empty() {
        return Ok(Vec::new());
    }

    let mut manager = McpServerManager::from_bootstraps(bootstraps);
    let discovered = manager.discover_tools().await?;
    let shared = Arc::new(Mutex::new(manager));
    Ok(discovered
        .into_iter()
        .map(|tool| McpToolAdapter::from_managed_tool(shared.clone(), tool))
        .collect())
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct SessionModelConfig {
    provider: ProviderKind,
    model_override: Option<String>,
}

#[derive(Debug, Clone)]
struct SessionSettings {
    plan_prompt: String,
    permission_mode: PermissionMode,
    enable_subagent: bool,
    subagent_max_turns: usize,
    subagent_system_prompt: Option<String>,
}

fn detected_provider_kinds() -> Vec<ProviderKind> {
    ProviderKind::all()
        .into_iter()
        .filter(|kind| kind.is_configured())
        .collect()
}

fn initial_provider_kind() -> anyhow::Result<ProviderKind> {
    detected_provider_kinds()
        .into_iter()
        .next()
        .ok_or_else(|| {
            anyhow::anyhow!(
                "No provider API key configured. Set OPENROUTER_API_KEY, OPENAI_API_KEY, or GEMINI_API_KEY."
            )
        })
}

fn effective_model(config: &SessionModelConfig) -> String {
    config
        .model_override
        .clone()
        .unwrap_or_else(|| OpenRouterProvider::default_model_for_kind(config.provider))
}

fn suggested_models_for(kind: ProviderKind) -> Vec<String> {
    match kind {
        ProviderKind::OpenRouter => vec![
            "openrouter/free".to_string(),
            "openai/gpt-4o-mini".to_string(),
            "anthropic/claude-3.5-sonnet".to_string(),
            "google/gemini-2.0-flash".to_string(),
        ],
        ProviderKind::OpenAI => vec![
            "gpt-4o-mini".to_string(),
            "gpt-4.1-mini".to_string(),
            "gpt-4.1".to_string(),
        ],
        ProviderKind::Gemini => vec![
            "gemini-2.0-flash".to_string(),
            "gemini-2.0-flash-lite".to_string(),
            "gemini-1.5-pro".to_string(),
        ],
    }
}

async fn build_agent(
    model: &SessionModelConfig,
    settings: &SessionSettings,
    handler: Arc<ChannelInputHandler>,
) -> anyhow::Result<(Arc<PlanAgent<OpenRouterProvider>>, usize)> {
    let provider =
        OpenRouterProvider::from_kind_and_env(model.provider, model.model_override.clone())?;
    let subagent_provider = Arc::new(OpenRouterProvider::from_kind_and_env(
        model.provider,
        model.model_override.clone(),
    )?);

    let mut agent = PlanAgent::new(provider)
        .plan_prompt(settings.plan_prompt.clone())
        .permission_mode(settings.permission_mode)
        .tool(BashTool::new())
        .tool(ReadTool::new())
        .tool(WriteTool::new())
        .tool(EditTool::new())
        .tool(AskTool::new(handler));

    if settings.enable_subagent {
        let mut subagent = SubagentTool::new(subagent_provider, || {
            ToolSet::new()
                .with(BashTool::new())
                .with(ReadTool::new())
                .with(WriteTool::new())
                .with(EditTool::new())
        })
        .max_turns(settings.subagent_max_turns);

        if let Some(prompt) = settings.subagent_system_prompt.clone()
            && !prompt.trim().is_empty()
        {
            subagent = subagent.system_prompt(prompt);
        }

        agent = agent.tool(subagent);
    }

    let mcp_adapters = load_mcp_adapters_from_env().await?;
    let mcp_tool_count = mcp_adapters.len();
    for adapter in mcp_adapters {
        agent = agent.tool(adapter);
    }

    Ok((Arc::new(agent), mcp_tool_count))
}

/// Present options as an arrow-key-navigable list using crossterm raw mode.
///
/// Returns the selected option string, or switches to free-text if the user
/// types any letter.
fn select_option(question: &str, options: &[String]) -> io::Result<String> {
    use crossterm::{
        cursor,
        event::{self, Event, KeyCode, KeyEvent},
        terminal,
    };

    terminal::enable_raw_mode()?;

    let mut selected: usize = 0;
    let mut stdout = io::stdout();

    // Draw initial list
    write!(stdout, "\r\n  {BOLD_CYAN}{question}{RESET}\r\n")?;
    for (i, opt) in options.iter().enumerate() {
        if i == selected {
            write!(stdout, "  {BOLD_CYAN}> {opt}{RESET}\r\n")?;
        } else {
            write!(stdout, "    {opt}\r\n")?;
        }
    }
    stdout.flush()?;

    loop {
        if event::poll(Duration::from_millis(100))?
            && let Event::Key(KeyEvent { code, .. }) = event::read()?
        {
            match code {
                KeyCode::Up => {
                    selected = selected.saturating_sub(1);
                }
                KeyCode::Down => {
                    if selected + 1 < options.len() {
                        selected += 1;
                    }
                }
                KeyCode::Enter => {
                    terminal::disable_raw_mode()?;
                    // Move past the list
                    write!(
                        stdout,
                        "\r{CLEAR_LINE}  {DIM}> {}{RESET}\r\n",
                        options[selected]
                    )?;
                    stdout.flush()?;
                    return Ok(options[selected].clone());
                }
                KeyCode::Char(_) => {
                    // Switch to free-text mode
                    terminal::disable_raw_mode()?;
                    write!(stdout, "\r{CLEAR_LINE}  > ")?;
                    stdout.flush()?;
                    let mut line = String::new();
                    io::stdin().lock().read_line(&mut line)?;
                    return Ok(line.trim().to_string());
                }
                KeyCode::Esc => {
                    terminal::disable_raw_mode()?;
                    return Ok(options[selected].clone());
                }
                _ => {}
            }

            // Redraw list — move cursor up to start of list
            write!(stdout, "{}", cursor::MoveUp(options.len() as u16))?;
            for (i, opt) in options.iter().enumerate() {
                if i == selected {
                    write!(stdout, "\r{CLEAR_LINE}  {BOLD_CYAN}> {opt}{RESET}\r\n")?;
                } else {
                    write!(stdout, "\r{CLEAR_LINE}    {opt}\r\n")?;
                }
            }
            stdout.flush()?;
        }
    }
}

/// Handle a UserInputRequest: either show arrow-key selection or a simple prompt.
fn handle_input_request(req: UserInputRequest) {
    let answer = if req.options.is_empty() {
        // Simple text prompt
        print!("\n  {BOLD_CYAN}{}{RESET}\n  > ", req.question);
        let _ = io::stdout().flush();
        let mut line = String::new();
        let _ = io::stdin().lock().read_line(&mut line);
        line.trim().to_string()
    } else {
        // Arrow-key selection
        match select_option(&req.question, &req.options) {
            Ok(s) => s,
            Err(_) => req.options.first().cloned().unwrap_or_default(),
        }
    };
    let _ = req.response_tx.send(answer);
}

/// Run the streaming UI event loop: spinner, tool calls, streamed text.
/// Returns when `Done` or `Error` is received.
async fn ui_event_loop(
    rx: &mut mpsc::UnboundedReceiver<AgentEvent>,
    input_rx: &mut mpsc::UnboundedReceiver<UserInputRequest>,
    spinner_label: &str,
) {
    let mut tick = tokio::time::interval(Duration::from_millis(80));
    let mut frame = 0usize;
    let mut tool_count = 0usize;
    let mut streaming_text = false;
    let mut text_buf = String::new();
    const COLLAPSE_AFTER: usize = 3;

    print!(
        "{BOLD_MAGENTA}⏺{RESET} {YELLOW}{} {spinner_label}{RESET}",
        SPINNER[0]
    );
    let _ = io::stdout().flush();

    loop {
        tokio::select! {
            event = rx.recv() => {
                match event {
                    Some(AgentEvent::TextDelta(text)) => {
                        if !streaming_text {
                            // First delta: clear the spinner line
                            print!("{CLEAR_LINE}");
                            streaming_text = true;
                        }
                        print!("{text}");
                        let _ = io::stdout().flush();
                        text_buf.push_str(&text);
                    }
                    Some(AgentEvent::ToolCall { summary, .. }) => {
                        tool_count += 1;
                        streaming_text = false;
                        text_buf.clear();

                        if tool_count <= COLLAPSE_AFTER {
                            println!("{CLEAR_LINE}  {DIM}⎿  {summary}{RESET}");
                        } else if tool_count == COLLAPSE_AFTER + 1 {
                            println!("{CLEAR_LINE}  {DIM}⎿  ... and 1 more{RESET}");
                        } else {
                            let extra = tool_count - COLLAPSE_AFTER;
                            println!(
                                "{CLEAR_LINE}\x1b[A{CLEAR_LINE}  {DIM}⎿  ... and {extra} more{RESET}"
                            );
                        }

                        let ch = SPINNER[frame % SPINNER.len()];
                        print!("{BOLD_MAGENTA}⏺{RESET} {YELLOW}{ch} {spinner_label}{RESET}");
                        let _ = io::stdout().flush();
                    }
                    Some(AgentEvent::Done(_)) => {
                        if streaming_text && !text_buf.is_empty() {
                            // Clear the raw streamed text and re-render with markdown
                            let raw_lines = text_buf.chars().filter(|&c| c == '\n').count() + 1;
                            // Move cursor up and clear each line
                            for _ in 0..raw_lines {
                                print!("\x1b[A{CLEAR_LINE}");
                            }
                            print!("{CLEAR_LINE}");
                            let rendered = termimad::text(&text_buf);
                            println!("{rendered}");
                        } else {
                            println!("{CLEAR_LINE}");
                        }
                        let _ = io::stdout().flush();
                        return;
                    }
                    Some(AgentEvent::Error(e)) => {
                        print!("{CLEAR_LINE}");
                        let _ = io::stdout().flush();
                        if tool_count > 0 { println!(); }
                        println!("{BOLD_MAGENTA}⏺{RESET} {RED}error: {e}{RESET}\n");
                        return;
                    }
                    None => {
                        print!("{CLEAR_LINE}");
                        let _ = io::stdout().flush();
                        return;
                    }
                }
            }
            Some(req) = input_rx.recv() => {
                print!("{CLEAR_LINE}");
                let _ = io::stdout().flush();
                streaming_text = false;

                tokio::task::spawn_blocking(move || handle_input_request(req))
                    .await
                    .ok();

                let ch = SPINNER[frame % SPINNER.len()];
                print!("{BOLD_MAGENTA}⏺{RESET} {YELLOW}{ch} {spinner_label}{RESET}");
                let _ = io::stdout().flush();
            }
            _ = tick.tick() => {
                if !streaming_text {
                    frame += 1;
                    let ch = SPINNER[frame % SPINNER.len()];
                    print!("\r{BOLD_MAGENTA}⏺{RESET} {YELLOW}{ch} {spinner_label}{RESET}");
                    let _ = io::stdout().flush();
                }
            }
        }
    }
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let settings = SessionSettings {
        plan_prompt: load_prompt_template(PLAN_PROMPT_FILE_ENV, DEFAULT_PLAN_PROMPT_TEMPLATE)?,
        permission_mode: parse_permission_mode_from_env(),
        enable_subagent: read_bool_env(ENABLE_SUBAGENT_ENV, true),
        subagent_max_turns: read_subagent_max_turns(),
        subagent_system_prompt: std::env::var(SUBAGENT_SYSTEM_PROMPT_ENV).ok(),
    };

    // Channel for AskTool → TUI communication
    let (input_tx, mut input_rx) = mpsc::unbounded_channel::<UserInputRequest>();
    let handler = Arc::new(ChannelInputHandler::new(input_tx));

    let mut model_config = SessionModelConfig {
        provider: initial_provider_kind()?,
        model_override: std::env::var("MODEL").ok().filter(|v| !v.trim().is_empty()),
    };
    let (mut agent, mcp_tool_count) =
        build_agent(&model_config, &settings, handler.clone()).await?;

    let stdin = io::stdin();
    let mut history: Vec<Message> = Vec::new();
    let mut plan_mode = false;
    println!(
        "{DIM}[config] provider={}; model={}; permission_mode={}; subagent={}; mcp_tools={mcp_tool_count}{RESET}",
        model_config.provider.as_str(),
        effective_model(&model_config),
        settings.permission_mode.as_str(),
        if settings.enable_subagent {
            "on"
        } else {
            "off"
        }
    );
    println!();

    loop {
        if plan_mode {
            print!("{BOLD_GREEN}[plan]{RESET} {BOLD_CYAN}>{RESET} ");
        } else {
            print!("{BOLD_CYAN}>{RESET} ");
        }
        io::stdout().flush()?;

        let mut line = String::new();
        if stdin.lock().read_line(&mut line)? == 0 {
            println!();
            break;
        }
        let prompt = line.trim().to_string();
        if prompt.is_empty() {
            continue;
        }

        if prompt == "/help" {
            println!("  {BOLD_GREEN}Slash commands{RESET}");
            println!("  {DIM}/plan{RESET}               Toggle plan mode");
            println!("  {DIM}/provider{RESET}           Choose provider interactively");
            println!(
                "  {DIM}/provider <name>{RESET}    Switch provider (openrouter|openai|gemini)"
            );
            println!("  {DIM}/model{RESET}              Choose model interactively");
            println!("  {DIM}/model <id>{RESET}         Set model override");
            println!("  {DIM}/help{RESET}               Show this help\n");
            continue;
        }

        // Toggle plan mode
        if prompt == "/plan" {
            plan_mode = !plan_mode;
            if plan_mode {
                println!("  {BOLD_GREEN}Plan mode ON{RESET} — agent will plan before executing.\n");
            } else {
                println!("  {DIM}Plan mode OFF{RESET} — agent executes directly.\n");
            }
            continue;
        }

        if let Some(rest) = prompt.strip_prefix("/provider") {
            let arg = rest.trim();
            let target_provider = if arg.is_empty() {
                let available = detected_provider_kinds();
                if available.is_empty() {
                    println!("  {RED}No configured providers found.{RESET}\n");
                    continue;
                }
                let options = available
                    .iter()
                    .map(|kind| kind.as_str().to_string())
                    .collect::<Vec<_>>();
                match select_option("Select provider", &options) {
                    Ok(choice) => ProviderKind::parse(choice.trim()),
                    Err(e) => {
                        println!("  {RED}failed to open selection: {e}{RESET}\n");
                        continue;
                    }
                }
            } else {
                ProviderKind::parse(arg)
            };

            let Some(provider) = target_provider else {
                println!("  {RED}Unknown provider. Use openrouter, openai, or gemini.{RESET}\n");
                continue;
            };
            model_config.provider = provider;
            model_config.model_override = None;
            match build_agent(&model_config, &settings, handler.clone()).await {
                Ok((new_agent, mcp_count)) => {
                    agent = new_agent;
                    println!(
                        "  {BOLD_GREEN}Switched provider{RESET}: {} ({}) [mcp_tools={mcp_count}]\n",
                        model_config.provider.as_str(),
                        effective_model(&model_config)
                    );
                }
                Err(e) => {
                    println!("  {RED}failed to switch provider: {e}{RESET}\n");
                }
            }
            continue;
        }

        if let Some(rest) = prompt.strip_prefix("/model") {
            let arg = rest.trim();
            let next_model = if arg.is_empty() {
                let options = suggested_models_for(model_config.provider);
                match select_option("Select model", &options) {
                    Ok(choice) => choice.trim().to_string(),
                    Err(e) => {
                        println!("  {RED}failed to open selection: {e}{RESET}\n");
                        continue;
                    }
                }
            } else {
                arg.to_string()
            };
            if next_model.trim().is_empty() {
                println!("  {RED}model cannot be empty{RESET}\n");
                continue;
            }

            model_config.model_override = Some(next_model);
            match build_agent(&model_config, &settings, handler.clone()).await {
                Ok((new_agent, mcp_count)) => {
                    agent = new_agent;
                    println!(
                        "  {BOLD_GREEN}Active model{RESET}: {} / {} (mcp_tools={mcp_count})\n",
                        model_config.provider.as_str(),
                        effective_model(&model_config)
                    );
                }
                Err(e) => {
                    println!("  {RED}failed to switch model: {e}{RESET}\n");
                }
            }
            continue;
        }

        println!();
        history.push(Message::User(prompt));

        if plan_mode {
            // ---- PLAN → APPROVE → EXECUTE ----
            loop {
                // Plan phase
                let (tx, mut rx) = mpsc::unbounded_channel();
                let agent_clone = agent.clone();
                let mut msgs = std::mem::take(&mut history);
                let handle = tokio::spawn(async move {
                    let result = agent_clone.plan(&mut msgs, tx).await;
                    (msgs, result)
                });

                ui_event_loop(&mut rx, &mut input_rx, "Planning...").await;

                let (msgs, plan_result) = handle.await?;
                history = msgs;

                if plan_result.is_err() {
                    break; // error already shown by ui_event_loop
                }

                // Approval prompt
                print!("  {BOLD_GREEN}Accept this plan?{RESET} {DIM}[y/n/feedback]{RESET} ");
                io::stdout().flush()?;

                let mut response = String::new();
                stdin.lock().read_line(&mut response)?;
                let response = response.trim().to_string();
                println!();

                if response.is_empty() || response.eq_ignore_ascii_case("y") {
                    // Execute phase
                    history.push(Message::User("Approved. Execute the plan.".into()));

                    let (tx2, mut rx2) = mpsc::unbounded_channel();
                    let agent_clone = agent.clone();
                    let mut msgs = std::mem::take(&mut history);
                    let handle2 = tokio::spawn(async move {
                        let _ = agent_clone.execute(&mut msgs, tx2).await;
                        msgs
                    });

                    ui_event_loop(&mut rx2, &mut input_rx, "Executing...").await;

                    if let Ok(msgs) = handle2.await {
                        history = msgs;
                    }
                    break;
                } else if response.eq_ignore_ascii_case("n") {
                    history.push(Message::User(
                        "Rejected. I'll give you new instructions.".into(),
                    ));
                    break;
                } else {
                    // Feedback → re-plan
                    history.push(Message::User(response));
                    // loop continues → calls plan() again
                }
            }
        } else {
            // ---- NORMAL MODE (execute directly) ----
            let (tx, mut rx) = mpsc::unbounded_channel();
            let agent_clone = agent.clone();
            let mut msgs = std::mem::take(&mut history);
            let handle = tokio::spawn(async move {
                let _ = agent_clone.execute(&mut msgs, tx).await;
                msgs
            });

            ui_event_loop(&mut rx, &mut input_rx, "Thinking...").await;

            if let Ok(msgs) = handle.await {
                history = msgs;
            }
        }
    }

    Ok(())
}
