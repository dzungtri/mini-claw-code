export type JsonPrimitive = string | number | boolean | null;
export type JsonValue = JsonPrimitive | JsonObject | JsonValue[];
export type JsonObject = { [key: string]: JsonValue };

export type StopReason = "stop" | "tool_use";

export interface ToolCall {
  id: string;
  name: string;
  arguments: JsonValue;
}

export interface AssistantTurn {
  text?: string | undefined;
  toolCalls: ToolCall[];
  stopReason: StopReason;
}

export type Message =
  | { kind: "system"; text: string }
  | { kind: "user"; text: string }
  | { kind: "assistant"; turn: AssistantTurn }
  | { kind: "tool_result"; id: string; content: string };

export class ToolDefinition {
  readonly name: string;
  readonly description: string;
  readonly parameters: JsonObject;

  constructor(name: string, description: string, parameters?: JsonObject) {
    this.name = name;
    this.description = description;
    this.parameters =
      parameters ??
      ({
        type: "object",
        properties: {},
        required: [],
      } satisfies JsonObject);
  }

  param(name: string, type: string, description: string, required: boolean): this {
    const properties = this.ensureProperties();
    properties[name] = {
      type,
      description,
    };

    if (required) {
      this.ensureRequired().push(name);
    }

    return this;
  }

  paramRaw(name: string, schema: JsonValue, required: boolean): this {
    const properties = this.ensureProperties();
    properties[name] = schema;

    if (required) {
      this.ensureRequired().push(name);
    }

    return this;
  }

  private ensureProperties(): JsonObject {
    const properties = this.parameters.properties;
    if (properties && typeof properties === "object" && !Array.isArray(properties)) {
      return properties as JsonObject;
    }

    const next: JsonObject = {};
    this.parameters.properties = next;
    return next;
  }

  private ensureRequired(): string[] {
    const required = this.parameters.required;
    if (Array.isArray(required)) {
      return required.filter((value): value is string => typeof value === "string");
    }

    const next: string[] = [];
    this.parameters.required = next;
    return next;
  }
}

export interface Tool {
  definition(): ToolDefinition;
  call(args: JsonValue): Promise<string>;
}

export class ToolSet {
  #tools = new Map<string, Tool>();

  static from(...tools: Tool[]): ToolSet {
    const set = new ToolSet();
    for (const tool of tools) {
      set.push(tool);
    }
    return set;
  }

  with(tool: Tool): this {
    this.push(tool);
    return this;
  }

  push(tool: Tool): void {
    this.#tools.set(tool.definition().name, tool);
  }

  get(name: string): Tool | undefined {
    return this.#tools.get(name);
  }

  definitions(): ToolDefinition[] {
    return [...this.#tools.values()].map((tool) => tool.definition());
  }
}

export interface Provider {
  chat(messages: Message[], tools: ToolDefinition[]): Promise<AssistantTurn>;
}

export function systemMessage(text: string): Message {
  return { kind: "system", text };
}

export function userMessage(text: string): Message {
  return { kind: "user", text };
}

export function assistantMessage(turn: AssistantTurn): Message {
  return { kind: "assistant", turn };
}

export function toolResultMessage(id: string, content: string): Message {
  return { kind: "tool_result", id, content };
}
