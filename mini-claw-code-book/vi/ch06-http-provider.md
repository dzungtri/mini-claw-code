# Chương 6: OpenRouter Provider

Cho tới giờ, mọi thứ đều chạy cục bộ với `MockProvider`. Trong chương này, bạn
sẽ triển khai `OpenRouterProvider` -- một provider giao tiếp với LLM thật qua
HTTP bằng API chat completions tương thích OpenAI.

Đây là chương biến agent của bạn thành một hệ thống thật sự.

## Mục tiêu

Hãy triển khai `OpenRouterProvider` sao cho:

1. Nó có thể được tạo từ API key và tên model.
2. Nó chuyển đổi các kiểu nội bộ `Message` và `ToolDefinition` sang định dạng
   của API.
3. Nó gửi HTTP POST request tới endpoint chat completions.
4. Nó parse phản hồi trở lại thành `AssistantTurn`.

## Các khái niệm Rust chính

### Serde derive và attribute

Các kiểu dữ liệu API trong `openrouter.rs` đã được cung cấp sẵn -- bạn không
cần sửa chúng. Nhưng hiểu chúng sẽ giúp ích:

```rust
#[derive(Serialize, Deserialize, Clone, Debug)]
pub(crate) struct ApiToolCall {
    pub(crate) id: String,
    #[serde(rename = "type")]
    pub(crate) type_: String,
    pub(crate) function: ApiFunction,
}
```

Những serde attribute quan trọng được dùng ở đây:

- **`#[serde(rename = "type")]`** -- Trường JSON tên là `"type"`, nhưng
  `type` là từ khóa dành riêng trong Rust. Vì vậy trường trong struct được đặt
  là `type_`, rồi serde đổi tên nó khi serialize/deserialze.

- **`#[serde(skip_serializing_if = "Option::is_none")]`** -- Bỏ hẳn field khỏi
  JSON nếu giá trị là `None`. Điều này quan trọng vì API mong một số field phải
  vắng mặt hẳn (chứ không phải `null`) khi không dùng.

- **`#[serde(skip_serializing_if = "Vec::is_empty")]`** -- Ý tưởng tương tự
  nhưng áp dụng cho vector rỗng. Nếu không có tool nào, ta bỏ hẳn field `tools`.

### HTTP client `reqwest`

`reqwest` là crate HTTP client tiêu chuẩn trong Rust. Mẫu gọi thường như sau:

```rust
let response: MyType = client
    .post(url)
    .bearer_auth(&api_key)
    .json(&body)        // serialize body as JSON
    .send()
    .await
    .context("request failed")?
    .error_for_status() // turn 4xx/5xx into errors
    .context("API returned error status")?
    .json()             // deserialize response as JSON
    .await
    .context("failed to parse response")?;
```

Mỗi lời gọi trả về một builder hoặc future để bạn chain tiếp. Toán tử `?` sẽ
propagate lỗi tại từng bước.

### `impl Into<String>`

Một số phương thức dùng `impl Into<String>` làm kiểu tham số:

```rust
pub fn new(api_key: impl Into<String>, model: impl Into<String>) -> Self
```

Điều này cho phép truyền vào bất kỳ thứ gì có thể chuyển thành `String`:
`String`, `&str`, `Cow<str>`, v.v. Bên trong phương thức, chỉ cần gọi `.into()`
để lấy `String`:

```rust
api_key: api_key.into(),
model: model.into(),
```

### `dotenvy`

Crate `dotenvy` dùng để nạp biến môi trường từ file `.env`:

```rust
let _ = dotenvy::dotenv(); // loads .env if present, ignores errors
let key = std::env::var("OPENROUTER_API_KEY")?;
```

`let _ =` dùng để bỏ qua kết quả vì việc `.env` không tồn tại cũng không sao
(có thể biến môi trường đã được set sẵn từ trước).

## Các kiểu dữ liệu của API

File `mini-claw-code-starter/src/providers/openrouter.rs` bắt đầu bằng một cụm
serde struct. Chúng đại diện cho định dạng của API chat completions tương thích
OpenAI. Tóm tắt nhanh:

**Kiểu request:**
- `ChatRequest` -- phần thân POST: tên model, messages, tools
- `ApiMessage` -- một message đơn với role, content, và tool calls tùy chọn
- `ApiTool` / `ApiToolDef` -- tool definition theo định dạng API

**Kiểu response:**
- `ChatResponse` -- phản hồi từ API: một danh sách `choices`
- `Choice` -- một lựa chọn cụ thể chứa `message` và `finish_reason`
- `ResponseMessage` -- phản hồi của assistant: content tùy chọn, tool calls tùy chọn

Field `finish_reason` trên `Choice` cho biết vì sao model dừng sinh nội dung.
Trong phần `chat()` của bạn, hãy map nó sang `StopReason`:
`"tool_calls"` thành `StopReason::ToolUse`, còn mọi giá trị khác thành
`StopReason::Stop`.

Các kiểu này đã hoàn chỉnh sẵn. Công việc của bạn là triển khai các phương thức
*sử dụng* chúng.

## Phần triển khai

### Bước 1: Triển khai `new()`

Khởi tạo cả bốn field:

```rust
pub fn new(api_key: impl Into<String>, model: impl Into<String>) -> Self {
    Self {
        client: reqwest::Client::new(),
        api_key: api_key.into(),
        model: model.into(),
        base_url: "https://openrouter.ai/api/v1".into(),
    }
}
```

### Bước 2: Triển khai `base_url()`

Một builder method đơn giản dùng để ghi đè base URL:

```rust
pub fn base_url(mut self, url: impl Into<String>) -> Self {
    self.base_url = url.into();
    self
}
```

### Bước 3: Triển khai `from_env_with_model()`

1. Nạp `.env` bằng `dotenvy::dotenv()` (bỏ qua kết quả).
2. Đọc `OPENROUTER_API_KEY` từ môi trường.
3. Gọi `Self::new()` với key và model.

Hãy dùng `std::env::var("OPENROUTER_API_KEY")` và chain thêm `.context(...)`
để có thông báo lỗi rõ ràng nếu key bị thiếu.

### Bước 4: Triển khai `from_env()`

Đây chỉ là một one-liner gọi `from_env_with_model` với model mặc định
`"openrouter/free"`. Đây là model miễn phí trên OpenRouter, đủ để bắt đầu mà
không cần nạp credit.

### Bước 5: Triển khai `convert_messages()`

Phương thức này chuyển `Message` enum nội bộ của bạn sang định dạng `ApiMessage`
của API. Hãy lặp qua danh sách message và `match` trên từng biến thể:

- **`Message::System(text)`** trở thành một `ApiMessage` với role `"system"` và
  `content: Some(text.clone())`. Các field còn lại là `None`.

- **`Message::User(text)`** trở thành một `ApiMessage` với role `"user"` và
  `content: Some(text.clone())`. Các field còn lại là `None`.

- **`Message::Assistant(turn)`** trở thành một `ApiMessage` với role
  `"assistant"`. Đặt `content` thành `turn.text.clone()`. Nếu
  `turn.tool_calls` không rỗng, hãy chuyển từng `ToolCall` sang `ApiToolCall`:

  ```rust
  ApiToolCall {
      id: c.id.clone(),
      type_: "function".into(),
      function: ApiFunction {
          name: c.name.clone(),
          arguments: c.arguments.to_string(), // Value -> String
      },
  }
  ```

  Nếu `tool_calls` rỗng, đặt `tool_calls: None` (không phải `Some(vec![])`).

- **`Message::ToolResult { id, content }`** trở thành một `ApiMessage` với role
  `"tool"`, `content: Some(content.clone())`, và `tool_call_id: Some(id.clone())`.

### Bước 6: Triển khai `convert_tools()`

Map mỗi `&ToolDefinition` thành một `ApiTool`:

```rust
ApiTool {
    type_: "function",
    function: ApiToolDef {
        name: t.name,
        description: t.description,
        parameters: t.parameters.clone(),
    },
}
```

### Bước 7: Triển khai `chat()`

Đây là phương thức chính. Nó ghép toàn bộ các mảnh lại với nhau:

1. Tạo `ChatRequest` với model, messages đã convert, và tools đã convert.
2. Gửi POST tới `{base_url}/chat/completions` với bearer auth.
3. Parse phản hồi thành `ChatResponse`.
4. Lấy choice đầu tiên.
5. Chuyển `tool_calls` trở lại kiểu `ToolCall` nội bộ của bạn.

Phần chuyển tool call là chỗ dễ vấp nhất. API trả về
`function.arguments` dưới dạng *chuỗi* (JSON đã được encode), trong khi
`ToolCall` nội bộ của bạn lưu nó dưới dạng `serde_json::Value`. Vì vậy bạn
cần parse lại:

```rust
let arguments = serde_json::from_str(&tc.function.arguments)
    .unwrap_or(Value::Null);
```

`unwrap_or(Value::Null)` xử lý trường hợp chuỗi arguments không phải JSON hợp
lệ (trường hợp này hiếm với một API hoạt động đúng, nhưng cứ phòng thủ vẫn tốt).

Đây là skeleton cho `chat()`:

```rust
async fn chat(
    &self,
    messages: &[Message],
    tools: &[&ToolDefinition],
) -> anyhow::Result<AssistantTurn> {
    let body = ChatRequest {
        model: &self.model,
        messages: Self::convert_messages(messages),
        tools: Self::convert_tools(tools),
    };

    let response: ChatResponse = self.client
        .post(format!("{}/chat/completions", self.base_url))
        // ... bearer_auth, json, send, error_for_status, json ...
        ;

    let choice = response.choices.into_iter().next()
        .context("no choices in response")?;

    // Convert choice.message.tool_calls to Vec<ToolCall>
    // Map finish_reason to StopReason
    // Return AssistantTurn { text, tool_calls, stop_reason }
    todo!()
}
```

Hãy điền nốt phần chain HTTP và logic chuyển đổi response.

## Chạy test

Chạy bộ test của Chương 6:

```bash
cargo test -p mini-claw-code-starter ch6
```

Các test của Chương 6 sẽ kiểm tra các hàm chuyển đổi (`convert_messages` và
`convert_tools`), logic constructor, và toàn bộ phương thức `chat()` bằng một
mock HTTP server cục bộ. Chúng *không* gọi tới API LLM thật, nên bạn không cần
API key. Ngoài ra còn có thêm một số edge-case test, và chúng sẽ tự qua khi
phần triển khai lõi của bạn đúng.

### Tùy chọn: test thật với API

Nếu bạn muốn thử với API thật, hãy thiết lập OpenRouter API key:

1. Đăng ký tại [openrouter.ai](https://openrouter.ai).
2. Tạo một API key.
3. Tạo file `.env` ở thư mục gốc của workspace:

```
OPENROUTER_API_KEY=sk-or-v1-your-key-here
```

Sau đó thử build và chạy chat example ở Chương 7. Nhưng trước hết, hãy hoàn
thành chương này rồi sang Chương 7 để nối tất cả các phần lại với nhau.

## Tóm tắt

Bạn vừa triển khai một HTTP provider thật sự có khả năng:

- Khởi tạo từ API key và tên model (hoặc từ biến môi trường).
- Chuyển đổi qua lại giữa kiểu nội bộ của bạn và định dạng API tương thích OpenAI.
- Gửi HTTP request và parse phản hồi.

Những pattern quan trọng:
- **Serde attribute** để map field JSON (`rename`, `skip_serializing_if`).
- **`reqwest`** để làm HTTP với fluent builder API.
- **`impl Into<String>`** để tham số chuỗi linh hoạt hơn.
- **`dotenvy`** để nạp file `.env`.

Bộ khung agent của bạn giờ đã hoàn chỉnh. Mọi thành phần -- tools, agent loop,
và HTTP provider -- đều đã được cài đặt và kiểm thử.

## Tiếp theo là gì

Trong [Chương 7: Một CLI đơn giản](./ch07-putting-together.md), bạn sẽ nối mọi
thứ thành một CLI tương tác có khả năng nhớ lịch sử hội thoại.
