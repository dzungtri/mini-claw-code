use std::io::{self, BufRead, Write};
use std::sync::Arc;
use std::time::Duration;

use mini_code::{
    AgentEvent, BashTool, EditTool, Message, OpenRouterProvider, ReadTool, SimpleAgent, WriteTool,
};
use termimad::crossterm::terminal;
use tokio::sync::mpsc;

const SPINNER: &[char] = &['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏'];

// ANSI helpers
const BOLD_CYAN: &str = "\x1b[1;36m";
const BOLD_MAGENTA: &str = "\x1b[1;35m";
const YELLOW: &str = "\x1b[33m";
const RED: &str = "\x1b[31m";
const DIM: &str = "\x1b[2m";
const RESET: &str = "\x1b[0m";
const CLEAR_LINE: &str = "\x1b[2K\r";

fn print_markdown(text: &str) {
    let trimmed = text.trim();
    if trimmed.is_empty() {
        println!();
        return;
    }

    let width = terminal::size().map(|(w, _)| w as usize).unwrap_or(80);
    // Leave room for 2-space indent
    let text_width = width.saturating_sub(2).max(40);

    let skin = termimad::MadSkin::default();
    let rendered = skin.text(trimmed, Some(text_width)).to_string();

    let mut lines = rendered.lines();
    if let Some(first) = lines.next() {
        println!("{BOLD_MAGENTA}⏺{RESET} {first}");
        for line in lines {
            if line.is_empty() {
                println!();
            } else {
                println!("  {line}");
            }
        }
    }
    println!();
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let provider = OpenRouterProvider::from_env()?;
    let agent = Arc::new(
        SimpleAgent::new(provider)
            .tool(BashTool::new())
            .tool(ReadTool::new())
            .tool(WriteTool::new())
            .tool(EditTool::new()),
    );

    let stdin = io::stdin();
    let mut history: Vec<Message> = Vec::new();
    println!();

    loop {
        print!("{BOLD_CYAN}❯{RESET} ");
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
        println!();

        // Append user message and spawn agent task with full history
        history.push(Message::User(prompt));
        let (tx, mut rx) = mpsc::unbounded_channel();
        let agent = agent.clone();
        let msgs = std::mem::take(&mut history);
        let handle = tokio::spawn(async move { agent.run_with_history(msgs, tx).await });

        // Event loop with spinner
        let mut tick = tokio::time::interval(Duration::from_millis(80));
        let mut frame = 0usize;
        let mut tool_count = 0usize;
        const COLLAPSE_AFTER: usize = 3;

        // Initial spinner
        print!(
            "{BOLD_MAGENTA}⏺{RESET} {YELLOW}{} Thinking...{RESET}",
            SPINNER[0]
        );
        let _ = io::stdout().flush();

        loop {
            tokio::select! {
                event = rx.recv() => {
                    match event {
                        Some(AgentEvent::ToolCall { summary, .. }) => {
                            tool_count += 1;
                            let s = summary.trim();

                            if tool_count <= COLLAPSE_AFTER {
                                // Show tool call normally
                                print!("{CLEAR_LINE}  {DIM}⎿  {s}{RESET}\n");
                            } else if tool_count == COLLAPSE_AFTER + 1 {
                                // First collapsed: clear spinner, print counter
                                print!("{CLEAR_LINE}  {DIM}⎿  ... and 1 more{RESET}\n");
                            } else {
                                // Update counter in-place: clear spinner line, move up,
                                // clear counter line, rewrite counter
                                let extra = tool_count - COLLAPSE_AFTER;
                                print!("{CLEAR_LINE}\x1b[A{CLEAR_LINE}  {DIM}⎿  ... and {extra} more{RESET}\n");
                            }

                            let ch = SPINNER[frame % SPINNER.len()];
                            print!("{BOLD_MAGENTA}⏺{RESET} {YELLOW}{ch} Thinking...{RESET}");
                            let _ = io::stdout().flush();
                        }
                        Some(AgentEvent::Done(text)) => {
                            print!("{CLEAR_LINE}");
                            let _ = io::stdout().flush();
                            if tool_count > 0 { println!(); }
                            print_markdown(&text);
                            break;
                        }
                        Some(AgentEvent::Error(e)) => {
                            print!("{CLEAR_LINE}");
                            let _ = io::stdout().flush();
                            if tool_count > 0 { println!(); }
                            println!("{BOLD_MAGENTA}⏺{RESET} {RED}error: {e}{RESET}\n");
                            break;
                        }
                        None => {
                            print!("{CLEAR_LINE}");
                            let _ = io::stdout().flush();
                            break;
                        }
                    }
                }
                _ = tick.tick() => {
                    frame += 1;
                    let ch = SPINNER[frame % SPINNER.len()];
                    print!("\r{BOLD_MAGENTA}⏺{RESET} {YELLOW}{ch} Thinking...{RESET}");
                    let _ = io::stdout().flush();
                }
            }
        }

        // Recover conversation history from the agent task
        if let Ok(msgs) = handle.await {
            history = msgs;
        }
    }

    Ok(())
}
