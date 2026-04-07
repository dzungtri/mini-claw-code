export type JsonValue =
  | string
  | number
  | boolean
  | null
  | JsonValue[]
  | { [key: string]: JsonValue };

export type JsonSchema = {
  type: "object";
  properties: Record<string, JsonValue>;
  required: string[];
};

export class ToolDefinition {
  readonly parameters: JsonSchema;

  constructor(
    readonly name: string,
    readonly description: string,
    parameters?: JsonSchema,
  ) {
    this.parameters = parameters ?? {
      type: "object",
      properties: {},
      required: [],
    };
  }

  static new(name: string, description: string): ToolDefinition {
    return new ToolDefinition(name, description);
  }

  param(
    name: string,
    type: string,
    description: string,
    required: boolean,
  ): ToolDefinition {
    this.parameters.properties[name] = {
      type,
      description,
    };
    if (required) {
      this.parameters.required.push(name);
    }
    return this;
  }
}

export interface ToolCall {
  id: string;
  name: string;
  arguments: JsonValue;
}

export type StopReason = "stop" | "tool_use";

export interface AssistantTurn {
  text: string | null;
  toolCalls: ToolCall[];
  stopReason: StopReason;
}

export type Message =
  | { kind: "system"; text: string }
  | { kind: "user"; text: string }
  | { kind: "assistant"; turn: AssistantTurn }
  | { kind: "tool_result"; id: string; content: string };

export interface Tool {
  definition(): ToolDefinition;
  call(args: JsonValue): Promise<string>;
}

export class ToolSet {
  readonly tools = new Map<string, Tool>();

  static new(): ToolSet {
    return new ToolSet();
  }

  with(tool: Tool): ToolSet {
    this.push(tool);
    return this;
  }

  push(tool: Tool): void {
    this.tools.set(tool.definition().name, tool);
  }

  get(name: string): Tool | undefined {
    return this.tools.get(name);
  }

  definitions(): ToolDefinition[] {
    return [...this.tools.values()].map((tool) => tool.definition());
  }
}

export interface Provider {
  chat(messages: Message[], tools: ToolDefinition[]): Promise<AssistantTurn>;
}
