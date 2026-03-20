"""
Demo: Send a LangChain trace to Potato

This script simulates a LangChain agent run and sends the trace
to a running Potato instance. It does NOT require an actual LLM
API key — it uses the callback handler directly to demonstrate
the trace format.

Prerequisites:
    1. Start the Potato server:
       python potato/flask_server.py start examples/agent-traces/langchain-integration/config.yaml -p 8000

    2. Run this script:
       python examples/agent-traces/langchain-integration/demo_agent.py

Usage with a real LangChain agent:

    from langchain_openai import ChatOpenAI
    from langchain.agents import AgentExecutor, create_react_agent
    from potato.integrations.langchain_callback import PotatoCallbackHandler

    handler = PotatoCallbackHandler(potato_url="http://localhost:8000")
    executor = AgentExecutor(agent=agent, tools=tools)
    result = executor.invoke(
        {"input": "What's 2+2?"},
        config={"callbacks": [handler]},
    )
    handler.flush()
"""

import uuid

from potato.integrations.langchain_callback import PotatoCallbackHandler


def simulate_agent_trace(handler: PotatoCallbackHandler):
    """Simulate a LangChain agent execution by calling callback methods directly."""

    root_id = uuid.uuid4()
    llm_id = uuid.uuid4()
    tool_id = uuid.uuid4()
    llm2_id = uuid.uuid4()

    # Root chain starts
    handler.on_chain_start(
        serialized={"name": "AgentExecutor"},
        inputs={"input": "What is the population of Tokyo?"},
        run_id=root_id,
    )

    # LLM decides to use a tool
    handler.on_llm_start(
        serialized={"name": "ChatOpenAI"},
        prompts=["You are a helpful assistant. What is the population of Tokyo?"],
        run_id=llm_id,
        parent_run_id=root_id,
    )

    class FakeGeneration:
        text = 'I should search for the current population of Tokyo. Action: search("population of Tokyo")'

    class FakeResponse:
        generations = [[FakeGeneration()]]

    handler.on_llm_end(response=FakeResponse(), run_id=llm_id, parent_run_id=root_id)

    # Tool execution
    handler.on_tool_start(
        serialized={"name": "search"},
        input_str="population of Tokyo",
        run_id=tool_id,
        parent_run_id=root_id,
    )
    handler.on_tool_end(
        output="Tokyo has a population of approximately 13.96 million people in the city proper.",
        run_id=tool_id,
        parent_run_id=root_id,
    )

    # Final LLM response
    handler.on_llm_start(
        serialized={"name": "ChatOpenAI"},
        prompts=["Based on the search results, answer the question."],
        run_id=llm2_id,
        parent_run_id=root_id,
    )

    class FinalGeneration:
        text = "The population of Tokyo is approximately 13.96 million people."

    class FinalResponse:
        generations = [[FinalGeneration()]]

    handler.on_llm_end(response=FinalResponse(), run_id=llm2_id, parent_run_id=root_id)

    # Root chain ends — this triggers the send
    handler.on_chain_end(
        outputs={"output": "The population of Tokyo is approximately 13.96 million people."},
        run_id=root_id,
    )


if __name__ == "__main__":
    print("Sending simulated LangChain trace to Potato...")
    handler = PotatoCallbackHandler(
        potato_url="http://localhost:8000",
        api_key="",
    )
    simulate_agent_trace(handler)
    handler.flush(timeout=10)
    print("Done! Check http://localhost:8000/annotate to see the trace.")
