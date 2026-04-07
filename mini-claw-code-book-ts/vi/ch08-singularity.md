# Chương 8: Điểm Kỳ Dị

Đây là khoảng dừng ngắn sau khi bạn đã xây xong toàn bộ lõi đầu tiên.

Lúc này bạn đã có những thành phần quan trọng:

- message và tool call có kiểu rõ ràng
- một tool registry
- một provider có thể nói chuyện với OpenAI hoặc Gemini
- một helper cho single-turn
- một agent có loop
- một CLI hoạt động được

Phần còn lại của cuốn sách sẽ thêm các lớp hoàn thiện runtime và các ràng buộc
an toàn. Đây là lúc phần mềm agent ngừng là một demo và bắt đầu thật sự hữu
ích trong dự án thực tế.

## Điều cần nhớ

Model không phải là chương trình. Chương trình là vòng lặp bao quanh model.
Vòng lặp đó cho bạn kiểm soát, an toàn, khả năng quan sát và khả năng test.

## Sắp tới có gì

Những chương tiếp theo sẽ thêm:

- streaming output
- UX terminal tốt hơn
- user input tool
- plan mode
- subagents
- tích hợp tool bên ngoài
- safety rails

## Vì sao khoảng dừng này quan trọng

Kiến trúc đã hoàn chỉnh ở nửa đầu cuốn sách. Từ đây trở đi, bạn không đổi ý
tưởng cốt lõi nữa. Bạn chỉ đang mở rộng nó:

- streaming làm agent có cảm giác "sống"
- TUI làm tương tác dễ đọc hơn
- user input cho phép model hỏi lại khi thiếu dữ kiện
- plan mode tách giai đoạn khám phá và giai đoạn thay đổi
- subagents giúp chia nhỏ công việc phức tạp

Đó là hình dạng của phần mềm agent thật: một lõi nhỏ, ổn định, và các extension
chuyên biệt bao quanh nó.
