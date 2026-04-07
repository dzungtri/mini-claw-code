import { createInterface } from "node:readline/promises";
import { stdin as input, stdout as output } from "node:process";
import { ToolDefinition, type JsonObject, type Tool } from "../types";

export interface InputHandler {
  ask(question: string, options: string[]): Promise<string>;
}

export interface UserInputRequest {
  question: string;
  options: string[];
}

export class AskTool implements Tool {
  readonly #handler: InputHandler;
  readonly #definition = new ToolDefinition(
    "ask_user",
    "Ask the user a clarifying question before proceeding.",
  )
    .param("question", "string", "The question to ask the user", true)
    .paramRaw(
      "options",
      {
        type: "array",
        items: { type: "string" },
        description: "Optional list of choices to present to the user",
      },
      false,
    );

  constructor(handler: InputHandler) {
    this.#handler = handler;
  }

  definition(): ToolDefinition {
    return this.#definition;
  }

  async call(args: JsonObject | null): Promise<string> {
    const question = args?.question;
    if (typeof question !== "string") {
      throw new Error("missing required parameter: question");
    }

    const options = Array.isArray(args?.options)
      ? args.options.filter((option): option is string => typeof option === "string")
      : [];

    return this.#handler.ask(question, options);
  }
}

export class CliInputHandler implements InputHandler {
  async ask(question: string, options: string[]): Promise<string> {
    const rl = createInterface({ input, output });
    try {
      const renderedOptions =
        options.length === 0
          ? ""
          : `\n${options.map((option, index) => `  ${index + 1}) ${option}`).join("\n")}`;
      const answer = await rl.question(`\n${question}${renderedOptions}\n> `);
      return resolveOption(answer.trim(), options);
    } finally {
      rl.close();
    }
  }
}

export class ChannelInputHandler implements InputHandler {
  readonly #dispatch: (request: UserInputRequest) => Promise<string>;

  constructor(dispatch: (request: UserInputRequest) => Promise<string>) {
    this.#dispatch = dispatch;
  }

  ask(question: string, options: string[]): Promise<string> {
    return this.#dispatch({ question, options });
  }
}

export class MockInputHandler implements InputHandler {
  readonly #answers: string[];
  #cursor = 0;

  constructor(answers: Iterable<string>) {
    this.#answers = [...answers];
  }

  async ask(_question: string, _options: string[]): Promise<string> {
    const answer = this.#answers[this.#cursor];
    if (answer === undefined) {
      throw new Error("MockInputHandler: no more answers");
    }
    this.#cursor += 1;
    return answer;
  }
}

function resolveOption(answer: string, options: string[]): string {
  const asNumber = Number(answer);
  if (Number.isInteger(asNumber) && asNumber >= 1 && asNumber <= options.length) {
    return options[asNumber - 1]!;
  }
  return answer;
}
