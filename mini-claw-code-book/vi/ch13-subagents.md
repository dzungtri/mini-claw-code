# Chương 13: Tác tử con

Những tác vụ phức tạp luôn khó. Ngay cả LLM tốt nhất cũng chật vật khi một
prompt duy nhất bắt nó vừa nghiên cứu codebase, vừa thiết kế hướng đi, vừa viết
code, rồi còn phải tự kiểm chứng kết quả, tất cả trong cùng một cuộc hội thoại
liền mạch. Context window sẽ nhanh chóng bị lấp đầy, mô hình mất tập trung, và
chất lượng bắt đầu đi xuống.

**Subagent** giải quyết điều này bằng cách phân rã bài toán: parent agent tạo
một child agent cho từng subtask. Child có message history và bộ tool riêng,
chạy đến khi hoàn thành, rồi trả lại một bản tóm tắt. Parent chỉ nhìn thấy câu
trả lời cuối cùng, một kết quả sạch và tập trung, không mang theo toàn bộ tiếng
ồn từ quá trình suy luận nội bộ của child.

Đây chính là cách **Task tool** của Claude Code hoạt động. Khi Claude Code cần
khảo sát một codebase lớn hoặc xử lý một subtask độc lập, nó sinh ra một
subagent để làm việc rồi báo cáo ngược lại. OpenCode và Anthropic Agent SDK
cũng dùng cùng mẫu thiết kế này.

Trong chương này bạn sẽ xây dựng `SubagentTool`, một implementation của `Tool`
có khả năng sinh ra các child agent tạm thời.

Bạn sẽ làm:

1. Thêm blanket `impl Provider for Arc<P>` để parent và child có thể dùng chung provider.
2. Xây dựng `SubagentTool<P: Provider>` với tool factory dựa trên closure và các builder method.
3. Triển khai trait `Tool` với một agent loop nội tuyến và giới hạn số turn.
4. Kết nối module này vào project và re-export nó.

## Tại sao cần subagent?

Hãy xem tình huống sau:

```text
User: "Add error handling to all API endpoints"

Agent (no subagents):
  → reads 15 files, context window fills up
  → forgets what it learned from file 3
  → produces inconsistent changes

Agent (with subagents):
  → spawns child: "Add error handling to /api/users.rs"
  → child reads 1 file, writes changes, returns "Done: added Result types"
  → spawns child: "Add error handling to /api/posts.rs"
  → child does the same
  → parent sees clean summaries, coordinates the overall task
```

Ý tưởng cốt lõi là: **subagent thực chất cũng chỉ là một Tool**. Nó nhận mô tả
nhiệm vụ làm input, tự làm việc ở bên trong, rồi trả về một chuỗi kết quả. Parent
agent loop không cần bất kỳ nhánh đặc biệt nào, nó gọi subagent y hệt như cách
nó gọi `read` hoặc `bash`.

## Chia sẻ provider bằng `Arc<P>`

Parent và child cần dùng chung một LLM provider. Trong môi trường thật, điều đó
nghĩa là dùng chung HTTP client, API key và cấu hình. Nếu clone provider, bạn sẽ
nhân đôi kết nối một cách không cần thiết. Ta muốn chia sẻ nó với chi phí thấp.

Câu trả lời là `Arc<P>`. Nhưng có một điểm vướng: trait `Provider` của chúng ta
dùng RPITIT (`return-position impl Trait in trait`), nên nó không object-safe.
Ta không thể dùng `dyn Provider`. Tuy nhiên ta *có thể* dùng `Arc<P>` với
`P: Provider`, miễn là `Arc<P>` tự nó cũng triển khai `Provider`.

Một blanket impl sẽ xử lý việc đó. Trong `types.rs`:

```rust
impl<P: Provider> Provider for Arc<P> {
    fn chat<'a>(
        &'a self,
        messages: &'a [Message],
        tools: &'a [&'a ToolDefinition],
    ) -> impl Future<Output = anyhow::Result<AssistantTurn>> + Send + 'a {
        (**self).chat(messages, tools)
    }
}
```

Nó đơn giản chỉ ủy quyền xuống `P` bên trong thông qua deref. Bây giờ cả
`Arc<MockProvider>` lẫn `Arc<OpenRouterProvider>` đều là provider hợp lệ. Mọi
code hiện có vẫn giữ nguyên: nếu trước đây bạn truyền `MockProvider` trực tiếp,
nó vẫn hoạt động. Việc bọc trong `Arc` là tùy chọn.

## Cấu trúc `SubagentTool`

```rust
pub struct SubagentTool<P: Provider> {
    provider: Arc<P>,
    tools_factory: Box<dyn Fn() -> ToolSet + Send + Sync>,
    system_prompt: Option<String>,
    max_turns: usize,
    definition: ToolDefinition,
}
```

Có ba quyết định thiết kế quan trọng ở đây:

**`Arc<P>` cho provider.** Parent tạo `Arc::new(provider)`, giữ lại một clone
cho mình, rồi đưa một clone khác vào `SubagentTool`. Cả hai cùng chia sẻ cùng
một provider gốc, rẻ, an toàn, và không cần clone HTTP client.

**Closure factory cho tool.** Tool được lưu dưới dạng `Box<dyn Tool>`, nên nó
không clone được. Mỗi lần sinh child sẽ cần một `ToolSet` mới tinh.
Closure `Fn() -> ToolSet` sẽ sản xuất nó theo yêu cầu. Cách này tự nhiên hỗ trợ
việc capture các `Arc` để chia sẻ state:

```rust
let provider = Arc::new(OpenRouterProvider::from_env()?);

SubagentTool::new(provider, || {
    ToolSet::new()
        .with(ReadTool::new())
        .with(WriteTool::new())
        .with(BashTool::new())
})
```

**Giới hạn an toàn `max_turns`.** Nếu thiếu giới hạn này, một child đang rối có
thể loop mãi. Giá trị mặc định là 10, đủ rộng cho các tác vụ thật, nhưng vẫn đủ
chặt để ngăn vòng lặp mất kiểm soát.

## Builder

Việc khởi tạo dùng cùng phong cách fluent builder như phần còn lại của codebase:

```rust
impl<P: Provider> SubagentTool<P> {
    pub fn new(
        provider: Arc<P>,
        tools_factory: impl Fn() -> ToolSet + Send + Sync + 'static,
    ) -> Self {
        Self {
            provider,
            tools_factory: Box::new(tools_factory),
            system_prompt: None,
            max_turns: 10,
            definition: ToolDefinition::new(
                "subagent",
                "Spawn a child agent to handle a subtask independently. \
                 The child has its own message history and tools.",
            )
            .param(
                "task",
                "string",
                "A clear description of the subtask for the child agent to complete.",
                true,
            ),
        }
    }

    pub fn system_prompt(mut self, prompt: impl Into<String>) -> Self {
        self.system_prompt = Some(prompt.into());
        self
    }

    pub fn max_turns(mut self, max: usize) -> Self {
        self.max_turns = max;
        self
    }
}
```

Định nghĩa tool chỉ lộ ra một tham số duy nhất là `task`: LLM sẽ viết mô tả rõ
ràng về việc child cần làm. Tối giản nhưng hiệu quả.

## Triển khai `Tool`

Trái tim của `SubagentTool` là `Tool::call()`. Nó nhúng trực tiếp một agent loop
tối thiểu, dùng đúng giao thức như `SimpleAgent::chat()` (gọi provider, chạy
tool, loop lại), nhưng có thêm giới hạn số turn, không in ra terminal, và dùng
một message vec cục bộ do chính nó sở hữu:

```rust
#[async_trait::async_trait]
impl<P: Provider + 'static> Tool for SubagentTool<P> {
    fn definition(&self) -> &ToolDefinition {
        &self.definition
    }

    async fn call(&self, args: Value) -> anyhow::Result<String> {
        let task = args
            .get("task")
            .and_then(|v| v.as_str())
            .ok_or_else(|| anyhow::anyhow!("missing required parameter: task"))?;

        let tools = (self.tools_factory)();
        let defs = tools.definitions();

        let mut messages = Vec::new();
        if let Some(ref prompt) = self.system_prompt {
            messages.push(Message::System(prompt.clone()));
        }
        messages.push(Message::User(task.to_string()));

        for _ in 0..self.max_turns {
            let turn = self.provider.chat(&messages, &defs).await?;

            match turn.stop_reason {
                StopReason::Stop => {
                    return Ok(turn.text.unwrap_or_default());
                }
                StopReason::ToolUse => {
                    let mut results = Vec::with_capacity(turn.tool_calls.len());
                    for call in &turn.tool_calls {
                        let content = match tools.get(&call.name) {
                            Some(t) => t
                                .call(call.arguments.clone())
                                .await
                                .unwrap_or_else(|e| format!("error: {e}")),
                            None => format!("error: unknown tool `{}`", call.name),
                        };
                        results.push((call.id.clone(), content));
                    }
                    messages.push(Message::Assistant(turn));
                    for (id, content) in results {
                        messages.push(Message::ToolResult { id, content });
                    }
                }
            }
        }

        Ok("error: max turns exceeded".to_string())
    }
}
```

Có vài điểm đáng chú ý:

**Không dùng `tokio::spawn`.** Child chạy ngay bên trong future `Tool::call()`
của parent. Đây là một lựa chọn có chủ ý: nếu đẩy child ra background task, bạn
sẽ phải gánh thêm độ phức tạp điều phối như channel, join handle hay hủy tác vụ.
Chạy nội tuyến giúp hệ thống đơn giản và quyết định hơn.

**Message history hoàn toàn mới.** Child chỉ bắt đầu với system prompt
(nếu có) và task dưới dạng `User` message. Nó không hề thấy cuộc hội thoại của
parent. Khi child xong, chỉ phần text cuối cùng được trả ngược về parent như
một tool result. Mọi message nội bộ của child sẽ bị bỏ đi.

**Giới hạn turn là một soft error.** Khi `max_turns` bị vượt quá, tool trả về
một chuỗi lỗi thay vì `Err(...)`. Cách này cho phép LLM ở phía parent nhìn thấy
thất bại và quyết định tiếp theo nên làm gì, ví dụ thử lại với task đơn giản hơn
hoặc chọn hướng khác, thay vì làm sập toàn bộ agent loop.

**Lỗi provider sẽ propagate.** Nếu API LLM lỗi trong lúc child đang chạy, lỗi đó
sẽ nổi lên qua toán tử `?` và đi ngược về parent. Đây là chủ ý, vì lỗi API là
lỗi hạ tầng, không phải lỗi bản thân task.

## Kết nối vào dự án

Thêm module và re-export trong `mini-claw-code/src/lib.rs`:

```rust
pub mod subagent;
// ...
pub use subagent::SubagentTool;
```

## Ví dụ sử dụng

Đây là cách bạn gắn subagent tool vào parent agent:

```rust
use std::sync::Arc;
use mini_claw_code::*;

let provider = Arc::new(OpenRouterProvider::from_env()?);
let p = provider.clone();

let agent = SimpleAgent::new(provider)
    .tool(ReadTool::new())
    .tool(WriteTool::new())
    .tool(BashTool::new())
    .tool(SubagentTool::new(p, || {
        ToolSet::new()
            .with(ReadTool::new())
            .with(WriteTool::new())
            .with(BashTool::new())
    }));

let result = agent.run("Refactor the auth module").await?;
```

Parent LLM sẽ thấy `subagent` nằm cạnh `read`, `write` và `bash` trong danh
sách tool. Khi task đủ phức tạp, LLM có thể chọn ủy quyền qua `subagent`, hoặc
vẫn tự xử lý bằng những tool còn lại. Quyết định nằm ở mô hình.

Bạn cũng có thể gán cho child một system prompt chuyên biệt:

```rust
SubagentTool::new(provider, || {
    ToolSet::new()
        .with(ReadTool::new())
        .with(BashTool::new())
})
.system_prompt("You are a security auditor. Review code for vulnerabilities.")
.max_turns(15)
```

## Chạy test

```bash
cargo test -p mini-claw-code ch13
```

Các test sẽ kiểm tra:

- **Text response**: child trả text ngay, không gọi tool nào.
- **Có dùng tool**: child dùng `ReadTool` trước khi trả lời.
- **Nhiều bước**: child gọi tool qua nhiều turn liên tiếp.
- **Vượt `max_turns`**: giới hạn số turn được áp dụng và trả về chuỗi lỗi.
- **Thiếu `task`**: lỗi khi không truyền tham số `task`.
- **Provider error**: lỗi từ provider của child sẽ propagate lên parent.
- **Unknown tool**: child xử lý tool không tồn tại một cách an toàn.
- **Builder pattern**: chain `.system_prompt().max_turns()` compile được.
- **System prompt**: child chạy đúng khi được cấu hình system prompt.
- **Write tool**: child có thể ghi file, rồi parent vẫn tiếp tục công việc của mình.
- **Parent continues**: parent tiếp tục chạy sau khi subagent hoàn tất.
- **Isolated history**: message của child không rò rỉ vào message vec của parent.

## Tổng kết

- **`SubagentTool`** là một `Tool` có khả năng sinh ra các child agent tạm thời.
  Parent chỉ nhìn thấy câu trả lời cuối cùng.
- **Blanket impl cho `Arc<P>`** cho phép parent và child dùng chung provider mà
  không phải clone thực thể bên dưới. Hoàn toàn tương thích ngược.
- **Closure factory** tạo ra một `ToolSet` mới cho mỗi lần sinh child, vì
  `Box<dyn Tool>` không clone được.
- **Agent loop nội tuyến** cùng guard `max_turns` giúp giữ nguyên `SimpleAgent`.
  Không cần `tokio::spawn`, child chạy trực tiếp trong `Tool::call()`.
- **Cô lập message**: toàn bộ message nội bộ của child chỉ tồn tại bên trong
  future `call()`. Chỉ có text cuối cùng quay trở lại parent.
- **Một tham số `task` duy nhất**: LLM viết mô tả task thật rõ ràng, child lo phần còn lại.
- **Hoàn toàn cộng thêm**: thay đổi duy nhất vào code cũ là blanket impl trong
  `types.rs`; mọi phần còn lại đều là code mới.
