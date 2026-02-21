use mini_code::{
    BashTool, EditTool, Message, OpenRouterProvider, ReadTool, SimpleAgent, WriteTool,
};
use std::io::{self, BufRead, Write};

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let provider = OpenRouterProvider::from_env()?;
    let agent = SimpleAgent::new(provider)
        .tool(BashTool::new())
        .tool(ReadTool::new())
        .tool(WriteTool::new())
        .tool(EditTool::new());

    let stdin = io::stdin();
    let mut history: Vec<Message> = Vec::new();

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
