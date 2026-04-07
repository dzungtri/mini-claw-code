# Chương 11: Nhập liệu từ người dùng

Agent của bạn có thể đọc file, chạy lệnh và chỉnh sửa code, nhưng nó không thể
hỏi người dùng một câu hỏi trừ khi bạn cung cấp cho nó một tool cho việc đó.
Nếu không có nhập liệu từ người dùng, model sẽ phải đoán khi tên file không rõ
ràng, khi có nhiều lựa chọn hợp lý, hoặc khi một thao tác phá huỷ cần được xác
nhận.

Các coding agent thực tế giải quyết việc này bằng một ask tool. LLM gọi một
tool đặc biệt, agent tạm dừng, người dùng trả lời, rồi câu trả lời được đưa
trở lại vòng lặp dưới dạng tool result.

Trong chương này bạn sẽ xây dựng:

1. Một interface `InputHandler` để trừu tượng hoá cách thu thập nhập liệu.
2. Một `AskTool` để LLM dùng khi cần hỏi người dùng.
3. Ba implementation handler: CLI, cầu nối TUI, và mock.

## Vì sao cần một interface handler?

Các frontend khác nhau thu thập nhập liệu theo những cách khác nhau:

- Ứng dụng CLI in câu hỏi ra stdout và đọc từ stdin.
- TUI thường phải chuyển câu hỏi sang event loop của giao diện.
- Test cần các câu trả lời dựng sẵn mà không có I/O thật.

`InputHandler` giữ cho `AskTool` độc lập với frontend:

```ts
export interface InputHandler {
  ask(question: string, options: string[]): Promise<string>;
}
```

`question` là văn bản do model tạo ra. `options` là danh sách tuỳ chọn không
bắt buộc. Nếu mảng rỗng, người dùng nhập tự do. Nếu không rỗng, UI có thể hiển
thị danh sách lựa chọn.

Đây là cùng một ý tưởng như trong chương Rust: tool không nên biết câu trả lời
đến từ terminal, từ event loop, hay từ test stub.

## AskTool

`AskTool` là cầu nối giữa model và con người. Nó công khai một tool có tên
`ask_user`, nhận một `question` bắt buộc, và một mảng `options` không bắt buộc.

Bản TypeScript dùng cùng ý tưởng schema như bản Rust, nhưng kiểu dữ liệu gọn
hơn:

```ts
export class AskTool implements Tool {
  constructor(private readonly handler: InputHandler) {}

  definition(): ToolDefinition {
    return new ToolDefinition(
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
  }
}
```

Tham số `question` là bắt buộc. Tham số `options` là tuỳ chọn và dùng
`paramRaw()` vì mảng biểu diễn được cấu trúc phong phú hơn builder scalar đơn
giản.

### Luồng gọi tool

Phương thức `call()` làm ba việc:

1. Xác thực rằng `question` là một chuỗi.
2. Phân tích mảng `options` tuỳ chọn thành `string[]`.
3. Uỷ quyền cho `InputHandler` đã được inject.

Nhờ vậy tool chỉ tập trung vào contract thay vì chi tiết UI.

```ts
async call(args: JsonValue): Promise<string> {
  const question = (args as { question?: unknown }).question;
  if (typeof question !== "string") {
    throw new Error("missing required parameter: question");
  }

  const options =
    Array.isArray((args as { options?: unknown }).options)
      ? (args as { options: unknown[] }).options.filter(
          (value): value is string => typeof value === "string",
        )
      : [];

  return await this.handler.ask(question, options);
}
```

Điểm quan trọng không phải là cú pháp chính xác, mà là việc model giờ đây có
thể tạm dừng vòng lặp và hỏi con người khi thiếu thông tin.

## CliInputHandler

Handler đơn giản nhất là in câu hỏi ra và chờ stdin. Với Bun, bạn có thể làm
điều đó bằng `readline/promises` hoặc một wrapper nhỏ quanh standard input.
Implementation trong `mini-claw-code-ts/src/tools/ask.ts` dùng luồng hỏi/đáp
trực tiếp và giải các lựa chọn đánh số khi người dùng nhập `1`, `2`, v.v.

Hành vi quan trọng là:

- hiển thị câu hỏi
- liệt kê các lựa chọn nếu có
- cho phép nhập tự do nếu không có lựa chọn
- chuyển câu trả lời dạng số thành tuỳ chọn tương ứng

Điều đó giúp bản CLI dùng tốt cho cả câu hỏi mở và prompt xác nhận.

## ChannelInputHandler

Bản TUI cần chuyển yêu cầu nhập liệu ra event loop bên ngoài. Trong sách Rust,
điều này dùng channel và oneshot response. Trong TypeScript, cùng một ý tưởng
được biểu diễn thành một cầu nối callback request/response.

Shape vẫn tương tự:

```ts
export interface UserInputRequest {
  question: string;
  options: string[];
}

export class ChannelInputHandler implements InputHandler {
  constructor(
    private readonly dispatch: (request: UserInputRequest) => Promise<string>,
  ) {}

  ask(question: string, options: string[]): Promise<string> {
    return this.dispatch({ question, options });
  }
}
```

Tool không quan tâm câu trả lời được render như thế nào. Nó chỉ quan tâm việc
event loop của TUI cuối cùng trả về một chuỗi.

Đây là abstraction cốt lõi: agent hỏi, UI quyết định cách hiển thị, và câu trả
lời quay về dưới dạng plain text.

## MockInputHandler

Đối với test, một fake input handler giúp chương học có tính quyết định:

```ts
export class MockInputHandler implements InputHandler {
  constructor(answers: Iterable<string>) {
    this.answers = [...answers];
  }

  async ask(_question: string, _options: string[]): Promise<string> {
    const answer = this.answers[this.cursor];
    if (answer === undefined) {
      throw new Error("MockInputHandler: no more answers");
    }
    this.cursor += 1;
    return answer;
  }
}
```

Điều này cho phép bạn test việc đặt câu hỏi, chọn option, và hành vi khi hết
câu trả lời mà không cần tương tác terminal thật.

## Chi tiết implementation

Chương Rust dành khá nhiều thời gian cho các helper nhỏ vì chúng giúp tool dễ
lý giải hơn. Bản TypeScript cũng nên như vậy.

### Giải lựa chọn

Khi người dùng nhập `1`, `2`, hoặc `3`, CLI nên map con số đó trở lại lựa chọn
tương ứng. Nếu input không phải số hợp lệ, dùng nguyên văn text.

```ts
function resolveOption(answer: string, options: string[]): string {
  const asNumber = Number(answer);
  if (Number.isInteger(asNumber) && asNumber >= 1 && asNumber <= options.length) {
    return options[asNumber - 1]!;
  }
  return answer;
}
```

Helper này giúp bản CLI dùng tốt cho cả câu trả lời mở và prompt xác nhận.

### Ranh giới của CLI

CLI handler nên giữ ranh giới I/O thật nhỏ:

1. render câu hỏi
2. liệt kê các lựa chọn nếu có
3. đọc một dòng từ stdin
4. giải lựa chọn được đánh số

Như vậy code hướng người dùng được tách khỏi logic agent.

### Cầu nối TUI

TUI không nên hỏi trực tiếp từ trong tool. Nó nên đẩy request ra ngoài và để
event loop render theo phong cách nó muốn.

Đó là lý do `ChannelInputHandler` chỉ là một adapter mỏng quanh một hàm
dispatch. Request object chứa câu hỏi và danh sách lựa chọn, còn UI event loop
quyết định hiển thị ra sao.

### Câu trả lời mock

Mock handler nên dùng một queue câu trả lời đơn giản. Điều đó cho test một
cách deterministic để xác minh:

- câu trả lời text tự do
- lựa chọn option
- nhiều câu hỏi liên tiếp
- lỗi khi queue cạn

Mục tiêu là giữ cho chương này test được mà không cần I/O terminal thật.

## Tool summary

Logic tool summary từ agent loop trở nên hữu ích hơn nhiều khi `ask_user` xuất
hiện. Khi agent hỏi con người một câu hỏi, UI có thể hiển thị summary đó y như
một tool call summary thông thường.

Nói cách khác: `AskTool` không phải trường hợp đặc biệt. Nó chỉ là một tool nữa
trả về string result, và agent loop xử lý nó giống như `read` hay `bash`.

## Tích hợp với plan mode

`ask_user` đặc biệt có giá trị trong plan mode. Khi model đang khám phá một
thay đổi, nó có thể cần hỏi:

- file nào mới là mục tiêu đúng
- có được phép rewrite hay không
- trong vài hướng tiếp cận khác nhau, người dùng muốn hướng nào

Đó là lý do `ask_user` thuộc về tập tool read-only trong giai đoạn planning.

## Wiring it up

Export các type và tool từ `mini-claw-code-ts/src/tools/index.ts`, rồi đăng ký
`AskTool` trong bất kỳ agent nào cần tương tác với người dùng.

```ts
const agent = new SimpleAgent(provider)
  .tool(new BashTool())
  .tool(new ReadTool())
  .tool(new WriteTool())
  .tool(new EditTool())
  .tool(new AskTool(new CliInputHandler()));
```

Tool này cũng hoạt động với planning agent và TUI. Chỉ có handler là thay đổi.

## Testing

Chạy test của Chương 11:

```bash
bun test mini-claw-code-starter-ts/tests/ch11.test.ts
```

Các test xác minh:

- tool definition expose `question` và `options` tuỳ chọn
- CLI handler giải option number đúng
- mock handler trả về câu trả lời dựng sẵn
- ask tool thực sự delegate sang handler

## Recap

- `InputHandler` giữ tool độc lập với frontend.
- `AskTool` cho phép model hỏi con người thay vì đoán.
- `CliInputHandler`, `ChannelInputHandler`, và `MockInputHandler` bao phủ ba
  môi trường runtime chính.
- `ask_user` là một tool bình thường, nên agent loop không cần nhánh đặc biệt
  cho nhập liệu của con người.
