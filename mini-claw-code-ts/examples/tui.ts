import {
  AskTool,
  BashTool,
  ChannelInputHandler,
  DEFAULT_PLAN_PROMPT_TEMPLATE,
  EditTool,
  OpenAICompatibleProvider,
  PLAN_PROMPT_FILE_ENV,
  PlanAgent,
  ReadTool,
  WriteTool,
  loadPromptTemplate,
  userMessage,
  type Message,
  type UserInputRequest,
} from "../src";

const provider = OpenAICompatibleProvider.fromEnv();

async function handleInputRequest(request: UserInputRequest): Promise<string> {
  const renderedOptions =
    request.options.length === 0
      ? ""
      : `\n${request.options.map((option, index) => `  ${index + 1}) ${option}`).join("\n")}`;
  const answer = (await prompt(`${request.question}${renderedOptions}\n> `)) ?? "";
  const asNumber = Number(answer);
  if (Number.isInteger(asNumber) && asNumber >= 1 && asNumber <= request.options.length) {
    return request.options[asNumber - 1]!;
  }
  return answer;
}

const agent = new PlanAgent(provider)
  .planPrompt(await loadPromptTemplate(PLAN_PROMPT_FILE_ENV, DEFAULT_PLAN_PROMPT_TEMPLATE))
  .tool(new BashTool())
  .tool(new ReadTool())
  .tool(new WriteTool())
  .tool(new EditTool())
  .tool(new AskTool(new ChannelInputHandler(handleInputRequest)));

const history: Message[] = [];
let planMode = false;

for await (const line of console) {
  const promptText = line.trim();
  if (!promptText) {
    continue;
  }

  if (promptText === "/plan") {
    planMode = !planMode;
    console.log(planMode ? "Plan mode ON\n" : "Plan mode OFF\n");
    continue;
  }

  history.push(userMessage(promptText));

  if (!planMode) {
    const result = await agent.execute(history, async (event) => {
      if (event.kind === "text_delta") {
        process.stdout.write(event.text);
      }
      if (event.kind === "tool_call") {
        process.stdout.write(`\n${event.summary}\n`);
      }
    });
    console.log(`\n${result}\n`);
    continue;
  }

  const plan = await agent.plan(history, async (event) => {
    if (event.kind === "text_delta") {
      process.stdout.write(event.text);
    }
  });
  console.log(`\n\nPlan:\n${plan}\n`);
  const approval = ((await prompt("Accept this plan? [y/n/feedback] ")) ?? "")
    .trim()
    .toLowerCase();
  if (approval === "y" || approval === "yes") {
    const result = await agent.execute(history, async (event) => {
      if (event.kind === "text_delta") {
        process.stdout.write(event.text);
      }
      if (event.kind === "tool_call") {
        process.stdout.write(`\n${event.summary}\n`);
      }
    });
    console.log(`\n${result}\n`);
  } else {
    history.push(userMessage(approval));
  }
}
