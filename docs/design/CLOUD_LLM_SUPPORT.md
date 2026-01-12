# Cloud LLM Support Design

Enable API key authentication for OpenAI and other cloud-based LLM providers.

## Current State

- `LLMModelConfig` has an `api_key` field but it's not documented in the example YAML
- The `vllm` provider uses `/v1/completions` endpoint (legacy completions API)
- OpenAI chat models require `/v1/chat/completions` endpoint
- No support for environment variable substitution in YAML configs

## Todo List

- [x] Add `openai` provider to LLM client with chat completions API support
- [x] Update YAML config example to show api_key fields
- [x] Add environment variable fallback for api_key (e.g., `OPENAI_API_KEY`)
- [x] Test config loading and validation
- [x] Test with actual OpenAI API (requires real key)
- [x] Document configuration in CLAUDE.md

## Implementation

### 1. Add OpenAI Provider to LLM Client

Update `src/yonk_code_robomonkey/llm/client.py` to add an `openai` provider that uses:
- `/v1/chat/completions` endpoint
- Messages array format (not raw prompt)
- Bearer token auth via `api_key`

### 2. Update YAML Config Example

Add `api_key` to the LLM section in `config/robomonkey-daemon.yaml`:

```yaml
llm:
  deep:
    provider: "openai"  # or "ollama" or "vllm"
    model: "gpt-4o"
    base_url: "https://api.openai.com"
    api_key: "${OPENAI_API_KEY}"  # Or hardcoded value
    temperature: 0.3
    max_tokens: 4000

  small:
    provider: "openai"
    model: "gpt-4o-mini"
    base_url: "https://api.openai.com"
    api_key: "${OPENAI_API_KEY}"
    temperature: 0.3
    max_tokens: 1000
```

### 3. Environment Variable Fallback

For the `api_key` field, check environment variables:
- `OPENAI_API_KEY` for OpenAI
- `LLM_API_KEY` as generic fallback

### 4. Provider Support Matrix

| Provider | Endpoint | Auth | Format |
|----------|----------|------|--------|
| ollama | `/api/generate` | None | `{"prompt": ...}` |
| vllm | `/v1/completions` | Bearer | `{"prompt": ...}` |
| openai | `/v1/chat/completions` | Bearer | `{"messages": [...]}` |

## Notes

- The embeddings already support vLLM with api_key via `embeddings.vllm.api_key`
- For backwards compatibility, `vllm` provider stays as `/v1/completions`
- Consider supporting Anthropic API in the future

---

## Implementation Details

### Changes Made

**1. `src/yonk_code_robomonkey/llm/client.py`**
- Added `openai` provider handling in `call_llm()` function
- Uses `/v1/chat/completions` endpoint with messages array format
- Falls back to `OPENAI_API_KEY` env var if `api_key` not in config
- Also updated `vllm` provider to fall back to `VLLM_API_KEY` env var

**2. `src/yonk_code_robomonkey/config/daemon.py`**
- Updated `LLMModelConfig.provider` to accept `"openai"` in addition to `"ollama"` and `"vllm"`
- Updated description for `api_key` field

**3. `config/robomonkey-daemon.yaml`**
- Added documentation comments showing how to configure OpenAI
- Added commented `api_key` fields to deep/small model configs

### Usage

To use OpenAI instead of Ollama:

```yaml
llm:
  deep:
    provider: "openai"
    model: "gpt-4o"
    base_url: "https://api.openai.com"
    api_key: "sk-..."  # Or set OPENAI_API_KEY env var
    temperature: 0.3
    max_tokens: 4000
```

Or set the environment variable:
```bash
export OPENAI_API_KEY="sk-..."
```

### Compatible Providers

The `openai` provider works with any OpenAI-compatible API:
- OpenAI (api.openai.com)
- Azure OpenAI
- Together.ai
- Groq
- Local vLLM with chat completions enabled
- Any `/v1/chat/completions` compatible endpoint
