#!/usr/bin/env python3
"""
Generate real LangChain agent traces using Ollama local server.

Uses the qwen3:4b model to generate actual ReAct agent traces,
then saves them in LangChain format for testing the trace converter.
"""

import json
import os
import sys

from langchain_ollama import ChatOllama
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from langchain_core.tools import tool


@tool
def search_web(query: str) -> str:
    """Search the web for information."""
    # Simulated search results
    results = {
        "python list comprehension": "List comprehensions provide a concise way to create lists. Syntax: [expr for item in iterable if condition]",
        "weather paris": "Paris weather: 15°C, partly cloudy, humidity 65%",
        "capital of france": "The capital of France is Paris.",
    }
    for key, val in results.items():
        if key in query.lower():
            return val
    return f"Search results for '{query}': No specific results found. General information available."


@tool
def calculator(expression: str) -> str:
    """Evaluate a mathematical expression."""
    try:
        result = eval(expression, {"__builtins__": {}}, {})
        return f"Result: {result}"
    except Exception as e:
        return f"Error evaluating '{expression}': {e}"


@tool
def get_current_time() -> str:
    """Get the current date and time."""
    from datetime import datetime
    return f"Current time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"


def generate_traces(output_dir: str):
    """Generate LangChain agent traces and save in multiple formats."""

    llm = ChatOllama(
        model="qwen3:4b",
        temperature=0.3,
        num_predict=512,
    )

    tools = [search_web, calculator, get_current_time]
    llm_with_tools = llm.bind_tools(tools)

    tasks = [
        "What is the capital of France and what is the current weather there?",
        "Calculate 25 * 17 + 33 and tell me if the result is a prime number.",
        "What time is it right now?",
    ]

    all_traces_langchain = []
    all_traces_react = []

    for i, task in enumerate(tasks):
        print(f"\n{'='*60}")
        print(f"Task {i+1}: {task}")
        print(f"{'='*60}")

        trace_steps = []
        messages = [HumanMessage(content=task)]

        # Run agent loop (max 5 steps to avoid infinite loops)
        for step in range(5):
            print(f"\n--- Step {step+1} ---")
            try:
                response = llm_with_tools.invoke(messages)
            except Exception as e:
                print(f"  LLM invocation error: {e}")
                trace_steps.append({
                    "thought": f"Error invoking LLM: {e}",
                    "action": "error",
                    "observation": str(e),
                })
                break

            # Extract thought from content (before tool calls)
            thought = response.content if response.content else ""
            # Strip <think> tags if present (qwen3 pattern)
            if "<think>" in thought:
                import re
                think_match = re.search(r"<think>(.*?)</think>", thought, re.DOTALL)
                if think_match:
                    thought = think_match.group(1).strip()

            print(f"  Thought: {thought[:200]}...")

            if response.tool_calls:
                messages.append(response)

                for tc in response.tool_calls:
                    tool_name = tc["name"]
                    tool_args = tc["args"]
                    print(f"  Action: {tool_name}({tool_args})")

                    # Execute tool
                    tool_fn = {"search_web": search_web, "calculator": calculator, "get_current_time": get_current_time}.get(tool_name)
                    if tool_fn:
                        try:
                            result = tool_fn.invoke(tool_args)
                        except Exception as e:
                            result = f"Tool error: {e}"
                    else:
                        result = f"Unknown tool: {tool_name}"

                    print(f"  Observation: {result}")
                    messages.append(ToolMessage(content=str(result), tool_call_id=tc["id"]))

                    trace_steps.append({
                        "thought": thought,
                        "action": {"tool": tool_name, "params": tool_args},
                        "observation": str(result),
                    })
            else:
                # No tool calls - final answer
                print(f"  Final Answer: {thought[:200]}...")
                trace_steps.append({
                    "thought": thought,
                    "action": "finish",
                    "observation": "Task complete.",
                })
                break

        # Build LangChain format trace
        langchain_trace = {
            "id": f"run-{i+1:03d}",
            "name": "agent",
            "run_type": "chain",
            "inputs": {"input": task},
            "outputs": {"output": trace_steps[-1]["thought"] if trace_steps else ""},
            "child_runs": [],
        }

        for j, step_data in enumerate(trace_steps):
            # LLM child run
            langchain_trace["child_runs"].append({
                "id": f"run-{i+1:03d}-llm-{j}",
                "name": "ChatOllama",
                "run_type": "llm",
                "inputs": {"messages": [{"role": "user", "content": task}]},
                "outputs": {"generations": [[{"text": step_data["thought"]}]]},
            })

            # Tool child run (if not a finish action)
            action = step_data["action"]
            if isinstance(action, dict):
                langchain_trace["child_runs"].append({
                    "id": f"run-{i+1:03d}-tool-{j}",
                    "name": action["tool"],
                    "run_type": "tool",
                    "inputs": action["params"],
                    "outputs": {"output": step_data["observation"]},
                })

        all_traces_langchain.append(langchain_trace)

        # Build ReAct format trace
        react_trace = {
            "id": f"trace_{i+1:03d}",
            "task": task,
            "agent": "qwen3-4b-react",
            "steps": trace_steps,
        }
        all_traces_react.append(react_trace)

    # Save LangChain format
    langchain_path = os.path.join(output_dir, "langchain_traces.json")
    with open(langchain_path, "w") as f:
        json.dump(all_traces_langchain, f, indent=2, default=str)
    print(f"\nSaved LangChain format traces to {langchain_path}")

    # Save ReAct format
    react_path = os.path.join(output_dir, "react_traces.json")
    with open(react_path, "w") as f:
        json.dump(all_traces_react, f, indent=2, default=str)
    print(f"Saved ReAct format traces to {react_path}")

    # Save Potato-ready format (for direct loading into Potato)
    potato_items = []
    for i, (react_t, lc_t) in enumerate(zip(all_traces_react, all_traces_langchain)):
        # Convert steps to dialogue format
        conversation = []
        for step in react_t["steps"]:
            if step["thought"]:
                conversation.append({
                    "speaker": "Agent (Thought)",
                    "text": step["thought"][:500],  # Truncate long thoughts
                })
            action = step["action"]
            if isinstance(action, dict):
                conversation.append({
                    "speaker": "Agent (Action)",
                    "text": f"{action['tool']}({json.dumps(action['params'])})",
                })
            elif action == "finish":
                conversation.append({
                    "speaker": "Agent (Action)",
                    "text": "finish()",
                })
            if step["observation"]:
                conversation.append({
                    "speaker": "Environment",
                    "text": step["observation"],
                })

        potato_items.append({
            "id": f"trace_{i+1:03d}",
            "task_description": react_t["task"],
            "agent_name": "qwen3-4b-react",
            "metadata_table": [
                {"Property": "Agent", "Value": "qwen3:4b"},
                {"Property": "Steps", "Value": str(len(react_t["steps"]))},
                {"Property": "Model", "Value": "Ollama/qwen3:4b"},
            ],
            "conversation": conversation,
        })

    potato_path = os.path.join(output_dir, "potato_traces.json")
    with open(potato_path, "w") as f:
        json.dump(potato_items, f, indent=2)
    print(f"Saved Potato-ready format traces to {potato_path}")

    return langchain_path, react_path, potato_path


if __name__ == "__main__":
    output_dir = os.path.join(os.path.dirname(__file__), "generated_traces")
    os.makedirs(output_dir, exist_ok=True)
    generate_traces(output_dir)
    print("\nDone!")
