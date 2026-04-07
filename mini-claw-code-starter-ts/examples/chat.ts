import { stdin as input, stdout as output } from "node:process";
import readline from "node:readline/promises";

import {
  BashTool,
  EditTool,
  OpenAICompatibleProvider,
  ReadTool,
  SimpleAgent,
  WriteTool,
  type Message,
} from "../src";

async function main(): Promise<void> {
  const provider = OpenAICompatibleProvider.fromEnv();
  const agent = SimpleAgent.new(provider)
    .tool(BashTool.new())
    .tool(ReadTool.new())
    .tool(WriteTool.new())
    .tool(EditTool.new());

  const rl = readline.createInterface({ input, output });
  const history: Message[] = [
    {
      kind: "system",
      text: `You are a coding agent working in ${process.cwd()}.`,
    },
  ];

  while (true) {
    const prompt = (await rl.question("> ")).trim();
    if (!prompt) {
      continue;
    }
    if (prompt === "/exit") {
      break;
    }

    history.push({ kind: "user", text: prompt });
    const result = await agent.chat(history);
    output.write(`${result}\n\n`);
  }

  rl.close();
}

void main();
