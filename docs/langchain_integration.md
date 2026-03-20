# LangChain Integration

Automatically send LangChain agent traces to Potato for human evaluation and annotation.

## Installation

```bash
pip install potato-annotation[langchain]
# or
pip install langchain-core>=0.1.0
```

## Quick Start

```python
from langchain_openai import ChatOpenAI
from langchain.agents import AgentExecutor, create_react_agent
from potato.integrations.langchain_callback import PotatoCallbackHandler

# Create the callback handler
handler = PotatoCallbackHandler(
    potato_url="http://localhost:8000",
    api_key="your-api-key",  # optional, matches trace_ingestion.api_key in config
)

# Use with any LangChain chain or agent
llm = ChatOpenAI(model="gpt-4")
agent = create_react_agent(llm, tools, prompt)
executor = AgentExecutor(agent=agent, tools=tools)

result = executor.invoke(
    {"input": "What's the weather in NYC?"},
    config={"callbacks": [handler]},
)

# Ensure trace is sent before program exits
handler.flush()
```

## How It Works

1. The callback handler hooks into LangChain's callback system
2. It collects all run events (chain, LLM, tool, retriever starts/ends)
3. When the root chain completes, it POSTs the trace to Potato's `/api/traces/langsmith` endpoint
4. Potato normalizes the trace and adds it to the annotation queue
5. Annotators can then evaluate the agent's behavior

## Configuration

### Handler Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `potato_url` | (required) | Base URL of your Potato server |
| `api_key` | `""` | API key for webhook authentication |
| `endpoint` | `/api/traces/langsmith` | Webhook endpoint path |
| `send_timeout` | `10` | HTTP timeout in seconds |
| `metadata` | `{}` | Extra metadata attached to traces |

### Potato Server Configuration

Enable trace ingestion in your Potato config:

```yaml
# Trace ingestion configuration
trace_ingestion:
  enabled: true
  api_key: "your-api-key"  # must match handler's api_key
  notify_annotators: true   # send SSE notifications
```

## Advanced Usage

### Reusing the Handler

Call `reset()` between chains to start fresh:

```python
handler = PotatoCallbackHandler(potato_url="http://localhost:8000")

for task in tasks:
    handler.reset()
    result = chain.invoke(task, config={"callbacks": [handler]})

handler.flush()
```

### Custom Metadata

```python
handler = PotatoCallbackHandler(
    potato_url="http://localhost:8000",
    metadata={
        "experiment": "v2",
        "model": "gpt-4-turbo",
    },
)
```

### Error Handling

The handler never raises exceptions that would interrupt your chain. Errors are logged:

```python
import logging
logging.getLogger("potato.integrations.langchain_callback").setLevel(logging.DEBUG)
```

## Payload Format

The handler sends traces in LangSmith format, which Potato's webhook receiver already understands:

```json
{
  "runs": [
    {
      "id": "uuid",
      "parent_run_id": null,
      "run_type": "chain",
      "name": "AgentExecutor",
      "inputs": {"input": "..."},
      "outputs": {"output": "..."},
      "status": "completed",
      "latency": 2.5
    },
    {
      "id": "uuid",
      "parent_run_id": "parent-uuid",
      "run_type": "tool",
      "name": "search",
      "inputs": {"input": "query"},
      "outputs": {"output": "results"},
      "status": "completed",
      "latency": 0.8
    }
  ]
}
```

## Example Project

See `examples/agent-traces/langchain-integration/` for a complete working example:

```bash
# Start the Potato server
python potato/flask_server.py start examples/agent-traces/langchain-integration/config.yaml -p 8000

# Run the demo agent (in another terminal)
python examples/agent-traces/langchain-integration/demo_agent.py
```

## Related Documentation

- [Agent Trace Evaluation](../examples/agent-traces/agent-trace-evaluation/) — annotation schemas for agent evaluation
- [Webhook Receiver](../potato/trace_ingestion/) — trace ingestion internals
