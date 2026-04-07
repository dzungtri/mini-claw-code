# Chương 6: Provider Tương Thích OpenAI

Cho tới lúc này, mọi thứ đều chạy cục bộ với `MockProvider`. Trong chương này,
bạn sẽ triển khai `OpenAICompatibleProvider` - provider nói chuyện với một mô
hình thật qua HTTP bằng OpenAI-compatible chat completions API.

Đây là chương làm cho agent của bạn trở nên thật sự hữu ích.

## Mục tiêu

Triển khai `OpenAICompatibleProvider` trong `mini-claw-code-starter-ts` sao cho
provider này:

1. Có thể được tạo từ API key và tên model.
2. Chuyển đổi các giá trị `Message` và `ToolDefinition` nội bộ sang định dạng API.
3. Gửi HTTP `POST` tới endpoint chat completions.
4. Phân tích phản hồi trở lại thành `AssistantTurn`.

## Vì sao chỉ cần một provider?

Track TypeScript dùng một abstraction provider duy nhất vì cả OpenAI lẫn
Gemini đều có thể đi qua cùng một dạng OpenAI-compatible. Điều đó giữ cho code
agent đơn giản:

- `baseUrl` trỏ tới OpenAI hoặc Gemini.
- `apiKey` lấy từ biến môi trường tương ứng.
- `model` lấy từ cấu hình hoặc môi trường.

Phần còn lại của agent không cần biết phía sau interface là nhà cung cấp nào.

## Vì sao dùng `fetch()`?

Bun cung cấp sẵn `fetch` toàn cục, nên provider không cần thêm một thư viện HTTP
khác. Điều này giữ bề mặt phụ thuộc rất nhỏ và giúp luồng request dễ đọc hơn:

```ts
const response = await fetch(`${this.baseUrl}/chat/completions`, {
  method: "POST",
  headers: {
    Authorization: `Bearer ${this.apiKey}`,
    "Content-Type": "application/json",
  },
  body: JSON.stringify(payload),
});
```

Luồng này gần như tương ứng trực tiếp với bản Rust: xây payload, gửi đi, kiểm
tra trạng thái, parse JSON, rồi chuyển phản hồi về kiểu nội bộ của bạn.

## Các dạng API

Mở `mini-claw-code-starter-ts/src/providers/openai-compatible.ts`. File này đã
có sẵn các helper types cho wire format:

```ts
type ChatRequest = {
  model: string;
  messages: ApiMessage[];
  tools: ApiTool[];
};

type ApiMessage = {
  role: "system" | "user" | "assistant" | "tool";
  content?: string;
  tool_calls?: ApiToolCall[];
  tool_call_id?: string;
};

type ApiToolCall = {
  id: string;
  type: "function";
  function: {
    name: string;
    arguments: string;
  };
};

type ApiTool = {
  type: "function";
  function: {
    name: string;
    description: string;
    parameters: unknown;
  };
};
```

Những helper này chỉ dùng cho wire protocol. Phần còn lại của code vẫn dùng mô
hình discriminated union sạch hơn từ Chương 1.

Shape này khớp với OpenAI-compatible chat completions API:

- `messages` là lịch sử hội thoại
- `tools` mô tả các tool mà model có thể gọi
- `tool_calls` quay về khi model muốn một kết quả từ tool
- `finish_reason` cho biết model đã dừng hay yêu cầu tool

## Khái niệm TypeScript

### Shape đối tượng chính xác

TypeScript cho phép bạn mô tả chính xác shape của API. Điều đó hữu ích ở đây vì
payload JSON có một vài field chỉ nên xuất hiện khi thật sự cần.

Khi một field không dùng tới, tốt nhất là bỏ hẳn nó ra khỏi object thay vì ép
thành `undefined` hoặc `null`. Như vậy wire format sẽ khớp với API hơn và code
chuyển đổi cũng dễ hiểu hơn.

### Chuyển đổi JSON

Provider phải nối hai thế giới:

- Các kiểu nội bộ `Message`, `ToolDefinition`, `AssistantTurn`
- Định dạng JSON request/response mà model API dùng

Trong TypeScript, việc chuyển đổi này là tường minh và cơ học. Bạn sẽ dùng
`JSON.stringify()` khi gửi tham số tool và `JSON.parse()` khi đọc chúng về.

### Biến môi trường

Starter TypeScript dùng trực tiếp `process.env`. Bun tự load các file `.env`,
nên sinh viên chỉ cần đặt API key ở root workspace là có thể chạy ví dụ của
chương mà không cần cấu hình thêm.

## Provider cần làm gì

Starter file đã cho sẵn chữ ký method. Việc của bạn là làm cho chúng hoạt động:

```ts
export class OpenAICompatibleProvider implements Provider {
  static new(apiKey: string, model: string, baseUrl?: string): OpenAICompatibleProvider
  withBaseUrl(url: string): OpenAICompatibleProvider
  static fromEnv(model = "gpt-4.1-mini"): OpenAICompatibleProvider
  static convertMessages(messages: Message[]): ApiMessage[]
  static convertTools(tools: ToolDefinition[]): ApiTool[]
  async chat(messages: Message[], tools: ToolDefinition[]): Promise<AssistantTurn>
}
```

Shape này gần như map 1-1 với chương Rust:

1. constructor
2. builder cho base URL
3. constructor dựa trên environment
4. chuyển đổi message
5. chuyển đổi tool
6. vòng request/response

## Bước 1: `new()`

Khởi tạo ba field:

```ts
constructor(
  readonly apiKey: string,
  readonly model: string,
  readonly baseUrl = "https://api.openai.com/v1",
) {}
```

Base URL mặc định trỏ tới OpenAI. Hàm `withBaseUrl()` có thể đổi sang endpoint
Gemini-compatible sau.

## Bước 2: `withBaseUrl()`

Hàm này nên trả về một provider mới với cùng API key và model nhưng endpoint
mới:

```ts
withBaseUrl(url: string): OpenAICompatibleProvider {
  return new OpenAICompatibleProvider(this.apiKey, this.model, url);
}
```

Builder nhỏ này quan trọng vì nó giữ constructor đơn giản nhưng vẫn cho phép
book nói về nhiều vendor.

## Bước 3: `fromEnv()`

Bản starter giữ logic môi trường khá gọn. Một cách làm thực tế có thể:

1. Đọc API key từ `OPENAI_API_KEY` hoặc `GEMINI_API_KEY`.
2. Dùng model mặc định nếu môi trường không ghi đè.
3. Dùng `withBaseUrl()` nếu key đến từ Gemini.

Điều quan trọng không phải là chính xác tên biến nào, mà là provider phải có
thể cấu hình được mà không cần thay đổi phần còn lại của agent.

## Bước 4: `convertMessages()`

Method này chuyển `Message` nội bộ sang format message của API. Logic nhỏ
nhưng rất quan trọng:

- `system` trở thành `{ role: "system", content: text }`
- `user` trở thành `{ role: "user", content: text }`
- `assistant` trở thành `{ role: "assistant", content, tool_calls? }`
- `tool_result` trở thành `{ role: "tool", content, tool_call_id }`

Nhánh `assistant` là nhánh phức tạp nhất vì tool call phải được serialize:

```ts
{
  id: call.id,
  type: "function",
  function: {
    name: call.name,
    arguments: JSON.stringify(call.arguments),
  },
}
```

Nếu `toolCalls` rỗng, hãy bỏ hẳn field đó ra khỏi object.

## Bước 5: `convertTools()`

Map từng `ToolDefinition` sang format tool của API:

```ts
{
  type: "function",
  function: {
    name: tool.name,
    description: tool.description,
    parameters: tool.parameters,
  },
}
```

Đây là cùng một ý tưởng như bản Rust: model cần đủ thông tin schema để biết
nó có thể cung cấp những argument nào.

## Bước 6: `chat()`

Đây là method chính. Nó nối toàn bộ provider lại với nhau:

1. Xây một `ChatRequest`.
2. Gửi tới `${baseUrl}/chat/completions`.
3. Kiểm tra lỗi HTTP.
4. Parse phản hồi thành JSON.
5. Chuyển choice đầu tiên thành `AssistantTurn`.

Phần chuyển tool call là quan trọng nhất. API trả arguments dưới dạng chuỗi,
bạn cần parse ngược chúng lại thành JSON value:

```ts
const toolCalls = (choice.message.tool_calls ?? []).map((call) => ({
  id: call.id,
  name: call.function.name,
  arguments: JSON.parse(call.function.arguments),
}));
```

Sau đó map `finish_reason` sang `stopReason` nội bộ:

- `"tool_calls"` trở thành `"tool_use"`
- giá trị khác thì trở thành `"stop"`

## Ghi chú triển khai

Giữ logic của provider thật nhỏ và thật rõ:

- xây request bằng object JavaScript bình thường
- dùng `JSON.stringify()` ở ranh giới gửi đi
- dùng `await response.json()` khi đọc kết quả
- giữ các chi tiết riêng của model trong cấu hình, không nhét vào agent loop

Như vậy provider sẽ dễ test và dễ mở rộng hơn.

## Kiểm thử

Chạy các test của Chapter 6:

```bash
bun test mini-claw-code-starter-ts/tests/ch6.test.ts
```

Những test này kiểm tra:

- chuyển đổi tool definition
- chuyển đổi message
- khởi tạo từ environment
- toàn bộ luồng `chat()` từ request tới response

Các test dùng mock server cục bộ nên không cần API key thật.

## Tóm tắt

Bạn vừa xây một HTTP provider thật sự:

- khởi tạo từ API key và tên model
- chuyển đổi qua lại giữa kiểu nội bộ và JSON tương thích OpenAI
- gửi request HTTP và parse response
- dùng cùng một abstraction cho OpenAI và Gemini

Những pattern quan trọng là:

- `fetch()` cho lớp HTTP
- chuyển đổi JSON rõ ràng ở ranh giới
- provider interface nhỏ để giữ phần còn lại của agent sạch sẽ

Tiếp theo, bạn sẽ nối provider này vào một CLI chat loop.
