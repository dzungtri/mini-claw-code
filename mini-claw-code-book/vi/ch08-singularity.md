# Chương 8: Điểm kỳ dị

Agent của bạn giờ đã có thể tự chỉnh sửa chính nó và bắt đầu tự tiến hóa. Từ
chương này trở đi, bạn không cần tự viết mã nữa.

## Các chương mở rộng

Những chương mở rộng phía sau sẽ dẫn bạn đi qua phần triển khai tham chiếu.
Bạn không cần tự viết lại mã nguồn, hãy đọc để hiểu thiết kế rồi để agent của
bạn tự triển khai tiếp phần còn lại, hoặc tự làm thủ công nếu muốn luyện tập:

- [Chương 9: TUI tốt hơn](./ch09-tui.md) -- render Markdown, spinner và thu gọn các lần gọi tool.
- [Chương 10: Streaming](./ch10-streaming.md) -- stream token khi chúng xuất hiện với `StreamingAgent`.
- [Chương 11: User Input](./ch11-user-input.md) -- cho phép LLM hỏi lại bạn để làm rõ yêu cầu.
- [Chương 12: Plan Mode](./ch12-plan-mode.md) -- chế độ lập kế hoạch chỉ đọc với lớp phê duyệt.

Ngoài các chương mở rộng đó, đây là vài hướng khác bạn có thể khám phá:

- **Tool call song song** -- Thực thi nhiều tool call đồng thời bằng `tokio::join!`.
- **Theo dõi token** -- Cắt bớt các message cũ khi sắp chạm giới hạn context.
- **Thêm nhiều tool hơn** -- Tìm kiếm web, truy vấn cơ sở dữ liệu, gọi HTTP. Trait `Tool` giúp việc này khá dễ.
- **MCP** -- Expose các tool của bạn dưới dạng MCP server hoặc kết nối tới MCP server bên ngoài.
