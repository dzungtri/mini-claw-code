import { describe, expect, test } from "bun:test";
import { MockProvider } from "../mock";
import { MockStreamProvider, StreamAccumulator, parseSseLine, StreamingAgent } from "../streaming";
import { ReadTool } from "../tools";

describe("streaming", () => {
  test("parseSseLine parses text deltas", () => {
    const events = parseSseLine(
      'data: {"choices":[{"delta":{"content":"hello"}}]}',
    );
    expect(events).toEqual([{ kind: "text_delta", text: "hello" }]);
  });

  test("StreamAccumulator builds an AssistantTurn", () => {
    const accumulator = new StreamAccumulator();
    accumulator.feed({ kind: "text_delta", text: "hello" });
    expect(accumulator.finish()).toMatchObject({
      text: "hello",
      stopReason: "stop",
      toolCalls: [],
    });
  });

  test("StreamingAgent forwards text deltas", async () => {
    const provider = new MockStreamProvider(
      new MockProvider([{ text: "hello", toolCalls: [], stopReason: "stop" }]),
    );
    const agent = new StreamingAgent(provider);
    let text = "";
    await agent.run("hi", async (event) => {
      if (event.kind === "text_delta") {
        text += event.text;
      }
    });
    expect(text).toBe("hello");
  });
});
