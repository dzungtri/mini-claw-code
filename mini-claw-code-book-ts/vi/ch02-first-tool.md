# Chương 2: Công cụ đầu tiên của bạn

Bây giờ bạn sẽ xây dựng tool thực sự đầu tiên: `ReadTool`.

Tool này đọc một file từ đĩa và trả về nội dung của nó dưới dạng string. Đây
là một chương nhỏ, nhưng rất quan trọng vì nó giới thiệu toàn bộ contract của
tool:

- tool definition
- đối số của tool
- thực thi tool
- xử lý lỗi

Khi `ReadTool` tồn tại, mô hình có thể xem nội dung file trong dự án thay vì
đoán mò.

## Mục tiêu

Hiện thực `ReadTool` sao cho:

1. nó xuất ra một `ToolDefinition` tên `"read"`
2. nó yêu cầu tham số `"path"` kiểu `"string"`
3. `call()` đọc file từ đĩa và trả về nội dung
4. nó ném lỗi nếu thiếu path hoặc không đọc được file

## Interface `Tool`

Mở `mini-claw-code-starter-ts/src/types.ts`. Interface tool là:

```ts
export interface Tool {
  definition(): ToolDefinition
  call(args: JsonValue): Promise<string>
}
```

Mỗi tool có hai trách nhiệm:

- **`definition()`** nói cho mô hình biết tool tồn tại và cách gọi nó
- **`call(args)`** thực sự làm việc

Sự tách biệt này rất quan trọng.

Mô hình chỉ thấy definition. Runtime của bạn chỉ thấy implementation thật.
Agent loop ở chương sau sẽ nối hai phần đó lại.

## `ReadTool`

Mở `mini-claw-code-starter-ts/src/tools/read.ts`.

Scaffold đã cho sẵn hình dạng class:

```ts
export class ReadTool implements Tool {
  readonly toolDefinition: ToolDefinition

  constructor() {
    this.toolDefinition = ToolDefinition.new(
      "read",
      "Read the contents of a file.",
    ).param("path", "string", "The file path to read", true)
  }

  definition(): ToolDefinition {
    return this.toolDefinition
  }

  async call(_args: JsonValue): Promise<string> {
    throw new Error("TODO...")
  }
}
```

Bạn chỉ cần hoàn thiện logic runtime.

## Các khái niệm TypeScript quan trọng

### Thu hẹp `JsonValue`

API tool nhận vào `JsonValue`, vì đối số tool có dạng JSON.

Điều đó có nghĩa là `args` không tự động được biết là một object có trường
`path`. Bạn cần thu hẹp kiểu trước.

Mẫu thường dùng:

```ts
if (
  typeof args !== "object" ||
  args === null ||
  Array.isArray(args) ||
  typeof args.path !== "string"
) {
  throw new Error("missing 'path' argument")
}
```

Đây là phiên bản TypeScript của việc validate JSON input trước khi tin nó.

### `node:fs/promises`

Implementation dùng:

```ts
import { readFile } from "node:fs/promises"
```

`readFile(path, "utf8")` trả về `Promise<string>`, nên nó khớp tự nhiên với
contract của `Tool`.

## Phần hiện thực

Mở `mini-claw-code-starter-ts/src/tools/read.ts`.

### Bước 1: Validate đối số

Tham số `path` phải tồn tại và phải là string.

Nếu shape của đối số sai, hãy ném lỗi mô tả rõ ràng, ví dụ:

```ts
throw new Error("missing 'path' argument")
```

Thông báo này hữu ích vì ở các chương sau, lỗi tool sẽ được bắt lại và trả về
cho mô hình dưới dạng tool result.

### Bước 2: Đọc file

Khi `path` đã biết chắc là string:

```ts
return readFile(path, "utf8")
```

Thế là đủ.

Nếu file không tồn tại, `readFile` sẽ reject và tool call thất bại. Điều đó ổn.
Bạn không cần logic recovery riêng trong tool này.

## Vì sao trả nội dung file dưới dạng string?

Vì mô hình làm việc với text.

Dù tool là "đọc file", mục tiêu thực sự là:

> "Biến một thứ ở thế giới bên ngoài thành text để mô hình có thể suy nghĩ."

Mẫu đó sẽ xuất hiện lặp đi lặp lại:

- `read` biến nội dung file thành text
- `bash` biến output của command thành text
- `ask_user` biến input của người dùng thành text

Mô hình luôn làm việc bằng cách nhận thêm text context.

## Chạy test

Chạy test của Chương 2:

```bash
bun test mini-claw-code-starter-ts/tests/ch2.test.ts
```

### Test xác minh gì?

- tool definition có tên `"read"`
- tham số `path` là bắt buộc
- tool trả về nội dung file

Chương này cố tình rất nhỏ. Nó là ví dụ tối thiểu cho pattern tool.

## Tóm tắt

- Một tool có hai nửa: schema và hành vi runtime.
- `ReadTool` là ví dụ cụ thể đầu tiên của interface tool.
- Đối số tool đến dưới dạng JSON tổng quát và phải được thu hẹp trước khi dùng.
- Mô hình không tự đọc file; runtime của bạn làm việc đó và trả text về.

Ở chương sau, bạn sẽ nối tool này với provider lần đầu tiên.
