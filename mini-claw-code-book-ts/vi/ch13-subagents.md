# Chương 13: Subagents

Những tác vụ phức tạp sẽ dễ xử lý hơn khi agent chính có thể uỷ quyền một phần
việc cho một child agent tập trung vào đúng một nhiệm vụ.

Nếu bạn yêu cầu một model vừa nghiên cứu, vừa thiết kế, vừa code, vừa xác minh
tất cả trong cùng một cuộc hội thoại, nó rất dễ mất tập trung. Ngữ cảnh trở nên
quá đông, model quên chi tiết ở các lượt trước, và chất lượng giảm xuống.

Subagent giải quyết việc đó bằng decomposition: parent agent spawn một child
agent cho một subtask cụ thể. Child có messages và tools riêng, chạy tới khi
xong, rồi trả về một kết quả ngắn gọn. Parent chỉ nhìn thấy phần tóm tắt cuối
cùng.

Đây là cùng một pattern được dùng trong Task tool của Claude Code và các hệ
thống agent khác khi cần chia việc thành các phần nhỏ hơn.

Trong chương này bạn sẽ xây `SubagentTool`, một `Tool` implementation dùng để
spawn các child agent ngắn hạn.

## Vì sao subagent hữu ích?

Hãy xét yêu cầu sau:

> Thêm error handling cho tất cả API endpoint.

Nếu không có subagent, parent agent có thể:

- đọc quá nhiều file
- mất dấu những gì nó đã sửa
- trộn lẫn implementation và verification trong cùng một vòng lặp dài
- tạo ra các chỉnh sửa thiếu nhất quán

Với subagent, parent có thể uỷ quyền các tác vụ tập trung:

- một child review users endpoint
- một child khác review posts endpoint
- một child thứ ba kiểm tra error shape

Parent vẫn giữ quyền kiểm soát, còn kết quả từ child thì gọn và tập trung.

## Chia sẻ provider

Parent và child nên dùng chung cấu hình provider. Trong TypeScript điều này rất
đơn giản: provider chỉ là một object reference, nên bạn có thể tái sử dụng nó
mà không phải clone bất kỳ network client nào.

Child chỉ cần:

- một tool set mới
- một message history mới

## Shape của `SubagentTool`

`SubagentTool` cần bốn phần state:

```ts
export class SubagentTool implements Tool {
  constructor(
    private readonly provider: Provider,
    private readonly toolsFactory: () => ToolSet,
  ) {}

  private systemPromptText?: string;
  private maxTurns = 10;
  private readonly definition = new ToolDefinition(
    "subagent",
    "Spawn a child agent to handle a subtask independently.",
  ).param("task", "string", "A clear description of the subtask.", true);
}
```

Ba điểm đáng chú ý là:

- provider được chia sẻ
- `toolsFactory` tạo ra một `ToolSet` mới cho mỗi child
- `maxTurns` ngăn vòng lặp chạy vô hạn

Factory quan trọng vì object tool không nên bị vô tình chia sẻ giữa các child.
Mỗi child nên nhận một tập tool sạch cho đúng phạm vi công việc của nó.

## Builder

Builder của tool này theo cùng phong cách với phần còn lại của codebase:

```ts
systemPrompt(prompt: string): this
maxTurns(value: number): this
```

Điều này giữ cho tool có tính kết hợp và cho phép caller chuyên biệt hoá hành
vi của child khi cần.

## Tool call

Phương thức `call()` làm một lượng validation nhỏ rồi chạy một agent loop bên
trong:

1. trích xuất `task`
2. tạo một tool set mới
3. tạo một message history mới
4. chạy child provider cho tới khi nó dừng hoặc chạm `maxTurns`
5. trả về văn bản cuối cùng cho parent

Child agent không chia sẻ các message trung gian của nó với parent. Chỉ câu trả
lời cuối cùng đi qua ranh giới.

Điều này rất quan trọng. Nó giữ cho cuộc hội thoại của parent gọn và ngăn nhiễu
từ child lọt vào vòng lặp chính.

### Vòng lặp child tối thiểu

Vòng lặp child cố ý giống hệt vòng lặp lõi của parent, chỉ khác là nó chạy với
một message history khác:

```ts
for (let turn = 0; turn < this.maxTurns; turn += 1) {
  const assistantTurn = await this.provider.chat(messages, definitions);
  if (assistantTurn.stopReason === "stop") {
    return assistantTurn.text ?? "";
  }

  // chạy tool call, append assistant + tool results, rồi tiếp tục
}
```

Nhờ vậy mô hình tinh thần vẫn nhỏ gọn. Subagent không phải một runtime mới. Nó
chỉ là một lần dùng khác của đúng cùng vòng lặp cốt lõi.

## Vì sao không dùng background task?

Rất dễ bị cám dỗ bởi ý tưởng spawn background task hay worker thread cho child.
Cuốn sách này không cần mức độ phức tạp đó.

Chạy child inline giúp hành vi dễ đoán:

- không cần logic huỷ riêng
- không phải quản lý join handle
- không cần message broker
- không có race condition giữa parent và child

Child chỉ đơn giản là một nested agent call.

Điều đó cũng giúp tool dễ test hơn. Child agent không phải runtime primitive
mới; nó chỉ là một nested call path mà bạn có thể kiểm thử bằng mock provider.

## Ví dụ

Parent có thể cung cấp cho child một system prompt chuyên biệt khi cần một góc
nhìn hẹp hơn:

```ts
const tool = new SubagentTool(provider, () =>
  ToolSet.from(new ReadTool(), new WriteTool(), new BashTool()),
).systemPrompt("You are a security reviewer. Focus on vulnerabilities.");
```

Như vậy parent có một cách tái sử dụng được để uỷ quyền công việc tập trung mà
không phải thay đổi vòng lặp chính.

Bạn cũng có thể giới hạn tool set của child. Với tác vụ khám phá, child có thể
chỉ cần `read` và `bash`. Với tác vụ thiên về ghi, nó có thể cần `read`,
`write`, và `bash`. Closure-based factory giữ quyết định đó ở đúng chỗ.

## Wiring it up

Parent đăng ký `SubagentTool` giống như bất kỳ tool nào khác:

```ts
const agent = new SimpleAgent(provider)
  .tool(new ReadTool())
  .tool(new WriteTool())
  .tool(new BashTool())
  .tool(
    new SubagentTool(provider, () =>
      ToolSet.from(new ReadTool(), new WriteTool(), new BashTool()),
    ),
  );
```

Parent vẫn sở hữu workflow cấp cao. Child chỉ xử lý subtask được uỷ quyền.

## Các ràng buộc quan trọng

Subagent rất hữu ích, nhưng chúng phải có kỷ luật:

- mỗi child có một tool set mới
- provider được tái sử dụng, không khởi tạo lại
- child phải có giới hạn số vòng lặp
- parent chỉ nên nhìn thấy câu trả lời cuối cùng

Những ràng buộc này làm cho delegation dễ dự đoán và giữ cho parent loop vẫn dễ
suy luận.

## Testing

Chạy test của Chương 13:

```bash
bun test mini-claw-code-starter-ts/tests/ch13.test.ts
```

Các test xác minh:

- child trả về text trực tiếp
- child có thể dùng tool trước khi trả lời
- hội thoại nhiều bước của child hoạt động đúng
- giới hạn số vòng lặp được áp dụng
- task bị thiếu bị từ chối
- lỗi provider được truyền ra ngoài

Những trường hợp này bao phủ happy path và các failure mode chính. Nếu child
làm rò rỉ message nội bộ hoặc chạy mãi không dừng, parent agent sẽ trở nên khó
tin cậy hơn rất nhiều.

## Recap

- Subagent chia tác vụ lớn thành các cuộc hội thoại child tập trung.
- Parent chỉ nhìn thấy câu trả lời cuối cùng của child.
- Tool set mới giúp giữ phạm vi của child sạch sẽ.
- Giới hạn số vòng lặp giữ cho nested loop không vượt kiểm soát.
- Trong TypeScript, việc tái sử dụng provider rất đơn giản vì object reference
  được chia sẻ.
- Một child agent vẫn chỉ là cùng vòng lặp cốt lõi đó, lồng thêm một tầng.
- Parent đơn giản hơn vì child sở hữu subtask tập trung.
- Delegation là một ranh giới kiến trúc, không phải runtime primitive mới.
