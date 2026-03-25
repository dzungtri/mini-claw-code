# Chapter 6: The OpenRouter Provider

So far everything used `MockProvider`. In this chapter you build the real HTTP
provider.

Open `mini-claw-code-starter-py/src/mini_claw_code_starter_py/providers/openrouter.py`.

## Goal

Implement `OpenRouterProvider` so that it:

1. stores an API key, model, and base URL
2. converts internal messages to OpenAI-compatible JSON
3. converts tool definitions to API tool schemas
4. sends a POST request to `/chat/completions`
5. converts the response back into `AssistantTurn`

## Python HTTP stack

The reference implementation uses `httpx.AsyncClient`:

```python
response = await client.post(
    f"{self.base_url}/chat/completions",
    headers={"Authorization": f"Bearer {self.api_key}"},
    json=body,
)
response.raise_for_status()
payload = response.json()
```

## Message conversion

The mapping matches the Rust version:

- `Message.system(...)` -> role `"system"`
- `Message.user(...)` -> role `"user"`
- `Message.assistant(turn)` -> role `"assistant"`
- `Message.tool_result(...)` -> role `"tool"`

Tool arguments must be JSON strings on the wire:

```python
json.dumps(call.arguments)
```

And parsed back on the way in:

```python
json.loads(raw_arguments)
```

## Environment support

The Python port supports both:

- `OPENROUTER_API_KEY`
- `OPENAI_API_KEY`

That matches the reference code and lets you point the same provider at either
OpenRouter or OpenAI-compatible endpoints.

## Run the tests

```bash
cd mini-claw-code-starter-py
PYTHONPATH=src python -m pytest tests/test_ch6.py
```
