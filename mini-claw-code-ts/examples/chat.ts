import {
  AskTool,
  BashTool,
  CliInputHandler,
  DEFAULT_SYSTEM_PROMPT_TEMPLATE,
  EditTool,
  OpenAICompatibleProvider,
  ReadTool,
  SimpleAgent,
  SYSTEM_PROMPT_FILE_ENV,
  WriteTool,
  loadPromptTemplate,
  systemMessage,
  userMessage,
  type Message,
} from "../src";

const provider = OpenAICompatibleProvider.fromEnv();
const agent = new SimpleAgent(provider)
  .tool(new BashTool())
  .tool(new ReadTool())
  .tool(new WriteTool())
  .tool(new EditTool())
  .tool(new AskTool(new CliInputHandler()));

const cwd = process.cwd();
const systemPrompt = (await loadPromptTemplate(
  SYSTEM_PROMPT_FILE_ENV,
  DEFAULT_SYSTEM_PROMPT_TEMPLATE,
)).replaceAll("{{cwd}}", cwd);

const history: Message[] = [systemMessage(systemPrompt)];

for await (const line of console) {
  const prompt = line.trim();
  if (!prompt) {
    continue;
  }

  history.push(userMessage(prompt));
  process.stdout.write("    thinking...");
  try {
    const result = await agent.chat(history);
    process.stdout.write("\r\x1b[2K");
    console.log(`${result.trim()}\n`);
  } catch (error) {
    process.stdout.write("\r\x1b[2K");
    console.error(`error: ${error instanceof Error ? error.message : String(error)}\n`);
  }
}
