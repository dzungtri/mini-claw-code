# Chương 11: Nhập liệu từ người dùng

Agent của bạn có thể đọc file, chạy lệnh và ghi code, nhưng nó chưa thể hỏi
*bạn* một câu nào. Khi không chắc nên chọn hướng tiếp cận nào, nên sửa file
nào, hay có nên tiếp tục với một thao tác mang tính phá hủy hay không, nó chỉ
biết đoán.

Các coding agent thực tế giải quyết việc này bằng một **ask tool**. Claude Code
có `AskUserQuestion`, Kimi CLI có approval prompt. LLM gọi một tool đặc biệt,
agent tạm dừng, rồi người dùng nhập câu trả lời. Câu trả lời đó được đưa ngược
lại thành tool result và quá trình thực thi tiếp tục.

Trong chương này bạn sẽ xây dựng:

1. Một trait **`InputHandler`** để trừu tượng hóa cách thu thập input từ người dùng.
2. Một **`AskTool`** để LLM dùng khi cần đặt câu hỏi cho người dùng.
3. Ba implementation của handler: CLI, channel-based (cho TUI) và mock (cho test).

## Tại sao cần trait?

Mỗi kiểu UI thu thập input theo một cách khác nhau:

- Ứng dụng **CLI** in ra stdout và đọc từ stdin.
- Ứng dụng **TUI** gửi request qua channel rồi chờ event loop thu câu trả lời
  (có thể kèm điều hướng bằng phím mũi tên).
- **Test** cần cung cấp câu trả lời dựng sẵn mà không dùng I/O thật.

Trait `InputHandler` cho phép `AskTool` hoạt động với cả ba kiểu này mà không
cần biết cụ thể nó đang dùng kiểu nào:

```rust
#[async_trait::async_trait]
pub trait InputHandler: Send + Sync {
    async fn ask(&self, question: &str, options: &[String]) -> anyhow::Result<String>;
}
```

`question` là điều LLM muốn hỏi. Slice `options` là danh sách lựa chọn tùy chọn.
Nếu nó rỗng, người dùng sẽ nhập tự do. Nếu không rỗng, UI có thể hiển thị dạng
danh sách để chọn.

## AskTool

`AskTool` triển khai trait `Tool`. Nó nhận vào một `Arc<dyn InputHandler>` để
handler có thể được chia sẻ giữa nhiều thread:

```rust
pub struct AskTool {
    definition: ToolDefinition,
    handler: Arc<dyn InputHandler>,
}
```

### Định nghĩa tool

LLM cần biết tool này chấp nhận những tham số nào. `question` là bắt buộc
(kiểu string). `options` là tùy chọn (một mảng string).

Với `options`, ta cần một JSON schema cho kiểu mảng, thứ mà `param()` không
biểu diễn được vì nó chỉ hỗ trợ kiểu scalar. Vì vậy trước tiên hãy thêm
`param_raw()` vào `ToolDefinition`:

```rust
/// Add a parameter with a raw JSON schema value.
///
/// Use this for complex types (arrays, nested objects) that `param()` can't express.
pub fn param_raw(mut self, name: &str, schema: Value, required: bool) -> Self {
    self.parameters["properties"][name] = schema;
    if required {
        self.parameters["required"]
            .as_array_mut()
            .unwrap()
            .push(serde_json::Value::String(name.to_string()));
    }
    self
}
```

Bây giờ định nghĩa tool có thể dùng đồng thời cả `param()` và `param_raw()`:

```rust
impl AskTool {
    pub fn new(handler: Arc<dyn InputHandler>) -> Self {
        Self {
            definition: ToolDefinition::new(
                "ask_user",
                "Ask the user a clarifying question...",
            )
            .param("question", "string", "The question to ask the user", true)
            .param_raw(
                "options",
                json!({
                    "type": "array",
                    "items": { "type": "string" },
                    "description": "Optional list of choices to present to the user"
                }),
                false,
            ),
            handler,
        }
    }
}
```

### `Tool::call`

Implementation của `call` sẽ lấy `question`, parse `options` qua một helper,
rồi ủy quyền cho handler:

```rust
#[async_trait::async_trait]
impl Tool for AskTool {
    fn definition(&self) -> &ToolDefinition {
        &self.definition
    }

    async fn call(&self, args: Value) -> anyhow::Result<String> {
        let question = args
            .get("question")
            .and_then(|v| v.as_str())
            .ok_or_else(|| anyhow::anyhow!("missing required parameter: question"))?;

        let options = parse_options(&args);

        self.handler.ask(question, &options).await
    }
}

/// Extract the optional `options` array from tool arguments.
fn parse_options(args: &Value) -> Vec<String> {
    args.get("options")
        .and_then(|v| v.as_array())
        .map(|arr| {
            arr.iter()
                .filter_map(|v| v.as_str().map(String::from))
                .collect()
        })
        .unwrap_or_default()
}
```

Helper `parse_options` giúp `call()` chỉ tập trung vào luồng chính. Nếu
`options` bị thiếu hoặc không phải mảng, nó sẽ mặc định trả về vec rỗng, và
handler sẽ hiểu đó là input tự do.

## Ba kiểu handler

### `CliInputHandler`

Đây là handler đơn giản nhất. Nó in câu hỏi ra màn hình, liệt kê các lựa chọn
đánh số (nếu có), đọc một dòng từ stdin, rồi resolve câu trả lời dạng số:

```rust
pub struct CliInputHandler;

#[async_trait::async_trait]
impl InputHandler for CliInputHandler {
    async fn ask(&self, question: &str, options: &[String]) -> anyhow::Result<String> {
        let question = question.to_string();
        let options = options.to_vec();

        // spawn_blocking because stdin is synchronous
        tokio::task::spawn_blocking(move || {
            // Display the question and numbered choices (if any)
            println!("\n  {question}");
            for (i, opt) in options.iter().enumerate() {
                println!("    {}) {opt}", i + 1);
            }

            // Read the answer
            print!("  > ");
            io::stdout().flush()?;
            let mut line = String::new();
            io::stdin().lock().read_line(&mut line)?;
            let answer = line.trim().to_string();

            // If the user typed a valid option number, resolve it
            Ok(resolve_option(&answer, &options))
        }).await?
    }
}

/// If `answer` is a number matching one of the options, return that option.
/// Otherwise return the raw answer.
fn resolve_option(answer: &str, options: &[String]) -> String {
    if let Ok(n) = answer.parse::<usize>()
        && n >= 1
        && n <= options.len()
    {
        return options[n - 1].clone();
    }
    answer.to_string()
}
```

Helper `resolve_option` giúp phần closure dễ đọc hơn. Nó dùng **let-chain
syntax** (ổn định từ Rust 1.87 / edition 2024): nhiều điều kiện nối với `&&`,
bao gồm cả pattern binding `let Ok(n) = ...`. Nếu người dùng nhập `"2"` và có
ba lựa chọn, nó sẽ trả về `options[1]`. Nếu không, câu trả lời thô sẽ được giữ
nguyên.

Lưu ý rằng vòng `for` qua `options` sẽ tự động không làm gì khi slice rỗng,
không cần một nhánh `if` riêng.

Bạn sẽ dùng nó trong các ứng dụng CLI đơn giản như `examples/chat.rs`:

```rust
let agent = SimpleAgent::new(provider)
    .tool(BashTool::new())
    .tool(ReadTool::new())
    .tool(WriteTool::new())
    .tool(EditTool::new())
    .tool(AskTool::new(Arc::new(CliInputHandler)));
```

### `ChannelInputHandler`

Với ứng dụng TUI, việc thu input diễn ra trong event loop, không nằm trong
tool. `ChannelInputHandler` đóng vai trò cầu nối bằng một channel:

```rust
pub struct UserInputRequest {
    pub question: String,
    pub options: Vec<String>,
    pub response_tx: oneshot::Sender<String>,
}

pub struct ChannelInputHandler {
    tx: mpsc::UnboundedSender<UserInputRequest>,
}
```

Khi `ask()` được gọi, nó gửi một `UserInputRequest` qua channel rồi chờ phản
hồi từ oneshot:

```rust
#[async_trait::async_trait]
impl InputHandler for ChannelInputHandler {
    async fn ask(&self, question: &str, options: &[String]) -> anyhow::Result<String> {
        let (response_tx, response_rx) = oneshot::channel();
        self.tx.send(UserInputRequest {
            question: question.to_string(),
            options: options.to_vec(),
            response_tx,
        })?;
        Ok(response_rx.await?)
    }
}
```

TUI event loop sẽ nhận request này và render theo cách nó muốn, có thể là một
prompt văn bản đơn giản, hoặc một danh sách chọn bằng phím mũi tên dùng
`crossterm` trong raw terminal mode.

### `MockInputHandler`

Trong test, ta cấu hình sẵn các câu trả lời trong một queue:

```rust
pub struct MockInputHandler {
    answers: Mutex<VecDeque<String>>,
}

#[async_trait::async_trait]
impl InputHandler for MockInputHandler {
    async fn ask(&self, _question: &str, _options: &[String]) -> anyhow::Result<String> {
        self.answers.lock().await.pop_front()
            .ok_or_else(|| anyhow::anyhow!("MockInputHandler: no more answers"))
    }
}
```

Nó theo đúng mẫu của `MockProvider`: pop phần tử đầu, và trả lỗi khi queue
rỗng. Cần chú ý rằng chỗ này dùng `tokio::sync::Mutex` (với `.lock().await`),
không phải `std::sync::Mutex`. Lý do là `ask()` là một `async fn`, và lock
guard cần được giữ qua ranh giới `.await`. Guard của `std::sync::Mutex` là
`!Send`, nên nếu giữ nó qua `.await` thì code sẽ không compile.
`tokio::sync::Mutex` tạo ra một guard an toàn cho ngữ cảnh async. Điều này khác
với `MockProvider` ở Chương 1, nơi `std::sync::Mutex` vẫn ổn vì `chat()` không
giữ guard qua `.await`.

## Tóm tắt tool trong terminal

Hãy cập nhật `tool_summary()` trong `agent.rs` để hiển thị `"question"` cho
các lời gọi `ask_user` trong output terminal:

```rust
let detail = call.arguments
    .get("command")
    .or_else(|| call.arguments.get("path"))
    .or_else(|| call.arguments.get("question"))  // <-- new
    .and_then(|v| v.as_str());
```

## Tích hợp với plan mode

`ask_user` là một tool chỉ-đọc: nó thu thập thông tin mà không làm thay đổi gì.
Hãy thêm nó vào tập `read_only` mặc định của `PlanAgent` (xem
[Chương 12](./ch12-plan-mode.md)) để LLM có thể đặt câu hỏi trong giai đoạn lập kế hoạch:

```rust
read_only: HashSet::from(["bash", "read", "ask_user"]),
```

## Kết nối vào dự án

Thêm module này vào `mini-claw-code/src/tools/mod.rs`:

```rust
mod ask;
pub use ask::*;
```

Và re-export từ `lib.rs`:

```rust
pub use tools::{
    AskTool, BashTool, ChannelInputHandler, CliInputHandler,
    EditTool, InputHandler, MockInputHandler, ReadTool,
    UserInputRequest, WriteTool,
};
```

## Chạy test

```bash
cargo test -p mini-claw-code ch11
```

Các test sẽ kiểm tra:

- **Định nghĩa tool**: schema có `question` (bắt buộc) và `options` (mảng tùy chọn).
- **Chỉ có câu hỏi**: `MockInputHandler` trả lời đúng cho lời gọi chỉ có câu hỏi.
- **Có lựa chọn**: tool truyền đúng `options` vào handler.
- **Thiếu question**: thiếu tham số `question` sẽ trả lỗi.
- **Handler cạn dữ liệu**: `MockInputHandler` rỗng sẽ trả lỗi.
- **Agent loop**: LLM gọi `ask_user`, nhận câu trả lời rồi mới trả text cuối cùng.
- **Hỏi rồi gọi tool khác**: `ask_user` diễn ra trước một tool khác (ví dụ `read`).
- **Nhiều lần hỏi**: hai lời gọi `ask_user` nối tiếp với các câu trả lời khác nhau.
- **Roundtrip qua channel**: `ChannelInputHandler` gửi request và nhận response qua oneshot channel.
- **`param_raw`**: `param_raw()` thêm đúng tham số kiểu mảng vào `ToolDefinition`.

## Tổng kết

- **Trait `InputHandler`** trừu tượng hóa việc thu input cho CLI, TUI và test.
- **`AskTool`** cho phép LLM tạm dừng để đặt câu hỏi cho người dùng.
- **`param_raw()`** mở rộng `ToolDefinition` để hỗ trợ JSON schema phức tạp như mảng.
- **Ba loại handler**: `CliInputHandler` cho ứng dụng đơn giản,
  `ChannelInputHandler` cho TUI, `MockInputHandler` cho test.
- **Plan mode**: `ask_user` mặc định là read-only nên dùng được trong giai đoạn lập kế hoạch.
- **Hoàn toàn cộng thêm**: không cần sửa `SimpleAgent`, `StreamingAgent` hay các tool hiện có.
