# Chương 7: Một CLI đơn giản

Bạn đã xây xong mọi thành phần: mock provider để test, bốn tool, agent loop và
HTTP provider. Giờ là lúc nối tất cả chúng lại thành một CLI chạy được thật.

## Mục tiêu

Thêm phương thức `chat()` vào `SimpleAgent` và viết `examples/chat.rs` sao cho:

1. Agent nhớ được toàn bộ hội thoại -- mỗi prompt mới được xây trên các prompt trước đó.
2. Nó in `> `, đọc một dòng nhập vào, chạy agent, rồi in kết quả.
3. Nó hiển thị chỉ báo `thinking...` trong lúc agent làm việc.
4. Nó tiếp tục chạy cho tới khi người dùng nhấn Ctrl+D (EOF).

## Phương thức `chat()`

Mở `mini-claw-code-starter/src/agent.rs`. Ngay bên dưới `run()` bạn sẽ thấy
chữ ký của phương thức `chat()`.

### Vì sao cần thêm một phương thức mới?

`run()` tạo ra một `Vec<Message>` mới hoàn toàn mỗi lần được gọi. Điều đó có
nghĩa là LLM không nhớ gì về các lượt trước. Một CLI thực sự cần mang ngữ cảnh
theo thời gian, để LLM có thể nói "tôi đã đọc file đó rồi" hoặc "như tôi đã
đề cập ở trên".

`chat()` giải quyết điều đó bằng cách nhận trực tiếp lịch sử message từ caller:

```rust
pub async fn chat(&self, messages: &mut Vec<Message>) -> anyhow::Result<String>
```

Caller sẽ tự đẩy `Message::User(…)` vào trước khi gọi, còn `chat()` sẽ nối
thêm các assistant turn. Khi phương thức trả về, `messages` sẽ chứa toàn bộ
lịch sử hội thoại sẵn sàng cho lượt tiếp theo.

### Phần triển khai

Phần thân vòng lặp giống hệt `run()`. Chỉ có vài điểm khác:

1. Dùng `messages` được truyền vào thay vì tạo vector mới.
2. Khi gặp `StopReason::Stop`, phải clone text *trước khi* đẩy
   `Message::Assistant(turn)` -- vì thao tác push sẽ move `turn`, nên bạn cần
   lấy text trước.
3. Đẩy `Message::Assistant(turn)` để lịch sử có cả phản hồi cuối cùng.
4. Trả lại đoạn text đã clone.

```rust
pub async fn chat(&self, messages: &mut Vec<Message>) -> anyhow::Result<String> {
    let defs = self.tools.definitions();

    loop {
        let turn = self.provider.chat(messages, &defs).await?;

        match turn.stop_reason {
            StopReason::Stop => {
                let text = turn.text.clone().unwrap_or_default();
                messages.push(Message::Assistant(turn));
                return Ok(text);
            }
            StopReason::ToolUse => {
                // Same tool execution as run() ...
            }
        }
    }
}
```

Nhánh `ToolUse` giống hệt như trong `run()`: thực thi từng tool, gom kết quả,
đẩy assistant turn, rồi đẩy tiếp các tool result.

### Chi tiết về ownership

Trong `run()`, bạn có thể viết trực tiếp
`return Ok(turn.text.unwrap_or_default())` vì hàm đã dùng xong `turn`. Còn
trong `chat()`, bạn vẫn cần đẩy `Message::Assistant(turn)` vào lịch sử. Vì
phép push đó sẽ move `turn`, nên bạn phải lấy text ra trước:

```rust
let text = turn.text.clone().unwrap_or_default();
messages.push(Message::Assistant(turn));  // moves turn
return Ok(text);                          // return the clone
```

Chỉ khác một dòng so với `run()`, nhưng đây là khác biệt quan trọng.

## CLI

Mở `mini-claw-code-starter/examples/chat.rs`. Bạn sẽ thấy một khung chương
trình với `unimplemented!()`. Hãy thay nó bằng phiên bản hoàn chỉnh.

### Bước 1: Import

```rust
use mini_claw_code_starter::{
    BashTool, EditTool, Message, OpenRouterProvider, ReadTool, SimpleAgent, WriteTool,
};
use std::io::{self, BufRead, Write};
```

Lưu ý phần import `Message` -- bạn cần nó để tạo vector lịch sử.

### Bước 2: Tạo provider và agent

```rust
let provider = OpenRouterProvider::from_env()?;
let agent = SimpleAgent::new(provider)
    .tool(BashTool::new())
    .tool(ReadTool::new())
    .tool(WriteTool::new())
    .tool(EditTool::new());
```

Giống hệt các chương trước -- không có gì mới ở đây. (Đến
[Chương 11](./ch11-user-input.md), bạn sẽ thêm `AskTool` vào đây để agent có
thể hỏi lại bạn khi cần làm rõ yêu cầu.)

### Bước 3: System prompt và vector history

```rust
let cwd = std::env::current_dir()?.display().to_string();
let mut history: Vec<Message> = vec![Message::System(format!(
    "You are a coding agent. Help the user with software engineering tasks \
     using all available tools. Be concise and precise.\n\n\
     Working directory: {cwd}"
))];
```

System prompt là message đầu tiên trong lịch sử. Nó nói cho LLM biết vai trò
mà nó phải đảm nhận. Có hai điểm đáng chú ý:

1. **Không liệt kê tên tool trong prompt.** Tool definition được gửi riêng tới
   API. System prompt chỉ tập trung vào *hành vi* -- hãy đóng vai một coding
   agent, dùng bất kỳ tool nào có sẵn, và trả lời ngắn gọn, chính xác.

2. **Có chèn thư mục làm việc hiện tại.** LLM cần biết nó đang đứng ở đâu để
   những tool call như `read` hay `bash` dùng đúng đường dẫn. Đây cũng chính là
   cách các coding agent thật làm -- Claude Code, OpenCode và Kimi CLI đều
   chèn current directory (đôi khi cả platform, ngày tháng, v.v.) vào system
   prompt.

Vector history nằm ngoài vòng lặp và tích lũy toàn bộ user prompt, assistant
response, và tool result xuyên suốt phiên làm việc. System prompt luôn nằm ở
đầu, giúp LLM nhận cùng một bộ chỉ dẫn ở mọi lượt.

### Bước 4: Vòng lặp REPL

```rust
let stdin = io::stdin();

loop {
    print!("> ");
    io::stdout().flush()?;

    let mut line = String::new();
    if stdin.lock().read_line(&mut line)? == 0 {
        println!();
        break;
    }

    let prompt = line.trim();
    if prompt.is_empty() {
        continue;
    }

    history.push(Message::User(prompt.to_string()));
    print!("    thinking...");
    io::stdout().flush()?;
    match agent.chat(&mut history).await {
        Ok(text) => {
            print!("\x1b[2K\r");
            println!("{}\n", text.trim());
        }
        Err(e) => {
            print!("\x1b[2K\r");
            println!("error: {e}\n");
        }
    }
}
```

Một vài điểm quan trọng:

- **`history.push(Message::User(…))`** thêm prompt của người dùng trước khi gọi
  agent. Phần còn lại sẽ do `chat()` nối thêm.
- **`print!("    thinking...")`** hiển thị trạng thái trong khi agent chạy.
  Phải gọi `flush()` vì `print!` (không có newline) sẽ không tự flush.
- **`\x1b[2K\r`** là chuỗi escape ANSI: "xóa toàn bộ dòng hiện tại, rồi đưa con
  trỏ về cột đầu tiên". Nó dùng để xóa dòng `thinking...` trước khi in phản
  hồi. Dòng này cũng sẽ tự được dọn khi agent in tool summary ra màn hình
  (vì `tool_summary()` dùng cùng cơ chế đó).
- **`stdout.flush()?`** sau `print!` giúp prompt và chỉ báo `thinking...` hiện
  ra ngay lập tức.
- `read_line` trả về `0` khi gặp EOF (Ctrl+D), lúc đó vòng lặp sẽ kết thúc.
- Lỗi từ agent được in ra thay vì làm crash chương trình -- nhờ vậy vòng lặp
  vẫn sống dù một request nào đó thất bại.

### Hàm `main`

Bọc toàn bộ chương trình trong một `async main`:

```rust
#[tokio::main]
async fn main() -> anyhow::Result<()> {
    // Steps 1-4 go here
    Ok(())
}
```

### Chương trình hoàn chỉnh

Ghép tất cả lại, toàn bộ chương trình chỉ khoảng 45 dòng. Đó là cái hay của bộ
khung bạn vừa xây: bước lắp ráp cuối cùng trở nên đơn giản vì mỗi thành phần
đều có interface sạch và rõ ràng.

## Chạy toàn bộ test suite

Chạy đầy đủ test:

```bash
cargo test -p mini-claw-code-starter
```

Lệnh này sẽ chạy tất cả test từ Chương 1 đến Chương 7. Nếu mọi thứ đều qua,
xin chúc mừng -- framework agent của bạn đã hoàn chỉnh và được test đầy đủ.

### Các test kiểm tra điều gì

Các test của Chương 7 là integration test, nơi mọi thành phần được ghép lại:

- **Luồng write rồi read**: Ghi file, đọc lại, và xác minh nội dung.
- **Luồng edit**: Ghi file, chỉnh sửa file, rồi đọc kết quả.
- **Pipeline nhiều tool**: Dùng bash, write, edit và read qua nhiều lượt.
- **Hội thoại dài**: Chuỗi tool call kéo dài năm bước.

Có khoảng 10 integration test kiểm tra toàn bộ pipeline của agent.

## Chạy chat example

Để thử với LLM thật, bạn cần có API key. Hãy tạo file `.env` ở thư mục gốc của
workspace:

```
OPENROUTER_API_KEY=sk-or-v1-your-key-here
```

Sau đó chạy:

```bash
cargo run -p mini-claw-code-starter --example chat
```

Bạn sẽ thấy một prompt tương tác. Hãy thử một hội thoại nhiều lượt:

```text
> List the files in the current directory
    thinking...
    [bash: ls]
Cargo.toml  src/  examples/  ...

> What is in Cargo.toml?
    thinking...
    [read: Cargo.toml]
The Cargo.toml contains the package definition for mini-claw-code-starter...

> Add a new dependency for serde
    thinking...
    [read: Cargo.toml]
    [edit: Cargo.toml]
Done! I added serde to the dependencies.

>
```

Hãy chú ý rằng prompt thứ hai ("What is in Cargo.toml?") vẫn hoạt động dù bạn
không lặp lại bối cảnh -- LLM đã nhớ được danh sách thư mục từ lượt đầu tiên.
Đó chính là tác dụng của conversation history.

---

Nhấn Ctrl+D (hoặc Ctrl+C) để thoát.

## Bạn vừa xây được gì

Hãy lùi lại một bước và nhìn bức tranh hoàn chỉnh:

```text
examples/chat.rs
    |
    | creates
    v
SimpleAgent<OpenRouterProvider>
    |
    | holds
    +---> OpenRouterProvider (HTTP to LLM API)
    +---> ToolSet (HashMap<String, Box<dyn Tool>>)
              |
              +---> BashTool
              +---> ReadTool
              +---> WriteTool
              +---> EditTool
```

Phương thức `chat()` điều phối toàn bộ tương tác:

```text
User prompt
    |
    v
history: [User, Assistant, ToolResult, ..., User]
    |
    v
Provider.chat() ---HTTP---> LLM API
    |
    | AssistantTurn
    v
Tool calls? ----yes---> Execute tools ---> append to history ---> loop
    |
    no
    |
    v
Append final Assistant to history, return text
```

Chỉ với khoảng 300 dòng Rust trải trên toàn bộ các file, bạn đã có:

- Một hệ thống tool dựa trên trait, với JSON schema definition.
- Một agent loop generic làm việc với bất kỳ provider nào.
- Một mock provider để kiểm thử theo cách xác định.
- Một HTTP provider để dùng với LLM API thật.
- Một CLI có nhớ lịch sử hội thoại, giúp nối toàn bộ hệ thống lại với nhau.

## Bạn có thể đi tiếp theo hướng nào

Framework này được cố ý giữ ở mức tối giản. Dưới đây là vài hướng mở rộng:

**Streaming response** -- Thay vì chờ toàn bộ phản hồi, hãy stream token ngay
khi chúng tới. Điều đó có nghĩa là phải đổi `chat()` để nó trả về `Stream`
thay vì một `AssistantTurn` đơn lẻ.

**Giới hạn token** -- Theo dõi mức sử dụng token và cắt bớt message cũ khi cửa
sổ context bắt đầu đầy.

**Nhiều tool hơn** -- Thêm tool tìm kiếm web, truy vấn cơ sở dữ liệu, hoặc bất
cứ thứ gì bạn muốn. Trait `Tool` giúp bạn cắm thêm khả năng mới khá dễ.

**UI phong phú hơn** -- Thêm spinner, render Markdown, hoặc thu gọn phần hiển
thị tool call. Xem `mini-claw-code/examples/tui.rs` để thấy một ví dụ làm đủ
cả ba bằng `termimad`.

Nền móng bạn vừa xây là rất chắc. Mọi phần mở rộng tiếp theo chỉ là tiếp tục
phát triển từ các pattern sẵn có, chứ không cần viết lại từ đầu. Trait
`Provider`, trait `Tool`, và agent loop chính là ba khối cơ bản cho bất cứ thứ
gì bạn muốn xây tiếp theo.

## Tiếp theo là gì

Hãy sang [Chương 8: Điểm kỳ dị](./ch08-singularity.md) -- agent của bạn giờ đã
có thể chỉnh sửa chính mã nguồn của nó, và chúng ta sẽ bàn về ý nghĩa của điều
đó cũng như các hướng đi kế tiếp.
