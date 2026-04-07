# Chương 12: Plan Mode

Các coding agent thực tế có thể rất nguy hiểm nếu chúng được phép ghi file ngay
lập tức. Chỉ cần cho model quyền `write`, `edit`, và `bash`, nó có thể thay
đổi repo của bạn trước khi con người kịp xem hướng tiếp cận của nó.

Plan mode giải quyết điều đó bằng cách tách workflow thành hai pha:

1. lập kế hoạch với các tool chỉ-đọc
2. thực thi sau khi được phê duyệt

Đây chính là ý tưởng đằng sau plan mode của Claude Code và approval workflow
của OpenCode. Trong chương này bạn sẽ xây `PlanAgent`, một streaming agent với
cơ chế phê duyệt do caller điều khiển.

## Vì sao plan mode tồn tại?

Hãy xét yêu cầu sau:

> Refactor lớp auth để dùng JWT thay cho session cookie.

Nếu không có plan mode, model có thể lập tức bắt đầu sửa code. Đó là mặc định
tệ vì thường có nhiều hướng tiếp cận hợp lý:

- thay trực tiếp session store
- thêm một compatibility layer
- chia công việc thành nhiều file
- hỏi thêm một câu trước khi sửa

Plan mode buộc model phải khám phá trước và giải thích ý định của nó trước khi
chạm vào filesystem.

## Thiết kế

`PlanAgent` có shape tổng quát giống `StreamingAgent`: một provider, một
`ToolSet`, và một vòng lặp. Các phần bổ sung làm cho nó an toàn hơn:

```ts
export class PlanAgent {
  constructor(
    private readonly provider: StreamProvider,
    private readonly tools = new ToolSet(),
  ) {
    this.readOnly = new Set(["bash", "read", "ask_user"]);
    this.planPromptText = DEFAULT_PLAN_PROMPT_TEMPLATE;
    this.exitPlanDefinition = new ToolDefinition(
      "exit_plan",
      "Signal that your plan is complete and ready for user review.",
    );
  }

  readOnly: Set<string>;
  planPromptText: string;
  exitPlanDefinition: ToolDefinition;

  plan(messages: Message[], onEvent?: AgentEventHandler): Promise<string> {}
  execute(messages: Message[], onEvent?: AgentEventHandler): Promise<string> {}
}
```

Ba thành phần quan trọng là:

- một tập tên tool được phép trong giai đoạn planning
- một system prompt nói cho model biết nó đang ở planning mode
- một `exit_plan` tool definition để model gọi khi kế hoạch đã sẵn sàng

## Builder

Các builder method theo cùng phong cách với `SimpleAgent` và `StreamingAgent`:

```ts
planPrompt(prompt: string): this
readOnlyTools(names: string[]): this
tool(tool: Tool): this
```

Mặc định được giữ chặt:

- `bash`
- `read`
- `ask_user`

Chúng đủ để khám phá và làm rõ yêu cầu, nhưng không đủ để sửa codebase.

## Planning prompt

Model cần biết nó đang ở planning mode. Nếu không có instruction này, nó sẽ cố
hoàn thành task bằng bất kỳ tool nào nó nhìn thấy.

Planning prompt nên nói rõ:

- bạn đang ở planning mode
- bạn có thể inspect codebase
- bạn có thể hỏi người dùng
- bạn không được write, edit, hay create file
- khi kế hoạch sẵn sàng, hãy gọi `exit_plan`

Prompt này chỉ được inject nếu cuộc hội thoại chưa bắt đầu bằng một system
message. Điều đó cho phép caller cung cấp prompt riêng nếu cần.

## Tool `exit_plan`

`exit_plan` là một tín hiệu tường minh từ model. Nó rõ ràng hơn việc chỉ dựa
vào `stopReason === "stop"`, vì một trạng thái dừng có thể có nhiều nghĩa:

- model đã lập kế hoạch xong
- model hết token
- model bị khựng

`exit_plan` có nghĩa là: "kế hoạch đã sẵn sàng để review."

Trong implementation TypeScript, `exit_plan` là một `ToolDefinition` được lưu
trên agent, chứ không phải tool đăng ký bình thường. Điều đó cho phép
`plan()` expose nó, còn `execute()` thì không.

## Vòng lặp dùng chung

`PlanAgent` giữ một vòng lặp và hai mode. Đó là lựa chọn kiến trúc quan trọng.

Vòng lặp vẫn làm các bước quen thuộc:

1. hỏi provider cho lượt tiếp theo
2. kiểm tra `stopReason`
3. chạy tool call nếu cần
4. append assistant và tool-result message
5. lặp lại cho tới khi model dừng hoặc thoát khỏi planning

Chỉ có bộ lọc tool thay đổi giữa hai pha. Mọi thứ khác giữ nguyên.

Đây cũng là thủ thuật dùng trong bản Rust: lõi vòng lặp giữ ổn định, còn ranh
giới an toàn được biểu diễn bằng danh sách tool và một điều kiện thoát bổ sung.

## Vòng lặp dùng chung trên thực tế

Private loop có thể mô tả ngắn gọn như sau:

```ts
const definitions =
  allowed === undefined
    ? this.tools.definitions()
    : [
        ...this.tools
          .definitions()
          .filter((definition) => allowed.has(definition.name)),
        this.exitPlanDefinition,
      ];

for (;;) {
  const turn = await this.provider.streamChat(messages, definitions, onStream);

  if (turn.stopReason === "stop") {
    messages.push(assistantMessage(turn));
    return turn.text ?? "";
  }

  // xử lý exit_plan và các tool bị chặn
}
```

Chỉ có hai yếu tố chuyển động:

- tool nào được model nhìn thấy
- liệu `exit_plan` có được gọi hay không

Mọi phần còn lại chỉ là giao thức agent bình thường mà sách đã giới thiệu.

## Phòng thủ hai lớp

Plan mode dùng hai lớp bảo vệ.

### Lớp 1: Lọc definition

Trong planning, chỉ các tool chỉ-đọc cùng với `exit_plan` mới được gửi tới
provider. Model hoàn toàn không nhìn thấy `write` hay `edit`.

Điều đó nghĩa là các lựa chọn mà model có thể cân nhắc đã bị giới hạn ngay từ
trước khi nó ra quyết định.

### Lớp 2: Chốt chặn ở lúc thực thi

Execution guard kiểm tra từng tool call trước khi chạy nó. Nếu model bằng cách
nào đó hallucinate một tool bị chặn, agent sẽ trả về một chuỗi lỗi thay vì
thực thi lệnh đó.

Điều này giữ cho model được thông tin đầy đủ và filesystem vẫn an toàn.

Nó quan trọng vì model đôi khi vẫn có thể bịa ra tên tool bị chặn hoặc nhớ lại
tên tool từ các lượt trước. Guard biến sai lầm đó thành kết quả có thể phục
hồi thay vì thành một thay đổi trên filesystem.

## Approval do caller điều khiển

`PlanAgent` không tự hỏi xin phê duyệt. Caller mới là bên sở hữu flow đó.

Điều này giúp agent chỉ tập trung vào orchestration và để UI quyết định cách
trình bày kế hoạch:

- prompt trong CLI
- màn hình xác nhận trong TUI
- một giao diện web approval

Điểm quan trọng là cùng một mảng `messages` được tái sử dụng giữa các pha, để
model nhìn thấy chính kế hoạch của nó và phản hồi của người dùng khi bước vào
giai đoạn execute.

Nếu người dùng muốn sửa lại kế hoạch, caller chỉ cần append feedback như một
`User` message rồi gọi `plan()` lại. Nhờ vậy ngữ cảnh của model được liên tục.

## Ví dụ về approval do caller điều khiển

Caller sở hữu UI phê duyệt. Agent chỉ tạo kế hoạch và thực thi khi được yêu
cầu:

```ts
const messages: Message[] = [userMessage("Refactor auth.ts")];

const plan = await agent.plan(messages, onEvent);
console.log("Plan:", plan);

if (userApproves(plan)) {
  messages.push(userMessage("Approved. Execute the plan."));
  const result = await agent.execute(messages, onEvent);
  console.log(result);
} else {
  messages.push(userMessage("Try a different approach."));
  const revisedPlan = await agent.plan(messages, onEvent);
  console.log("Revised plan:", revisedPlan);
}
```

Đây chính là workflow mà các agent thực tế cần: khám phá trước, hỏi lại nếu
cần, rồi chỉ mutate sau khi con người đồng ý.

## Wiring it up

Planning agent dùng cùng các tool như agent bình thường, nhưng chỉ tập read-only
được mở trong plan mode. Các ví dụ và test ở bản TS dùng cùng pattern:

```ts
const agent = new PlanAgent(provider)
  .planPrompt(planPrompt)
  .tool(new BashTool())
  .tool(new ReadTool())
  .tool(new WriteTool())
  .tool(new EditTool())
  .tool(new AskTool(handler));
```

Caller quyết định khi nào gọi `plan()` và khi nào gọi `execute()`.

## Testing

Chạy test của Chương 12:

```bash
bun test mini-claw-code-starter-ts/tests/ch12.test.ts
```

Các test xác minh:

- planning prompt được inject khi cần
- tập tool read-only được áp dụng đúng
- `exit_plan` kết thúc giai đoạn planning
- giai đoạn execute có thể chạy với toàn bộ tool set

## Recap

- Plan mode tách quá trình khám phá khỏi quá trình thay đổi.
- Model chỉ nhìn thấy các tool an toàn trong giai đoạn planning.
- `exit_plan` cho model một cách tường minh để bàn giao kế hoạch.
- Caller sở hữu approval flow và quyết định khi nào execution bắt đầu.
