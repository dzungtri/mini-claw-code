# Chương 7: Một CLI Đơn Giản

Bây giờ bạn đã có tất cả các thành phần quan trọng: một mock provider cho test,
bốn tool, agent loop, và một HTTP provider. Giờ là lúc nối chúng lại thành một
trợ lý dòng lệnh hoạt động thật sự.

Đây là chương mà dự án ngừng trông như những mảnh rời rạc và bắt đầu giống một
agent thật.

## Mục tiêu

Triển khai `chat()` trong `mini-claw-code-starter-ts/src/agent.ts` và hoàn tất
`mini-claw-code-starter-ts/examples/chat.ts` sao cho:

1. Agent nhớ được hội thoại qua nhiều prompt.
2. CLI in prompt, đọc một dòng, chạy agent và in kết quả.
3. Có chỉ báo `thinking...` trong lúc agent đang làm việc.
4. Chương trình chạy liên tục cho đến khi người dùng thoát hoặc gửi EOF.

## Method `chat()`

Mở [`mini-claw-code-starter-ts/src/agent.ts`](/Users/dzung/mini-claw-code/mini-claw-code-starter-ts/src/agent.ts).
Bạn đã có khung `SimpleAgent` và method `run()` từ Chapter 5. Chapter 7 thêm
vào một method mới:

```ts
async chat(messages: Message[]): Promise<string>
```

### Vì sao cần method mới?

`run()` luôn bắt đầu từ một prompt mới. Điều đó rất tiện cho test, nhưng CLI
cần nhớ hội thoại. Nếu người dùng hỏi:

1. "Show me the files in this repo"
2. "Now open the package file"

thì prompt thứ hai phải nhìn thấy toàn bộ trao đổi trước đó.

`chat()` giải quyết điều đó bằng cách nhận lịch sử message từ caller. Caller
giữ array đó, push message mới vào, rồi dùng lại chính array đó ở turn tiếp
theo.

Trong TypeScript, shape này đơn giản hơn Rust:

- không có chuyện move ownership
- bạn mutate cùng một `Message[]`
- lịch sử hội thoại luôn rõ ràng và dễ đọc

Đó là tương đương của phần bàn luận ownership trong chương Rust.

### Cách triển khai

Phần loop bên trong giống hệt `run()`:

1. Collect tool definitions.
2. Gọi `provider.chat(messages, definitions)`.
3. Nếu `stopReason === "stop"`, trả về text.
4. Nếu `stopReason === "tool_use"`, execute tools.
5. Push assistant turn và tool results vào history.
6. Lặp lại.

Điểm quan trọng là `chat()` phải append assistant turn vào đúng array mà
caller đưa vào. Như vậy prompt kế tiếp vẫn thấy toàn bộ hội thoại.

Trong starter package, implementation này vẫn cố ý để TODO, nhưng solution
package đi theo shape sau:

```ts
async chat(messages: Message[]): Promise<string> {
  const definitions = this.tools.definitions();

  for (;;) {
    const turn = await this.provider.chat(messages, definitions);

    if (turn.stopReason === "stop") {
      const text = turn.text ?? "";
      messages.push({ kind: "assistant", turn });
      return text;
    }

    const results = await this.executeTools(turn);
    messages.push({ kind: "assistant", turn });
    for (const result of results) {
      messages.push({ kind: "tool_result", id: result.id, content: result.content });
    }
  }
}
```

Nhánh `tool_use` vẫn là pattern từ Chapter 5: execute từng tool, bắt lỗi nếu
có, rồi feed kết quả tool trở lại conversation.

## CLI

Mở [`mini-claw-code-starter-ts/examples/chat.ts`](/Users/dzung/mini-claw-code/mini-claw-code-starter-ts/examples/chat.ts).
File này là shell người dùng nhìn thấy bọc quanh agent loop.

### Bước 1: Imports

CLI cần bốn thứ:

- provider
- agent
- các tool
- kiểu message

Starter example đã import chúng từ `../src`:

```ts
import {
  BashTool,
  EditTool,
  OpenAICompatibleProvider,
  ReadTool,
  SimpleAgent,
  WriteTool,
  type Message,
} from "../src";
```

### Bước 2: Tạo provider và agent

CLI yêu cầu provider lấy credential từ environment:

```ts
const provider = OpenAICompatibleProvider.fromEnv();
const agent = SimpleAgent.new(provider)
  .tool(BashTool.new())
  .tool(ReadTool.new())
  .tool(WriteTool.new())
  .tool(EditTool.new());
```

Đó chính là builder pattern bạn đã dùng suốt trong bản Rust:

- tạo provider
- đăng ký tool
- giữ agent bản thân nó thật nhỏ

### Bước 3: System prompt và history

Người dùng cần một instruction ổn định ở đầu hội thoại. Starter CLI giữ nó
đơn giản và viết thẳng:

```ts
const history: Message[] = [
  {
    kind: "system",
    text: `You are a coding agent working in ${process.cwd()}.`,
  },
];
```

System message đặt vai trò cho agent và cho biết working directory hiện tại.
Điều đó giúp giải thích các đường dẫn trong tool call sau này dễ hơn.

Mảng `history` nằm ngoài vòng REPL. Chính điều đó tạo ra bộ nhớ qua nhiều turn.

### Bước 4: Vòng REPL

Starter TypeScript dùng `readline/promises` để đọc prompt:

```ts
import readline from "node:readline/promises";
import { stdin as input, stdout as output } from "node:process";

const rl = readline.createInterface({ input, output });
```

Vòng lặp khá thẳng:

1. Đọc một dòng.
2. Bỏ qua input rỗng.
3. Thoát nếu là `/exit`.
4. Push user message vào `history`.
5. Gọi `agent.chat(history)`.
6. In câu trả lời.

Code thực tế trông như sau:

```ts
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
```

Call `history.push(...)` diễn ra trước `agent.chat(...)`, nên model thấy
prompt mới như một phần của conversation.

### Bước 5: Giữ tính tương tác

CLI nên tạo cảm giác đang hoạt động, không bị đứng im. Bản Rust in
`thinking...` rồi xóa nó khi có câu trả lời. Ý tưởng đó cũng áp dụng ở đây.

Trong TypeScript, `process.stdout.write()` thường là cách dễ nhất để tránh
thêm newline ngoài ý muốn và kiểm soát con trỏ.

### Vì sao history nằm ngoài agent

Đây là một ranh giới thiết kế, không phải một sự tiện tay ngẫu nhiên.

- Agent nên sở hữu orchestration.
- CLI nên sở hữu interaction.
- Mảng `history` nên nằm ở nơi quyết định khi nào hội thoại được reset.

Điều đó làm code dễ hiểu và dễ test hơn. Cùng một agent có thể được dùng lại
trong script, REPL, và sau này là TUI.

### Vì sao nó vẫn giống một coding assistant

CLI này có ba chi tiết nhỏ nhưng rất quan trọng:

1. Prompt ngắn và quen thuộc.
2. Câu trả lời của assistant được append vào cùng một conversation.
3. Người dùng có thể tiếp tục nói chuyện mà không phải load lại trạng thái.

Kết hợp đó làm cho chương trình terminal có cảm giác như một trợ lý, thay vì
chỉ là một script một lần.

### Ví dụ trong repository

Starter example dùng cùng cấu trúc như solution package:

```ts
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
```

## Chạy test

Chạy test của Chapter 7:

```bash
bun test mini-claw-code-starter-ts/tests/ch7.test.ts
```

Những test này kiểm tra:

- history được giữ qua nhiều turn
- `chat()` append assistant turn vào đúng array
- CLI loop vẫn còn đơn giản và có thể lặp tiếp

## Tóm tắt

- `chat()` là phiên bản giữ lịch sử hội thoại của `run()`.
- CLI nên giữ history ở bên ngoài agent.
- Prompt, agent, và tool registration đi cùng nhau rất tự nhiên trong TypeScript.
- Chapter 7 là lúc agent bắt đầu trông và hoạt động như một trợ lý thật sự.
