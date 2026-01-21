"""
Command-line interface for the user simulator.

Usage:
    python -m potato.simulator --server http://localhost:8000 --users 10
    python -m potato.simulator --config simulator-config.yaml --server http://localhost:8000
"""

import argparse
import logging
import sys
import os

from .config import (
    SimulatorConfig,
    TimingConfig,
    LLMStrategyConfig,
    BiasedStrategyConfig,
    AnnotationStrategyType,
)
from .simulator_manager import SimulatorManager


def setup_logging(verbose: bool = False) -> None:
    """Configure logging for the CLI.

    Args:
        verbose: If True, enable debug logging
    """
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%H:%M:%S",
    )

    # Suppress noisy loggers
    if not verbose:
        logging.getLogger("urllib3").setLevel(logging.WARNING)
        logging.getLogger("requests").setLevel(logging.WARNING)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments.

    Returns:
        Parsed arguments namespace
    """
    parser = argparse.ArgumentParser(
        description="User Simulator for Potato Annotation Platform",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic random simulation
  python -m potato.simulator --server http://localhost:8000 --users 10

  # With configuration file
  python -m potato.simulator --config simulator.yaml --server http://localhost:8000

  # LLM-powered simulation with Ollama
  python -m potato.simulator --server http://localhost:8000 --users 5 \\
      --strategy llm --llm-endpoint ollama --llm-model llama3.2

  # Biased simulation
  python -m potato.simulator --server http://localhost:8000 --users 20 \\
      --strategy biased --bias-weights positive=0.6,negative=0.3,neutral=0.1

  # Fast scalability test
  python -m potato.simulator --server http://localhost:8000 --users 100 \\
      --parallel 20 --max-annotations 5 --fast-mode
""",
    )

    # Required arguments
    parser.add_argument(
        "--server",
        "-s",
        required=True,
        help="Potato server URL (e.g., http://localhost:8000)",
    )

    # Configuration file (alternative to CLI args)
    parser.add_argument(
        "--config",
        "-c",
        help="Path to YAML configuration file",
    )

    # User configuration
    parser.add_argument(
        "--users",
        "-u",
        type=int,
        default=10,
        help="Number of simulated users (default: 10)",
    )
    parser.add_argument(
        "--competence",
        help="Competence distribution as comma-separated key=value pairs "
        "(e.g., good=0.5,average=0.3,poor=0.2)",
    )

    # Strategy configuration
    parser.add_argument(
        "--strategy",
        choices=["random", "biased", "llm", "pattern", "gold_standard"],
        default="random",
        help="Annotation strategy (default: random)",
    )

    # LLM configuration
    parser.add_argument(
        "--llm-endpoint",
        choices=["openai", "anthropic", "ollama", "gemini", "huggingface", "vllm"],
        help="LLM endpoint type (for --strategy llm)",
    )
    parser.add_argument(
        "--llm-model",
        help="LLM model name (for --strategy llm)",
    )
    parser.add_argument(
        "--llm-api-key",
        help="LLM API key (or set via environment variable)",
    )
    parser.add_argument(
        "--llm-base-url",
        help="LLM base URL (for local endpoints like Ollama)",
    )

    # Biased strategy configuration
    parser.add_argument(
        "--bias-weights",
        help="Label bias weights as comma-separated key=value pairs "
        "(e.g., positive=0.6,negative=0.3,neutral=0.1)",
    )

    # Execution configuration
    parser.add_argument(
        "--parallel",
        "-p",
        type=int,
        default=5,
        help="Maximum concurrent users (default: 5)",
    )
    parser.add_argument(
        "--max-annotations",
        "-m",
        type=int,
        help="Maximum annotations per user (default: unlimited)",
    )
    parser.add_argument(
        "--sequential",
        action="store_true",
        help="Run users sequentially instead of in parallel",
    )

    # Timing configuration
    parser.add_argument(
        "--fast-mode",
        action="store_true",
        help="Disable waiting between annotations (for testing)",
    )
    parser.add_argument(
        "--timing-min",
        type=float,
        default=2.0,
        help="Minimum annotation time in seconds (default: 2.0)",
    )
    parser.add_argument(
        "--timing-max",
        type=float,
        default=30.0,
        help="Maximum annotation time in seconds (default: 30.0)",
    )

    # Quality control testing
    parser.add_argument(
        "--attention-fail-rate",
        type=float,
        default=0.0,
        help="Rate at which to fail attention checks (0-1, default: 0)",
    )
    parser.add_argument(
        "--fast-response-rate",
        type=float,
        default=0.0,
        help="Rate of suspiciously fast responses (0-1, default: 0)",
    )

    # Gold standards
    parser.add_argument(
        "--gold-file",
        help="Path to JSON file with gold standard answers",
    )

    # Output configuration
    parser.add_argument(
        "--output-dir",
        "-o",
        default="simulator_output",
        help="Output directory for results (default: simulator_output)",
    )
    parser.add_argument(
        "--no-export",
        action="store_true",
        help="Don't export results to files",
    )

    # Other options
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )

    return parser.parse_args()


def parse_key_value_pairs(s: str) -> dict:
    """Parse comma-separated key=value pairs.

    Args:
        s: String like "key1=val1,key2=val2"

    Returns:
        Dictionary of parsed pairs
    """
    result = {}
    if not s:
        return result

    for pair in s.split(","):
        if "=" in pair:
            key, value = pair.split("=", 1)
            # Try to convert to float
            try:
                result[key.strip()] = float(value.strip())
            except ValueError:
                result[key.strip()] = value.strip()

    return result


def build_config_from_args(args: argparse.Namespace) -> SimulatorConfig:
    """Build SimulatorConfig from CLI arguments.

    Args:
        args: Parsed arguments

    Returns:
        SimulatorConfig instance
    """
    # If config file provided, use it as base
    if args.config:
        config = SimulatorConfig.from_yaml(args.config)
    else:
        config = SimulatorConfig()

    # Override with CLI arguments
    config.user_count = args.users
    config.parallel_users = args.parallel
    config.simulate_wait = not args.fast_mode
    config.attention_check_fail_rate = args.attention_fail_rate
    config.respond_fast_rate = args.fast_response_rate
    config.output_dir = args.output_dir

    # Parse competence distribution
    if args.competence:
        config.competence_distribution = parse_key_value_pairs(args.competence)

    # Parse strategy
    try:
        config.strategy = AnnotationStrategyType(args.strategy)
    except ValueError:
        config.strategy = AnnotationStrategyType.RANDOM

    # LLM configuration
    if args.strategy == "llm" and args.llm_endpoint:
        api_key = args.llm_api_key
        if not api_key:
            # Try common environment variables
            env_vars = {
                "openai": "OPENAI_API_KEY",
                "anthropic": "ANTHROPIC_API_KEY",
                "huggingface": "HF_TOKEN",
                "gemini": "GOOGLE_API_KEY",
            }
            env_var = env_vars.get(args.llm_endpoint)
            if env_var:
                api_key = os.environ.get(env_var)

        config.llm_config = LLMStrategyConfig(
            endpoint_type=args.llm_endpoint,
            model=args.llm_model,
            api_key=api_key,
            base_url=args.llm_base_url,
        )

    # Biased configuration
    if args.strategy == "biased" and args.bias_weights:
        config.biased_config = BiasedStrategyConfig(
            label_weights=parse_key_value_pairs(args.bias_weights)
        )

    # Timing configuration
    config.timing = TimingConfig(
        annotation_time_min=args.timing_min,
        annotation_time_max=args.timing_max,
    )

    # Gold standards file
    if args.gold_file:
        config.gold_standard_file = args.gold_file

    return config


def main() -> int:
    """Main entry point for CLI.

    Returns:
        Exit code (0 for success, 1 for error)
    """
    args = parse_args()
    setup_logging(args.verbose)

    logger = logging.getLogger(__name__)

    try:
        # Build configuration
        config = build_config_from_args(args)

        logger.info(f"Starting simulator with {config.user_count} users")
        logger.info(f"Server: {args.server}")
        logger.info(f"Strategy: {config.strategy.value}")

        # Create manager
        manager = SimulatorManager(config, args.server)

        # Run simulation
        if args.sequential:
            results = manager.run_sequential(args.max_annotations)
        else:
            results = manager.run_parallel(args.max_annotations)

        # Print summary
        manager.print_summary()

        # Export results
        if not args.no_export:
            manager.export_results()

        return 0

    except KeyboardInterrupt:
        logger.info("Simulation interrupted by user")
        return 1

    except Exception as e:
        logger.error(f"Simulation failed: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
