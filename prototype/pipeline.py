#!/usr/bin/env python3
"""
pipeline.py — Eisla NL-to-Zener pipeline.

End-to-end flow:
  1. Accept a plain-English project description
  2. Call Claude to generate a composable Zener board file (.zen)
  3. Write the file to boards/generated/<BoardName>/
  4. Invoke `pcb build` to compile to a KiCad project
  5. On build failure, feed errors back to Claude and retry (up to MAX_RETRIES)
  6. (Future) invoke FreeRouting for auto-layout
  7. (Future) run ERC/DRC checks
  8. (Future) export Gerbers and quote from fabs

Usage:
    python pipeline.py "I want an ESP32 board with WiFi and an LED"
    python pipeline.py --interactive
    python pipeline.py --examples
    python pipeline.py --no-build "..." # skip pcb build (offline / no CLI)

Requirements:
    pip install anthropic
    ANTHROPIC_API_KEY env var set
    pcb CLI installed (https://docs.pcb.new) for build step
"""

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

import claude_generator


# ── Config ───────────────────────────────────────────────────────────────────

PRICING = {1: 499, 2: 599, 3: 749}   # kept for quote display (tier inferred)
MAX_RETRIES = 2                       # self-healing build retries

EXAMPLE_REQUESTS = [
    "I want a simple board with an ATmega328P that blinks an LED",
    "Build me a WiFi-enabled sensor hub that reads temperature and humidity over I2C",
    "I need a USB-C dev board with an RP2040, SPI flash, and SWD debug",
    "Design a motor controller board with ESP32, PWM outputs, and Bluetooth",
    "High-performance board with STM32H7, Ethernet, USB, and SPI for an IMU",
]


# ── Board name helper ────────────────────────────────────────────────────────

def _make_board_name(description: str) -> str:
    """Derive a filesystem-safe board name from the NL description."""
    skip = {"i", "a", "an", "the", "with", "and", "for", "that", "to", "me",
            "my", "want", "need", "build", "design", "make", "create"}
    words = description.lower().split()
    key_words = [w for w in words if w not in skip and w.isalpha()][:4]
    slug = "_".join(key_words) if key_words else "board"
    slug = re.sub(r"[^a-z0-9_]", "", slug)
    return f"EISLA_{slug.upper()}"


# ── pcb build wrapper ────────────────────────────────────────────────────────

def _pcb_build(board_dir: Path) -> tuple[bool, str]:
    """
    Run `pcb build <board_dir>`.

    Returns:
        (success: bool, output: str)  — output contains stdout + stderr on failure.
    """
    try:
        result = subprocess.run(
            ["pcb", "build", str(board_dir)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        combined = (result.stdout + "\n" + result.stderr).strip()
        return result.returncode == 0, combined
    except FileNotFoundError:
        return False, "pcb CLI not found — install from https://docs.pcb.new"
    except subprocess.TimeoutExpired:
        return False, "pcb build timed out after 120 s"


# ── Board pcb.toml ────────────────────────────────────────────────────────────

_BOARD_TOML_TEMPLATE = """\
[package]
name = "{name}"
version = "0.1.0"
description = "Auto-generated Eisla board: {description}"

[dependencies]
"github.com/diodeinc/registry" = "0.1.0"
"""


# ── Core pipeline ─────────────────────────────────────────────────────────────

def run_pipeline(
    description: str,
    output_dir: str = "boards/generated",
    run_build: bool = True,
) -> dict:
    """
    Run the full NL → Zener → KiCad pipeline.

    Args:
        description: Plain-English project description.
        output_dir:  Root directory for generated board packages.
        run_build:   Whether to invoke `pcb build` for validation.

    Returns:
        Result dict with keys: board_name, zen_file, build_success,
        build_output, next_steps.
    """
    board_name = _make_board_name(description)
    board_dir  = Path(output_dir) / board_name
    board_dir.mkdir(parents=True, exist_ok=True)

    zen_file  = board_dir / f"{board_name}.zen"
    toml_file = board_dir / "pcb.toml"

    # Write board manifest if not present
    if not toml_file.exists():
        toml_file.write_text(
            _BOARD_TOML_TEMPLATE.format(
                name=board_name.lower().replace("_", "-"),
                description=description,
            )
        )

    # ── Step 1: Generate .zen via Claude ────────────────────────────────────
    print(f"  Generating .zen for: {description!r}")
    zen_code = claude_generator.generate(description)
    zen_file.write_text(zen_code)
    print(f"  Written: {zen_file}")

    build_success = None
    build_output  = ""

    if run_build:
        # ── Step 2: Build (with self-healing retry) ──────────────────────
        for attempt in range(1, MAX_RETRIES + 2):   # attempts: 1, 2, 3
            print(f"  pcb build attempt {attempt}/{MAX_RETRIES + 1} …")
            build_success, build_output = _pcb_build(board_dir)

            if build_success:
                print("  Build succeeded.")
                break

            print(f"  Build failed:\n{_indent(build_output)}")

            if attempt <= MAX_RETRIES:
                print("  Asking Claude to fix errors …")
                zen_code = claude_generator.generate(description, error_feedback=build_output)
                zen_file.write_text(zen_code)
            else:
                print("  Max retries reached — manual review needed.")

    return {
        "board_name":    board_name,
        "zen_file":      str(zen_file),
        "build_success": build_success,
        "build_output":  build_output,
        "next_steps": _next_steps(board_dir, build_success),
    }


def _next_steps(board_dir: Path, build_success: bool | None) -> list[str]:
    steps = []
    if build_success is False:
        steps.append(f"Review errors, edit {board_dir}/*.zen, then re-run pipeline")
    if build_success is None:
        steps.append(f"pcb build {board_dir}          # compile to KiCad project")
    if build_success:
        steps.append(f"pcb layout {board_dir}         # open in KiCad for layout")
        steps.append( "freerouting <kicad_project>     # auto-route the PCB")
        steps.append( "pcb check                      # run ERC/DRC validation")
        steps.append( "pcb export gerber              # generate manufacturing files")
    return steps


def _indent(text: str, prefix: str = "    ") -> str:
    return "\n".join(prefix + line for line in text.splitlines())


# ── Output formatting ─────────────────────────────────────────────────────────

def print_result(result: dict) -> None:
    width = 60
    print("\n" + "=" * width)
    print("  EISLA PIPELINE — Board Generated")
    print("=" * width)
    print(f"  Board:    {result['board_name']}")
    print(f"  Zen file: {result['zen_file']}")

    if result["build_success"] is True:
        print("  Build:    SUCCESS")
    elif result["build_success"] is False:
        print("  Build:    FAILED (see errors above)")
    else:
        print("  Build:    skipped (--no-build)")

    print()
    print("  Next steps:")
    for step in result["next_steps"]:
        print(f"    $ {step}")
    print("=" * width + "\n")


# ── CLI modes ─────────────────────────────────────────────────────────────────

def interactive_mode(run_build: bool) -> None:
    print("\nEisla NL-to-Zener Pipeline")
    print("Type a project description, or 'quit' to exit.\n")
    while True:
        try:
            desc = input("eisla> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not desc or desc.lower() in ("quit", "exit", "q"):
            break
        result = run_pipeline(desc, run_build=run_build)
        print_result(result)


def run_examples(run_build: bool) -> None:
    print("\nRunning all example requests…\n")
    for i, desc in enumerate(EXAMPLE_REQUESTS, 1):
        print(f"[{i}/{len(EXAMPLE_REQUESTS)}] \"{desc}\"")
        result = run_pipeline(desc, run_build=run_build)
        print_result(result)


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Eisla NL-to-Zener PCB design pipeline",
    )
    parser.add_argument(
        "description",
        nargs="?",
        help="Natural-language project description",
    )
    parser.add_argument(
        "--interactive", "-i",
        action="store_true",
        help="Start interactive mode",
    )
    parser.add_argument(
        "--examples", "-e",
        action="store_true",
        help="Run all built-in examples",
    )
    parser.add_argument(
        "--output-dir", "-o",
        default="boards/generated",
        help="Output directory for generated boards",
    )
    parser.add_argument(
        "--no-build",
        action="store_true",
        help="Skip `pcb build` step (offline / no CLI installed)",
    )

    args = parser.parse_args()
    run_build = not args.no_build

    if args.examples:
        run_examples(run_build)
    elif args.interactive:
        interactive_mode(run_build)
    elif args.description:
        result = run_pipeline(args.description, args.output_dir, run_build)
        print_result(result)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
