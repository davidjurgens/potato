"""
Example: instrument an agent with the potato_trace SDK.

Run a Potato server with examples/agent-traces/sdk-capture/config.yaml, then:

    POTATO_TRACE_URL=http://localhost:8000 python examples/agent-traces/sdk-capture/agent.py

Each traced run is captured as a nested run tree and POSTed to Potato's
trace-ingestion webhook, where it becomes an item to evaluate.
"""

import os

import potato_trace

# Reads POTATO_TRACE_URL / POTATO_TRACE_API_KEY from the environment by default;
# you can also pass them explicitly here.
potato_trace.configure(
    potato_url=os.environ.get("POTATO_TRACE_URL", "http://localhost:8000"),
    project_name="sdk-capture-demo",
)


@potato_trace.traceable(run_type="tool")
def search(query: str) -> str:
    # pretend to call a search tool
    return f"top result for '{query}'"


@potato_trace.traceable(run_type="llm")
def summarize(text: str) -> str:
    # pretend to call an LLM; attach token usage for the trace
    potato_trace.add_metadata(prompt_tokens=12, completion_tokens=8)
    return f"summary: {text[:40]}"


@potato_trace.traceable  # the outermost call is the trace root
def agent(task: str) -> str:
    hits = search(task)
    return summarize(hits)


if __name__ == "__main__":
    for task in ["weather in NYC", "best pizza in Chicago", "capital of France"]:
        answer = agent(task)
        print(f"{task!r} -> {answer}")
    # Ensure background sends finish before the script exits.
    potato_trace.flush()
    print("\nTraces sent. Open the Potato UI to evaluate the captured runs.")
