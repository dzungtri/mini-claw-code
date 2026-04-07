# Tổng quan

Chào mừng bạn đến với *Xây dựng trợ lý lập trình mini của riêng bạn bằng
TypeScript*. Trong bảy chương tiếp theo, bạn sẽ tự tay xây dựng một agent lập
trình mini từ đầu -- một phiên bản nhỏ của những công cụ như Claude Code hay
OpenCode -- một chương trình nhận prompt, trò chuyện với mô hình ngôn ngữ lớn
(LLM), và dùng *tool* để tương tác với thế giới thực. Sau đó, một loạt chương
mở rộng sẽ bổ sung streaming, TUI, nhập từ người dùng, chế độ lập kế hoạch,
subagent, và nhiều hơn nữa.

Khi hoàn thành cuốn sách này, bạn sẽ có một agent có thể chạy lệnh shell, đọc
và ghi file, sửa mã nguồn, và hỏi lại người dùng khi cần, tất cả đều được điều
khiển bởi một LLM. Bạn không cần API key cho đến Chương 6. Khi đến đó, tầng
provider được thiết kế để sinh viên có thể dùng trực tiếp OpenAI hoặc Gemini
thông qua một endpoint tương thích OpenAI.

## Agent AI là gì?

Một LLM đứng một mình chỉ là một hàm: đầu vào là text, đầu ra là text. Hãy yêu
cầu nó tóm tắt `doc.pdf` và nó sẽ либо từ chối, либо bịa ra câu trả lời -- nó
không có cách nào mở file đó.

**Agent** giải quyết điều này bằng cách trao cho LLM **tool**. Một tool chỉ là
một hàm mà code của bạn có thể chạy -- đọc file, thực thi lệnh shell, gọi API,
hoặc hỏi người dùng. Agent vận hành trong một vòng lặp:

1. Gửi prompt của người dùng cho LLM.
2. LLM quyết định cần tool nào đó và xuất ra một tool call.
3. Code của bạn thực thi tool đó và đẩy kết quả trở lại.
4. LLM nhìn thấy thông tin mới và либо trả lời, либо yêu cầu tool khác.

LLM không bao giờ chạm trực tiếp vào filesystem. Nó chỉ *yêu cầu*, còn code
của bạn mới là thứ *thực hiện*. Vòng lặp đó -- hỏi, thực thi, phản hồi -- chính
là toàn bộ ý tưởng.

## LLM dùng tool như thế nào?

Một LLM không thể tự chạy code. Nó chỉ là bộ sinh văn bản. Vì vậy, "gọi tool"
thực ra nghĩa là LLM *xuất ra một yêu cầu có cấu trúc* và code của bạn làm phần
còn lại.

Khi gửi request tới LLM, bạn kèm theo một danh sách **tool definition** cùng
với cuộc trò chuyện. Mỗi definition có:

- một tên
- một mô tả
- một object JSON Schema mô tả đối số của nó

Sau đó mô hình có thể trả lời theo hai cách:

1. Nó có thể dừng và trả về text thuần.
2. Nó có thể dừng và trả về một hoặc nhiều tool call.

Runtime của bạn sẽ kiểm tra phản hồi đó, thực thi các tool call, và nối kết quả
vào lịch sử hội thoại.

Đó là lý do code của agent lại nhỏ đến vậy. Mô hình làm phần suy luận. Chương
trình của bạn chỉ cần triển khai protocol và các tool.

## Vì sao là TypeScript?

Bản Rust của cuốn sách này dùng traits, enums, và async runtime để dạy cùng
một kiến trúc. Trong bản này, chúng ta giữ nguyên ý tưởng nhưng biểu đạt bằng
Bun và TypeScript:

- **Discriminated union** đại diện cho message và event của cuộc trò chuyện.
- **`Promise` + `async` / `await`** thay cho future trả về từ trait.
- **`Map<string, Tool>`** cho tra cứu tool với độ phức tạp O(1).
- **`fetch()` toàn cục** và API runtime của Bun giúp provider nhỏ gọn.
- **Bun test runner** giúp mỗi chương đều dễ kiểm tra.

Bản TypeScript không phải là một "bản port đồ chơi". Nó dạy cùng một thiết kế
agent, chỉ là theo cách quen thuộc hơn với sinh viên đang viết JavaScript và
TypeScript.

## Bạn sẽ xây dựng gì?

Bảy chương đầu là phần thực hành:

- **Chương 1** giới thiệu các kiểu protocol và một mock provider.
- **Chương 2** xây dựng tool đầu tiên của bạn: `read`.
- **Chương 3** triển khai luồng tool call một lượt.
- **Chương 4** thêm các tool khác: `bash`, `write`, và `edit`.
- **Chương 5** xây dựng vòng lặp agent.
- **Chương 6** thêm một HTTP provider thật.
- **Chương 7** biến nó thành một chương trình chat CLI.

Sau đó, các chương mở rộng sẽ bao gồm:

- một terminal UI tốt hơn
- streaming
- nhập từ người dùng
- chế độ lập kế hoạch
- subagent
- an toàn và các hướng phát triển tiếp theo

## Cấu trúc dự án

Kho mã này hiện chứa cả track Rust gốc lẫn track TypeScript. Phần TypeScript
được chia thành ba package:

```text
mini-claw-code-book-ts/          # cuốn sách này
mini-claw-code-starter-ts/       # code khởi đầu để sinh viên hoàn thiện
mini-claw-code-ts/               # bản triển khai hoàn chỉnh
```

Cấu trúc này tương tự phiên bản Rust:

- package **starter** cố ý còn dang dở
- package **solution** là bản triển khai tham chiếu
- cuốn **book** giải thích các khái niệm và chỉ đúng file cần sửa

Bạn sẽ làm việc nhiều nhất trong `mini-claw-code-starter-ts/` trong khi dùng
`mini-claw-code-ts/` làm đích kiến trúc hoàn chỉnh.

## Quyết định thiết kế chính

Cuốn sách này cố ý giữ mọi thứ tối giản. Nó không bắt đầu bằng framework, state
machine library, ứng dụng React, hay database. Nó bắt đầu từ thứ nhỏ nhất có
thể hoạt động:

- một provider interface
- một tool interface
- một message history
- một agent loop

Hạt nhân nhỏ đó đủ để dạy kiến trúc một cách rõ ràng. Khi đã hiểu nó, mọi thứ
còn lại trong các agent cấp độ production sẽ giống như một phần mở rộng chứ
không phải ma thuật.

## Bạn nên biết gì trước?

Bạn không cần là chuyên gia AI hay hệ thống phân tán. Nhưng bạn cần biết một
vài thứ cơ bản:

- cú pháp TypeScript
- `async` / `await`
- các API file và process của Node/Bun ở mức khái quát
- kiến thức nền về JSON và HTTP

Nếu bạn đọc được class, interface, union, và Promise trong TypeScript, bạn đã
sẵn sàng.

## Cách dùng cuốn sách này

Với Chương 1-7:

1. Đọc chương.
2. Mở file tương ứng trong `mini-claw-code-starter-ts/`.
3. Tự hiện thực phần còn thiếu.
4. Chạy test của chương đó.

Các chương sau là tài liệu tham khảo và mở rộng. Bạn có thể tiếp tục tự triển
khai chúng hoặc đọc code hoàn chỉnh trong `mini-claw-code-ts/`.

## Mục tiêu cuối cùng

Khi hoàn thành Chương 7, bạn sẽ đã xây dựng được một agent thật sự. Nó sẽ nhỏ,
nhưng không hề giả:

- nó sẽ gọi được provider mô hình thật
- nó sẽ thực thi được tool thật
- nó sẽ giữ được lịch sử hội thoại
- nó sẽ hồi phục sau lỗi của tool

Như vậy là đủ để hiểu agent software thực sự hoạt động thế nào.
