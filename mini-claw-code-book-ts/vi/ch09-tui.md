# Chương 9: Một TUI Tốt Hơn

CLI chat ở Chapter 7 hoạt động được, nhưng vẫn chỉ là text đơn giản. Một coding
agent thật sự cần hành vi terminal tốt hơn: có spinner khi model đang suy nghĩ,
hiển thị gọn các tool call, hỗ trợ text được stream, và có chỗ để dừng lại khi
phải hỏi người dùng.

Chương này giải thích hình dạng của terminal UI đó và cách nó nằm trên runtime
agent.

## TUI Cần Gì

Ít nhất, giao diện nên làm tốt bốn việc:

1. Cho thấy agent đang làm việc.
2. Render assistant text ngay khi nó xuất hiện.
3. Hiển thị tool usage mà không làm màn hình bị loạn.
4. Dừng sạch sẽ khi agent cần người dùng trả lời một câu hỏi.

Chỉ thế thôi cũng đủ để một coding assistant cảm thấy phản hồi tốt thay vì như
một chương trình bị treo.

## Giao Diện Dựa Trên Event

Track TypeScript giữ UI tách khỏi agent bằng event. Agent emit event; TUI sẽ
quyết định render như thế nào.

Solution package mô hình hóa event đó bằng một discriminated union:

```ts
export type AgentEvent =
  | { kind: "text_delta"; text: string }
  | { kind: "tool_call"; name: string; summary: string }
  | { kind: "done"; text: string }
  | { kind: "error"; error: string };
```

Shape này là cố ý:

- `text_delta` cho phép UI in partial output ngay lập tức.
- `tool_call` cho UI một dòng tóm tắt cho mỗi lần gọi tool.
- `done` báo cho UI tắt spinner và render câu trả lời cuối.
- `error` giữ terminal loop tiếp tục chạy khi model hoặc tool lỗi.

Điều này giữ phần rendering ra khỏi agent loop. Agent lo orchestration; TUI lo
vẽ màn hình.

## Một Terminal Loop Tốt Hơn

Vòng người dùng vẫn đơn giản:

1. Đọc prompt.
2. Push nó vào lịch sử hội thoại.
3. Bắt đầu request của agent.
4. Render tiến trình trong lúc request đang chạy.
5. In câu trả lời cuối khi request hoàn tất.

Điểm khác so với CLI thường là TUI cần quản lý nhiều state hơn:

- bộ đếm frame cho spinner
- vùng buffer text cho output được stream
- số lượng tool call để có thể gộp các dòng ồn ào
- một đường nhập riêng khi `AskTool` tạm dừng run

Trong TypeScript, state này thường nằm trong một module và được điều khiển
bằng callback hoặc async events.

## Chiến Lược Render

Bản Rust dùng `termimad`, `crossterm`, và một event loop riêng để giữ màn hình
sạch. Bản TypeScript có thể đi theo cùng ý tưởng dù terminal library khác:

- render text assistant từng chút một
- gộp tool call lặp lại sau vài dòng đầu
- xóa dòng spinner trước khi in markdown cuối cùng
- vẽ lại spinner khi chunk tiếp theo xuất hiện

Library cụ thể quan trọng ít hơn ranh giới giữa agent event và rendering logic.

## Dừng Khi Cần User Input

Khi model hỏi một câu, UI phải ngừng hành xử như một prompt một lần và trở
thành một bề mặt hội thoại thật sự.

Đó là lý do input tool được tách khỏi agent:

- `AskTool` tạo ra `UserInputRequest`
- TUI sở hữu prompt hoặc widget chọn lựa thật sự
- câu trả lời được gửi ngược qua handler và agent tiếp tục

Rendering loop nên dừng trong lúc input đang active, rồi chạy tiếp ngay khi
có câu trả lời.

## Vị Trí Của Nó Trong Kiến Trúc

Lúc này kiến trúc có ba lớp:

```text
Provider  ->  Agent  ->  UI
```

Provider nói chuyện với model.
Agent xử lý loop và tool execution.
UI xử lý trải nghiệm terminal.

Giữ ba lớp đó tách biệt là điều làm cho các chương sau khả thi.

## Tóm tắt

- TUI chủ yếu là một renderer event nằm trên agent loop.
- Streaming text, tool summaries, và user prompt đều cần cách xử lý riêng.
- UI nên đứng ngoài protocol của agent.
- Khi boundary event đã rõ, bạn có thể cải thiện terminal experience mà không
  cần đụng tới code orchestration của model.

Chương tiếp theo sẽ cho bạn boundary streaming giúp UI này cảm thấy "sống".
