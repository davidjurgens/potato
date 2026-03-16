#!/usr/bin/env python3
"""
Demo: Live Agent with Ollama Vision

Tests the AgentRunner's Ollama vision integration. Uses a synthetic
test image or a real webpage screenshot (if Playwright is installed).

Recommended model: gemma3:4b (reliable structured output)
Also tested: qwen3-vl:2b (works for short prompts only)

Requirements:
    pip install ollama
    ollama pull gemma3:4b          # or: ollama pull qwen3-vl:2b
    # Optional for real screenshots:
    pip install playwright && playwright install chromium

Usage (from repo root):
    python examples/agent-traces/live-agent-evaluation/demo_ollama_agent.py
    python examples/agent-traces/live-agent-evaluation/demo_ollama_agent.py --model gemma3:4b
    python examples/agent-traces/live-agent-evaluation/demo_ollama_agent.py --model qwen3-vl:2b
    python examples/agent-traces/live-agent-evaluation/demo_ollama_agent.py --url https://example.com --steps 3
    python examples/agent-traces/live-agent-evaluation/demo_ollama_agent.py --screenshot-only
"""

import argparse
import base64
import json
import os
import struct
import sys
import time
import zlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def create_test_png(width=400, height=300):
    """Create a synthetic webpage-like PNG image."""
    sig = b'\x89PNG\r\n\x1a\n'
    ihdr_data = struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)
    ihdr_crc = zlib.crc32(b'IHDR' + ihdr_data) & 0xffffffff
    ihdr = struct.pack('>I', 13) + b'IHDR' + ihdr_data + struct.pack('>I', ihdr_crc)
    raw = b''
    for y in range(height):
        raw += b'\x00'
        for x in range(width):
            if y < 40:
                raw += b'\x33\x33\x33'  # dark header bar
            elif 80 <= y <= 120 and 50 <= x <= 350:
                raw += b'\x42\x87\xf5'  # blue button
            elif 150 <= y <= 200 and 50 <= x <= 350:
                raw += b'\xdd\xdd\xdd'  # gray content area
            else:
                raw += b'\xff\xff\xff'  # white background
    compressed = zlib.compress(raw)
    idat_crc = zlib.crc32(b'IDAT' + compressed) & 0xffffffff
    idat = struct.pack('>I', len(compressed)) + b'IDAT' + compressed + struct.pack('>I', idat_crc)
    iend_crc = zlib.crc32(b'IEND') & 0xffffffff
    iend = struct.pack('>I', 0) + b'IEND' + struct.pack('>I', iend_crc)
    return sig + ihdr + idat + iend


def get_screenshot(url="https://example.com"):
    """Get a screenshot, using Playwright if available, else synthetic."""
    try:
        from playwright.sync_api import sync_playwright
        print(f"  Taking screenshot of {url}...")
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 720})
            page.goto(url, wait_until="networkidle", timeout=15000)
            data = page.screenshot()
            browser.close()
        print(f"  Screenshot: {len(data)} bytes (real page)")
        return data
    except Exception:
        print("  Using synthetic test image (install playwright for real screenshots)")
        return create_test_png()


def check_dependencies(model):
    """Check required packages and model availability."""
    errors = []
    try:
        import ollama
        client = ollama.Client(host="http://localhost:11434", timeout=10)
        models_resp = client.list()
        model_names = [
            m.get("name", m.get("model", ""))
            for m in models_resp.get("models", [])
        ]
        print(f"  Ollama: OK ({len(model_names)} models)")
        # Check if requested model is available
        model_found = any(model in name for name in model_names)
        if not model_found:
            errors.append(f"Model '{model}' not found. Run: ollama pull {model}")
    except ImportError:
        errors.append("ollama package not installed: pip install ollama")
    except Exception as e:
        errors.append(f"Ollama not running: {e}")
    return errors


def test_agent_runner_integration(model, screenshot_b64):
    """Test the AgentRunner LLM pipeline with a screenshot."""
    from potato.agent_runner import AgentRunner, AgentConfig

    print(f"\n--- AgentRunner + {model} ---")

    config = AgentConfig(
        max_steps=1,
        model=model,
        endpoint_type="ollama_vision",
        base_url="http://localhost:11434",
        max_tokens=512,
        temperature=0.3,
        timeout=120,
    )
    runner = AgentRunner("demo", config, "/tmp/demo_screenshots")
    runner._init_llm_client()
    print(f"  LLM client initialized")

    messages = runner._build_llm_messages(
        screenshot_b64, "Describe what you see and identify clickable elements"
    )

    start = time.time()
    response = runner._query_llm(messages)
    elapsed = time.time() - start

    thought, action = runner._parse_action(response)

    print(f"  Response time: {elapsed:.1f}s")
    print(f"  Thought: {thought[:120] if thought else '(empty)'}")
    print(f"  Action:  {json.dumps(action)}")

    ok = bool(thought) and action.get("type") != "wait"
    print(f"  Result:  {'PASS' if ok else 'FAIL'}")
    return ok


def test_full_agent(model, url, max_steps):
    """Test the full agent loop with Playwright."""
    try:
        import playwright  # noqa: F401
    except ImportError:
        print("\n--- Full Agent Test SKIPPED (playwright not installed) ---")
        print("  pip install playwright && playwright install chromium")
        return

    from potato.agent_runner import AgentRunner, AgentConfig, AgentState
    import tempfile

    print(f"\n--- Full Agent Loop: {model} on {url} ---")

    config = AgentConfig(
        max_steps=max_steps,
        step_delay=0.5,
        viewport_width=1280,
        viewport_height=720,
        model=model,
        endpoint_type="ollama_vision",
        base_url="http://localhost:11434",
        max_tokens=1024,
        temperature=0.3,
        timeout=120,
    )

    screenshot_dir = tempfile.mkdtemp(prefix="agent_demo_")
    runner = AgentRunner("demo-full", config, screenshot_dir)

    def on_event(event):
        etype = event["type"]
        data = event.get("data", {})
        if etype == "step":
            i = data.get("step_index", "?")
            a = data.get("action_type", "?")
            t = data.get("thought", "")[:80]
            print(f"  Step {i}: {a} — {t}")
        elif etype == "state_change":
            print(f"  State: {data.get('old_state')} -> {data.get('new_state')}")
        elif etype == "error":
            print(f"  ERROR: {data.get('message', '')}")
        elif etype == "complete":
            print(f"  Complete ({data.get('total_steps')} steps)")

    runner.add_listener(on_event)
    runner.start(task_description=f"Describe {url}", start_url=url)

    timeout_secs = max_steps * 30 + 30
    t0 = time.time()
    while runner.state not in (AgentState.COMPLETED, AgentState.ERROR):
        if time.time() - t0 > timeout_secs:
            print("  TIMEOUT")
            runner.stop()
            break
        time.sleep(0.5)

    trace = runner.get_trace()
    print(f"\n  Final: {runner.state.value}, {trace['total_steps']} steps")
    if runner.error:
        print(f"  Error: {runner.error}")


def main():
    parser = argparse.ArgumentParser(description="Demo: Live Agent with Ollama Vision")
    parser.add_argument("--model", default="gemma3:4b",
                        help="Ollama vision model (default: gemma3:4b)")
    parser.add_argument("--url", default="https://example.com")
    parser.add_argument("--steps", type=int, default=2)
    parser.add_argument("--screenshot-only", action="store_true",
                        help="Skip full agent loop (no Playwright needed)")
    args = parser.parse_args()

    print("=" * 60)
    print(f"Live Agent Demo — Ollama Vision ({args.model})")
    print("=" * 60)

    print("\nChecking dependencies...")
    errors = check_dependencies(args.model)
    if errors:
        print("\nIssues:")
        for e in errors:
            print(f"  - {e}")
        if any("not installed" in e or "not running" in e for e in errors):
            sys.exit(1)

    # Get screenshot
    print("\nPreparing screenshot...")
    screenshot_bytes = get_screenshot(args.url)
    screenshot_b64 = base64.b64encode(screenshot_bytes).decode("utf-8")

    # Test AgentRunner integration
    test_agent_runner_integration(args.model, screenshot_b64)

    # Full agent loop (requires Playwright)
    if not args.screenshot_only:
        test_full_agent(args.model, args.url, args.steps)

    print("\n" + "=" * 60)
    print("Demo complete!")


if __name__ == "__main__":
    main()
