"""
Trace Converter CLI

Command-line interface for converting agent traces from various formats
to Potato's canonical JSONL format.

Usage:
    python -m potato.trace_converter --input traces.json --input-format react --output data.jsonl
    python -m potato.trace_converter --input traces.json --auto-detect --output data.jsonl
    python -m potato.trace_converter --list-formats
"""

import argparse
import json
import logging
import sys
from pathlib import Path

from .registry import converter_registry

logger = logging.getLogger(__name__)


def parse_args(args=None):
    parser = argparse.ArgumentParser(
        prog="potato-trace-convert",
        description="Convert agent traces from various formats to Potato's canonical JSONL format."
    )

    parser.add_argument(
        "--input", "-i",
        help="Input file path (JSON, JSONL, or Parquet)"
    )
    parser.add_argument(
        "--input-format", "-f",
        help="Input format name (e.g., react, langchain, langfuse, atif, webarena, openai, anthropic, swebench, otel, multi_agent, mcp)"
    )
    parser.add_argument(
        "--output", "-o",
        help="Output file path (JSONL). Defaults to stdout."
    )
    parser.add_argument(
        "--auto-detect",
        action="store_true",
        help="Auto-detect the input format"
    )
    parser.add_argument(
        "--list-formats",
        action="store_true",
        help="List all supported formats and exit"
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON output (one object per line, indented)"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging"
    )

    return parser.parse_args(args)


def load_input(file_path: str):
    """Load input data from JSON, JSONL, or Parquet file."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {file_path}")

    # Handle Parquet files
    if path.suffix.lower() == ".parquet":
        import pyarrow.parquet as pq
        table = pq.read_table(str(path))
        return table.to_pandas().to_dict("records")

    content = path.read_text(encoding="utf-8").strip()

    # Try parsing as JSON first
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    # Try parsing as JSONL (one JSON object per line)
    records = []
    for line_num, line in enumerate(content.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON on line {line_num}: {e}")
    return records


def main(args=None):
    parsed = parse_args(args)

    if parsed.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.WARNING)

    # List formats
    if parsed.list_formats:
        print("Supported trace formats:")
        print()
        for info in converter_registry.list_converters():
            print(f"  {info['format_name']:15s} {info['description']}")
            if info.get('file_extensions'):
                print(f"  {'':15s} Extensions: {', '.join(info['file_extensions'])}")
            print()
        return 0

    # Validate arguments
    if not parsed.input:
        print("Error: --input is required (or use --list-formats)", file=sys.stderr)
        return 1

    # Load input
    try:
        data = load_input(parsed.input)
    except (FileNotFoundError, ValueError) as e:
        print(f"Error loading input: {e}", file=sys.stderr)
        return 1

    # Determine format
    format_name = parsed.input_format
    if not format_name:
        if parsed.auto_detect:
            format_name = converter_registry.detect_format(data)
            if not format_name:
                print("Error: Could not auto-detect input format. "
                      "Please specify with --input-format.", file=sys.stderr)
                return 1
            print(f"Auto-detected format: {format_name}", file=sys.stderr)
        else:
            print("Error: --input-format or --auto-detect is required", file=sys.stderr)
            return 1

    # Convert
    try:
        traces = converter_registry.convert(format_name, data)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Conversion error: {e}", file=sys.stderr)
        return 1

    # Output
    output_lines = []
    for trace in traces:
        trace_dict = trace.to_dict()
        if parsed.pretty:
            output_lines.append(json.dumps(trace_dict, ensure_ascii=False, indent=2))
        else:
            output_lines.append(json.dumps(trace_dict, ensure_ascii=False))

    output_text = "\n".join(output_lines) + "\n"

    if parsed.output:
        Path(parsed.output).parent.mkdir(parents=True, exist_ok=True)
        Path(parsed.output).write_text(output_text, encoding="utf-8")
        print(f"Converted {len(traces)} traces to {parsed.output}", file=sys.stderr)
    else:
        sys.stdout.write(output_text)

    return 0


if __name__ == "__main__":
    sys.exit(main())
