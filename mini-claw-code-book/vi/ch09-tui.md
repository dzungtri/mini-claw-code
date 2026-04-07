# Chương 9: Một TUI tốt hơn

CLI `chat.rs` đã hoạt động, nhưng nó chỉ in văn bản thuần và hiển thị mọi lần
gọi tool. Một coding agent đúng nghĩa nên có khả năng render Markdown, có
spinner lúc suy nghĩ, và tự thu gọn các tool call khi agent làm việc quá nhiều.

Xem phần triển khai tham chiếu tại `mini-claw-code/examples/tui.rs`. Nó sử dụng:

- **`termimad`** để render Markdown trực tiếp trong terminal.
- **`crossterm`** cho raw terminal mode (được dùng cho giao diện chọn bằng phím mũi tên ở Chương 11).
- **Spinner động** (`⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏`) quay trong lúc agent đang suy nghĩ.
- **Thu gọn tool call**: sau 3 lần gọi tool, những lần tiếp theo sẽ được gộp thành bộ đếm `... and N more` để đầu ra gọn hơn.

TUI này được xây trên luồng `AgentEvent` của `StreamingAgent` (Chương 10). Vòng
lặp sự kiện dùng `tokio::select!` để ghép ba nguồn vào cùng một nơi:

1. **Sự kiện từ agent** (`AgentEvent::TextDelta`, `ToolCall`, `Done`, `Error`) --
   render phần text đang stream, tóm tắt tool call, hoặc đầu ra cuối cùng.
2. **Yêu cầu nhập liệu từ người dùng** của `AskTool` (Chương 11) -- tạm dừng
   spinner rồi hiển thị ô nhập text hoặc danh sách chọn bằng phím mũi tên.
3. **Timer tick** -- cập nhật hoạt ảnh của spinner.

Chương này chỉ để giải thích, không có mã cần viết. Hãy đọc `examples/tui.rs`
để thấy các thành phần ghép với nhau ra sao, hoặc yêu cầu agent
`mini-claw-code` của bạn tự xây một TUI cho bạn.
