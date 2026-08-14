#!/usr/bin/env python3
"""
Screenshot generator for Batch 2 annotation schemas.

Launches each example config with --debug --debug-phase annotation,
takes a screenshot of the annotation interface, and saves it.

Usage:
    python scripts/screenshot_batch2.py [--schemas vas,rubric_eval,...] [--output-dir screenshots]
    python scripts/screenshot_batch2.py --no-headless  # Debug: visible browser
"""

import os
import sys
import time
import argparse
import subprocess
import signal
from pathlib import Path

project_root = Path(__file__).parents[1]
sys.path.insert(0, str(project_root))

try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options as ChromeOptions
    from selenium.webdriver.chrome.service import Service as ChromeService
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
except ImportError:
    print("Error: selenium required. pip install selenium")
    sys.exit(1)

import requests

# Schema name -> example config path (relative to project root)
# Batch 1 schemas (7)
BATCH1_SCHEMAS = {
    "soft_label": "examples/classification/soft-label/config.yaml",
    "confidence": "examples/classification/confidence-calibrated/config.yaml",
    "constant_sum": "examples/classification/constant-sum/config.yaml",
    "semantic_differential": "examples/classification/semantic-differential/config.yaml",
    "ranking": "examples/classification/ranking/config.yaml",
    "range_slider": "examples/classification/range-slider/config.yaml",
    "hierarchical_multiselect": "examples/classification/hierarchical-multiselect/config.yaml",
}

# Batch 2 schemas (7)
BATCH2_SCHEMAS = {
    "vas": "examples/classification/vas/config.yaml",
    "extractive_qa": "examples/classification/extractive-qa/config.yaml",
    "rubric_eval": "examples/classification/rubric-eval/config.yaml",
    "text_edit": "examples/classification/text-edit/config.yaml",
    "error_span": "examples/classification/error-span/config.yaml",
    "card_sort": "examples/classification/card-sort/config.yaml",
    "conjoint": "examples/classification/conjoint/config.yaml",
}

# Original/legacy schemas
ORIGINAL_SCHEMAS = {
    "single_choice": "examples/classification/single-choice/config.yaml",
    "check_box": "examples/classification/check-box/config.yaml",
    "likert": "examples/classification/likert/config.yaml",
    "slider": "examples/classification/slider/config.yaml",
    "multirate": "examples/classification/multirate/config.yaml",
    "pairwise": "examples/classification/pairwise-comparison/config.yaml",
    "bws": "examples/classification/best-worst-scaling/config.yaml",
    "text_box": "examples/classification/text-box/config.yaml",
    "two_sliders": "examples/classification/two-sliders/config.yaml",
    "survey_demo": "examples/classification/survey-demo/config.yaml",
    "dialogue": "examples/classification/dialogue-classification/config.yaml",
    "span_labeling": "examples/span/span-labeling/config.yaml",
    "grid_layout": "examples/advanced/grid-layout/config.yaml",
    "custom_layout": "examples/custom-layouts/content-moderation/config.yaml",
    "image_class": "examples/image/image-classification/config.yaml",
    "llm_pref": "examples/classification/llm-preference/config.yaml",
    "agent_trace": "examples/agent-traces/agent-trace-evaluation/config.yaml",
    "live_agent": "examples/agent-traces/live-agent-evaluation/config.yaml",
    "hf_demo": "demo-space-build/config.yaml",
}

# Agentic schemas (for ACL 2026 camera-ready figure selection)
AGENTIC_SCHEMAS = {
    "agentic_agent_comparison": "examples/agent-traces/agent-comparison/config.yaml",
    "agentic_agent_trace_eval": "examples/agent-traces/agent-trace-evaluation/config.yaml",
    "agentic_eval_trace": "examples/agent-traces/continuous-eval/config.yaml",
    "agentic_trajectory_edit": "examples/agent-traces/trajectory-correction/config.yaml",
    "agentic_coding_comparison": "examples/agent-traces/coding-agent-comparison/config.yaml",
    "agentic_coding_eval": "examples/agent-traces/coding-agent-evaluation/config.yaml",
    "agentic_coding_prm": "examples/agent-traces/coding-agent-prm/config.yaml",
    "agentic_coding_prm_inline": "examples/agent-traces/coding-agent-prm/config-inline.yaml",
    "agentic_coding_review": "examples/agent-traces/coding-agent-review/config.yaml",
    "agentic_langchain": "examples/agent-traces/langchain-integration/config.yaml",
    "agentic_live_agent_eval": "examples/agent-traces/live-agent-evaluation/config.yaml",
    "agentic_live_coding": "examples/agent-traces/live-coding-agent/config.yaml",
    "agentic_multi_agent": "examples/agent-traces/multi-agent-evaluation/config.yaml",
    "agentic_swebench": "examples/agent-traces/swebench-evaluation/config.yaml",
    "agentic_visual_agent": "examples/agent-traces/visual-agent-evaluation/config.yaml",
    "agentic_web_creation": "examples/agent-traces/web-agent-creation/config.yaml",
    "agentic_web_review": "examples/agent-traces/web-agent-review/config.yaml",
    "agentic_interactive": "examples/agent-testing/interactive-agent-test/config.yaml",
    "agentic_coding_live_test": "examples/agent-testing/coding-agent-live-test/config.yaml",
    "agentic_coding_docker_test": "examples/agent-testing/coding-agent-docker-test/config.yaml",
    "agentic_per_turn_binding": "examples/agent-traces/per-turn-binding/config.yaml",
    "agentic_multi_agent_discussion": "examples/agent-traces/multi-agent-discussion/config.yaml",
    "consensus_tracking": "examples/agent-traces/multi-agent-discussion/config.yaml",
    "context_attribution": "examples/agent-traces/context-attribution/config.yaml",
    "agentic_debate_judging": "examples/agent-traces/debate-judging/config.yaml",
    "agentic_plan_review": "examples/agent-traces/plan-review/config.yaml",
    "agentic_negotiation": "examples/agent-traces/negotiation-review/config.yaml",
    "agentic_safety_escalation": "examples/agent-traces/safety-escalation/config.yaml",
    "agentic_session_scoring": "examples/agent-traces/session-scoring/config.yaml",
    "agentic_sub_agent_tree": "examples/agent-traces/sub-agent-tree/config.yaml",
    "agentic_review_workflow": "examples/advanced/review-workflow/config.yaml",
}

# Threaded conversations. The convokit-* examples download their corpus on first
# run (each has a setup_data.sh); screenshotting them needs that done once.
CONVERSATION_SCHEMAS = {
    "threaded_forum": "examples/conversation/threaded-forum/config.yaml",
    "convokit_awry": "examples/conversation/convokit-awry/config.yaml",
    "convokit_politeness": "examples/conversation/convokit-politeness/config.yaml",
    "convokit_tree": "examples/conversation/convokit-tree/config.yaml",
}

# Vision surfaces: drawing canvases, timelines, and bbox overlays.
#
# None of these were screenshotted before, so the verification path never
# exercised a drawing canvas or a video timeline at all -- exactly the surfaces
# most likely to render broken, because they are built at runtime by JavaScript
# rather than emitted as server-rendered markup.
VISION_SCHEMAS = {
    "image_annotation": "examples/image/image-annotation/config.yaml",
    "image_coco_import": "examples/image/coco-import/config.yaml",
    "image_format_migration": "examples/image/format-migration/config.yaml",
    "image_geometry_primitives": "examples/image/geometry-primitives/config.yaml",
    "annotation_telemetry": "examples/advanced/annotation-telemetry/config.yaml",
    "annotation_critique": "examples/image/annotation-critique/config.yaml",
    "image_ai_detection": "examples/image/image-ai-detection/config.yaml",
    "image_vllm_rationale": "examples/image/image-vllm-rationale/config.yaml",
    "image_class": "examples/image/image-classification/config.yaml",
    "video_frame_annotation": "examples/video/video-frame-annotation/config.yaml",
    "video_tracking": "examples/video/video-tracking/config.yaml",
    "video_classification": "examples/video/video-classification/config.yaml",
    "pdf_bbox": "examples/image/pdf-bbox/config.yaml",
    "document_bbox": "examples/image/document-bbox/config.yaml",
    "pdf_annotation": "examples/image/pdf-annotation/config.yaml",
}

# Combined
ALL_SCHEMAS = {**BATCH1_SCHEMAS, **BATCH2_SCHEMAS}

#: Every named group, in one place. The selector table and the config lookup
#: both derive from this, so adding a group cannot leave `everything` behind --
#: which is what happened before: `everything` resolved to ALL ∪ ORIGINAL and
#: silently skipped the agentic and conversation sets.
SCHEMA_GROUPS = {
    "batch1": BATCH1_SCHEMAS,
    "batch2": BATCH2_SCHEMAS,
    "all": ALL_SCHEMAS,
    "original": ORIGINAL_SCHEMAS,
    "agentic": AGENTIC_SCHEMAS,
    "conversation": CONVERSATION_SCHEMAS,
    "vision": VISION_SCHEMAS,
}

#: Name -> config path across every group.
COMBINED_SCHEMAS = {k: v for group in SCHEMA_GROUPS.values() for k, v in group.items()}

BASE_PORT = 9080


def find_free_port(start=9080):
    """Find a free port starting from the given number."""
    import socket
    for port in range(start, start + 100):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError("No free port found")


def start_server(config_path, port):
    """Start potato server with debug mode, return Popen object."""
    cmd = [
        sys.executable,
        str(project_root / "potato" / "flask_server.py"),
        "start",
        config_path,
        "-p", str(port),
        "--debug",
        "--debug-phase", "annotation",
    ]
    # Use DEVNULL to avoid stdout/stderr pipe buffer exhaustion.
    # Verbose configs (survey instruments, agent traces with stale users)
    # can fill the 64KB pipe buffer and hang the process.
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        cwd=str(project_root),
    )
    # Wait for server to be ready
    for _ in range(120):
        if proc.poll() is not None:
            stderr = proc.stderr.read()
            print(f"  Server died: {stderr.decode()[:500]}")
            return None
        try:
            r = requests.get(f"http://localhost:{port}/", timeout=2)
            if r.status_code in (200, 302):
                return proc
        except requests.ConnectionError:
            pass
        time.sleep(0.5)
    print("  Timeout waiting for server")
    proc.terminate()
    return None


def stop_server(proc):
    """Stop a server process."""
    if proc:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def take_screenshot(driver, port, schema_name, output_dir):
    """Navigate to annotation page and take screenshot."""
    base_url = f"http://localhost:{port}"

    # In debug mode with --debug-phase annotation, we skip login
    # Just go straight to /annotate
    driver.get(f"{base_url}/annotate")
    time.sleep(2)

    # Wait for main content to be visible
    try:
        WebDriverWait(driver, 15).until(
            EC.visibility_of_element_located((By.ID, "main-content"))
        )
    except Exception:
        # Try waiting for annotation-forms instead
        try:
            WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.ID, "annotation-forms"))
            )
        except Exception:
            print(f"  Warning: main-content not visible, taking screenshot anyway")

    time.sleep(1)  # Let animations settle

    # Take full page screenshot
    full_path = os.path.join(output_dir, f"{schema_name}_full.png")
    driver.save_screenshot(full_path)
    print(f"  Saved: {full_path}")

    # Try to take element screenshot of just the annotation form area
    try:
        form_el = driver.find_element(By.ID, "annotation-forms")
        form_path = os.path.join(output_dir, f"{schema_name}_form.png")
        form_el.screenshot(form_path)
        print(f"  Saved: {form_path}")
    except Exception as e:
        print(f"  Could not capture form element: {e}")

    # Capture console errors
    logs = driver.get_log("browser")
    errors = [l for l in logs if l["level"] in ("SEVERE", "ERROR")]
    if errors:
        print(f"  Console errors:")
        for err in errors[:5]:
            print(f"    {err['message'][:200]}")

    # Capture task_layout HTML for UI critique
    try:
        task_layout = driver.find_element(By.ID, "task_layout")
        html_content = task_layout.get_attribute("outerHTML")
        html_path = os.path.join(output_dir, f"{schema_name}_layout.html")
        with open(html_path, "w") as f:
            f.write(html_content)
        print(f"  Saved HTML: {html_path}")
    except Exception as e:
        print(f"  Could not capture layout HTML: {e}")

    return full_path


def main():
    parser = argparse.ArgumentParser(description="Screenshot Batch 2 schemas")
    parser.add_argument("--schemas", type=str, default=None,
                       help=("Group name (" + ", ".join(sorted(SCHEMA_GROUPS))
                             + ", everything) or a comma-separated list of "
                               "schema names. Default: batch2."))
    parser.add_argument("--output-dir", "-o", default="screenshots/batch2",
                       help="Output directory (default: screenshots/batch2)")
    parser.add_argument("--no-headless", action="store_true",
                       help="Show browser window")
    parser.add_argument("--window-size", default="1400x1000",
                       help="WIDTHxHEIGHT (default: 1400x1000)")
    args = parser.parse_args()

    # Parse schemas
    if args.schemas:
        if args.schemas == "everything":
            schema_names = list(COMBINED_SCHEMAS.keys())
        elif args.schemas in SCHEMA_GROUPS:
            schema_names = list(SCHEMA_GROUPS[args.schemas].keys())
        else:
            schema_names = [s.strip() for s in args.schemas.split(",")]
    else:
        schema_names = list(BATCH2_SCHEMAS.keys())

    # Parse window size
    w, h = map(int, args.window_size.split("x"))

    # Create output dir
    output_dir = os.path.join(str(project_root), args.output_dir)
    os.makedirs(output_dir, exist_ok=True)

    # Set up Chrome
    opts = ChromeOptions()
    if not args.no_headless:
        opts.add_argument("--headless=new")
    opts.add_argument(f"--window-size={w},{h}")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--force-device-scale-factor=1")
    opts.set_capability("goog:loggingPrefs", {"browser": "ALL"})

    # Try to start Chrome
    driver = None
    # webdriver-manager caches the matching driver under ~/.wdm; prefer it over
    # a potentially-stale /opt/homebrew/bin/chromedriver.
    wdm_path = None
    try:
        from webdriver_manager.chrome import ChromeDriverManager  # type: ignore
        wdm_ret = ChromeDriverManager().install()
        wdm_dir = os.path.dirname(wdm_ret)
        candidate = os.path.join(wdm_dir, "chromedriver")
        if os.path.exists(candidate):
            os.chmod(candidate, 0o755)
            wdm_path = candidate
    except Exception as exc:
        print(f"  webdriver-manager probe failed: {exc}")
    for chromedriver_path in [wdm_path, "/opt/homebrew/bin/chromedriver", None]:
        try:
            print(f"  Trying chromedriver: {chromedriver_path}")
            if chromedriver_path and os.path.exists(chromedriver_path):
                service = ChromeService(executable_path=chromedriver_path)
                driver = webdriver.Chrome(service=service, options=opts)
            else:
                driver = webdriver.Chrome(options=opts)
            print(f"  -> chromedriver OK: {chromedriver_path}")
            break
        except Exception as e:
            print(f"  -> failed: {type(e).__name__}: {str(e)[:200]}")
            if chromedriver_path:
                continue
            print(f"Error: Could not start Chrome: {e}")
            sys.exit(1)

    driver.set_window_size(w, h)

    results = {}
    for schema_name in schema_names:
        if schema_name not in COMBINED_SCHEMAS:
            print(f"Unknown schema: {schema_name}")
            continue

        config_path = COMBINED_SCHEMAS[schema_name]
        print(f"\n{'='*50}")
        print(f"Schema: {schema_name}")
        print(f"Config: {config_path}")

        port = find_free_port(BASE_PORT)
        proc = start_server(config_path, port)
        if not proc:
            results[schema_name] = "FAILED (server)"
            continue

        try:
            path = take_screenshot(driver, port, schema_name, output_dir)
            results[schema_name] = "OK"
        except Exception as e:
            print(f"  Screenshot error: {e}")
            import traceback
            traceback.print_exc()
            results[schema_name] = f"FAILED ({e})"
        finally:
            stop_server(proc)

    driver.quit()

    # Summary
    print(f"\n{'='*50}")
    print("SUMMARY")
    print(f"{'='*50}")
    for name, status in results.items():
        icon = "OK" if status == "OK" else "FAIL"
        print(f"  [{icon}] {name}: {status}")
    print(f"\nScreenshots saved to: {output_dir}")


if __name__ == "__main__":
    main()
