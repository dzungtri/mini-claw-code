use std::io::{self, BufRead, Write};
use std::sync::Arc;

use mini_claw_code::{
    AskTool, BashTool, CliInputHandler, DEFAULT_SYSTEM_PROMPT_TEMPLATE, EditTool, Message,
    OpenRouterProvider, ReadTool, SYSTEM_PROMPT_FILE_ENV, SimpleAgent, WriteTool,
    load_prompt_template,
};

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let provider = OpenRouterProvider::from_env()?;
    let agent = SimpleAgent::new(provider)
        .tool(BashTool::new())
        .tool(ReadTool::new())
        .tool(WriteTool::new())
        .tool(EditTool::new())
        .tool(AskTool::new(Arc::new(CliInputHandler)));

    let cwd = std::env::current_dir()?.display().to_string();
    let system_prompt =
        load_prompt_template(SYSTEM_PROMPT_FILE_ENV, DEFAULT_SYSTEM_PROMPT_TEMPLATE)?
            .replace("{{cwd}}", &cwd);
    let stdin = io::stdin();
    let mut history: Vec<Message> = vec![Message::System(system_prompt)];

    loop {
        print!("> ");
        io::stdout().flush()?;

        let mut line = String::new();
        if stdin.lock().read_line(&mut line)? == 0 {
            println!();
            break;
        }

        let prompt = line.trim();
        if prompt.is_empty() {
            continue;
        }

        history.push(Message::User(prompt.to_string()));
        print!("    thinking...");
        io::stdout().flush()?;
        match agent.chat(&mut history).await {
            Ok(text) => {
                print!("\x1b[2K\r");
                println!("{}\n", text.trim());
            }
            Err(e) => {
                print!("\x1b[2K\r");
                println!("error: {e}\n");
            }
        }
    }

    Ok(())
}
