#!/usr/bin/env python3
"""
CompShop CLI — Gaming Competitor Offer Extraction Pipeline

Usage:
    compshop --property "MGM Detroit" --input ./pdfs/ --template ./CompShopAgentTemplate.xlsx
    compshop --property "MGM Detroit" --input ./pdfs/ --template ./template.xlsx --model sonnet
    compshop --property "MGM Detroit" --input ./pdfs/ --template ./template.xlsx --dry-run
"""

import argparse
import sys
import time
from collections import Counter
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    BarColumn,
    TaskProgressColumn,
    TimeElapsedColumn,
)
from rich.table import Table
from rich import box

from .config import MODELS, DEFAULT_MODEL, DEFAULT_BATCH_SIZE, load_reference_values
from .ingest import scan_and_qualify, extract_text, build_batch_content
from .classify import classify_batches, get_api_key
from .validate import run_validation
from .writer import write_offers, verify_output
from .prompt import build_system_prompt

console = Console()

# Pricing per 1M tokens (March 2026)
PRICING = {
    "claude-opus-4-20250514": {"input": 5.0, "output": 25.0},
    "claude-sonnet-4-20250514": {"input": 3.0, "output": 15.0},
}


def estimate_cost(model_id, input_tokens, output_tokens):
    rates = PRICING.get(model_id, {"input": 5.0, "output": 25.0})
    return (input_tokens / 1_000_000 * rates["input"]) + (
        output_tokens / 1_000_000 * rates["output"]
    )


def build_arg_parser():
    parser = argparse.ArgumentParser(
        prog="compshop",
        description="Extract gaming competitor offers from PDFs into Excel",
    )
    parser.add_argument(
        "--property", required=True, help="MGM Property name (e.g., 'MGM Detroit')"
    )
    parser.add_argument(
        "--competitor",
        default=None,
        help="Competitor name override (auto-detected from PDF if omitted)",
    )
    parser.add_argument(
        "--input", required=True, help="Path to folder containing PDF files"
    )
    parser.add_argument(
        "--template", required=True, help="Path to CompShopAgentTemplate.xlsx"
    )
    parser.add_argument(
        "--output", default=".", help="Output directory (default: current dir)"
    )
    parser.add_argument(
        "--model",
        choices=list(MODELS.keys()),
        default=DEFAULT_MODEL,
        help=f"Model to use (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"PDFs per API call (default: {DEFAULT_BATCH_SIZE})",
    )
    parser.add_argument(
        "--property-keyword",
        default=None,
        help="Keyword to match in filenames (default: derived from --competitor or --property)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Scan and qualify PDFs without making API calls",
    )
    parser.add_argument(
        "--latest-only",
        action="store_true",
        help="Process only the newest qualifying PDF",
    )
    parser.add_argument(
        "--no-ocr", action="store_true", help="Disable automatic OCR for scanned PDFs"
    )
    return parser


def main():
    parser = build_arg_parser()
    args = parser.parse_args()

    model_id = MODELS[args.model]
    model_label = f"{args.model.capitalize()} ({model_id})"

    # ── Header ──────────────────────────────────────────────
    console.print()
    console.print(
        Panel.fit(
            f"[bold]CompShop[/bold]  Gaming Offer Extraction Pipeline\n"
            f"[dim]Property:[/dim] {args.property}  [dim]Model:[/dim] {model_label}",
            border_style="blue",
        )
    )
    console.print()

    # ── Stage 0: Load Template ──────────────────────────────
    with console.status("[bold blue]Loading template..."):
        template_path = Path(args.template)
        if not template_path.exists():
            console.print(f"[red]Template not found: {template_path}[/red]")
            sys.exit(1)
        ref_values = load_reference_values(str(template_path))
        system_prompt = build_system_prompt(ref_values)

    console.print(
        f"  [green]✓[/green] Template loaded — {len(ref_values['properties'])} properties, "
        f"{len(ref_values['competitors'])} competitors, {len(ref_values['categories'])} categories"
    )

    # ── Stage 1: Scan & Qualify ─────────────────────────────
    keyword = args.property_keyword
    if not keyword:
        # Derive from competitor or try common mappings
        keyword = args.competitor or args.property
        # Strip "MGM " prefix for filename matching
        for prefix in ["MGM ", "."]:
            if keyword.startswith(prefix):
                keyword = keyword[len(prefix) :]

    with console.status(f"[bold blue]Scanning for PDFs matching '{keyword}'..."):
        try:
            qualifying = scan_and_qualify(
                args.input, keyword, latest_only=args.latest_only
            )
        except FileNotFoundError as e:
            console.print(f"[red]{e}[/red]")
            sys.exit(1)

    if not qualifying:
        console.print(
            f"  [yellow]⚠[/yellow]  No qualifying PDFs found for '{keyword}' in {args.input}"
        )
        console.print(
            "  [dim]Tip: use --property-keyword to override filename matching[/dim]"
        )
        sys.exit(0)

    console.print(f"  [green]✓[/green] {len(qualifying)} qualifying PDFs found")

    # ── Stage 2: Extract Text ───────────────────────────────
    with console.status("[bold blue]Extracting text from PDFs..."):
        documents = extract_text(qualifying, enable_ocr=not args.no_ocr)

    total_chars = sum(d.total_chars for d in documents)
    total_pages = sum(len(d.pages) for d in documents)
    ocr_count = sum(1 for d in documents if d.ocr_applied)
    console.print(
        f"  [green]✓[/green] Extracted {total_pages} pages, {total_chars:,} chars from {len(documents)} PDFs"
    )
    if ocr_count:
        console.print(f"  [cyan]⟳[/cyan] OCR applied to {ocr_count} scanned PDF(s)")

    # Show PDF list
    pdf_table = Table(box=box.SIMPLE, show_header=True, header_style="dim")
    pdf_table.add_column("Filename", style="white")
    pdf_table.add_column("Segment", style="cyan")
    pdf_table.add_column("Pages", justify="right")
    pdf_table.add_column("Chars", justify="right")
    pdf_table.add_column("OCR", justify="center")
    for doc in documents:
        ocr_flag = "[cyan]✓[/cyan]" if doc.ocr_applied else ""
        pdf_table.add_row(
            doc.filename,
            doc.segment_code,
            str(len(doc.pages)),
            f"{doc.total_chars:,}",
            ocr_flag,
        )
    console.print(pdf_table)

    if args.dry_run:
        console.print("\n[yellow]Dry run complete — no API calls made.[/yellow]")
        sys.exit(0)

    # ── Stage 3: Classify via API ───────────────────────────
    api_key = get_api_key()
    if not api_key:
        console.print(
            "[red]No API key found. Set ANTHROPIC_API_KEY env var or create a .env file.[/red]"
        )
        sys.exit(1)

    # Determine competitor name
    competitor = args.competitor
    if not competitor:
        # Try to match from REFERENCE values
        keyword_lower = keyword.lower().replace(" ", "")
        for c in ref_values["competitors"]:
            if keyword_lower in c.lower().replace(" ", "").replace(".", ""):
                competitor = c
                break
        if not competitor:
            console.print(
                f"[yellow]Could not auto-detect competitor for '{keyword}'.[/yellow]"
            )
            console.print("[dim]Use --competitor to specify explicitly.[/dim]")
            sys.exit(1)

    console.print(f"\n  [dim]Competitor:[/dim] {competitor}")
    console.print(f"  [dim]Batch size:[/dim] {args.batch_size}")

    # Build batches
    batches = []
    for i in range(0, len(documents), args.batch_size):
        batch_docs = documents[i : i + args.batch_size]
        user_msg = build_batch_content(batch_docs, args.property, competitor)
        batches.append((user_msg, len(batch_docs)))

    console.print(f"  [dim]API calls:[/dim] {len(batches)}\n")

    # Run with progress
    accumulated_input = 0
    accumulated_output = 0
    accumulated_offers = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(bar_width=30),
        TaskProgressColumn(),
        TextColumn("•"),
        TimeElapsedColumn(),
        TextColumn("[dim]{task.fields[status]}[/dim]"),
        console=console,
    ) as progress:
        task = progress.add_task(
            "Classifying",
            total=len(batches),
            status="starting...",
        )

        def on_batch(idx, total, offers, usage, elapsed):
            nonlocal accumulated_input, accumulated_output, accumulated_offers
            in_tok = usage.get("input_tokens", 0)
            out_tok = usage.get("output_tokens", 0)
            accumulated_input += in_tok
            accumulated_output += out_tok
            accumulated_offers += len(offers)
            cost = estimate_cost(model_id, accumulated_input, accumulated_output)
            progress.update(
                task,
                advance=1,
                status=f"{accumulated_offers} offers | ${cost:.2f}",
            )

        result = classify_batches(
            batches, model_id, system_prompt, api_key, progress_callback=on_batch
        )

    # Stats
    total_cost = estimate_cost(
        model_id, result.total_input_tokens, result.total_output_tokens
    )
    console.print(
        f"  [green]✓[/green] {len(result.all_offers)} raw offers extracted in {result.total_time:.1f}s"
    )
    console.print(
        f"  [dim]Tokens:[/dim] {result.total_input_tokens:,} in / {result.total_output_tokens:,} out"
    )
    console.print(f"  [dim]Cost:[/dim] ${total_cost:.2f}")

    if result.errors:
        console.print(f"\n  [yellow]⚠ {len(result.errors)} API errors:[/yellow]")
        for err in result.errors:
            console.print(f"    [red]{err}[/red]")

    # ── Stage 4: Validate ───────────────────────────────────
    console.print()
    with console.status("[bold blue]Validating and deduplicating..."):
        val = run_validation(result.all_offers, ref_values)

    console.print(
        f"  [green]✓[/green] {len(val.valid_offers)} offers after dedup ({val.dupes_removed} duplicates removed)"
    )

    if val.errors:
        console.print(f"  [yellow]⚠ {len(val.errors)} validation issues:[/yellow]")
        for err in val.errors[:10]:
            console.print(f"    [yellow]{err}[/yellow]")
        if len(val.errors) > 10:
            console.print(f"    [dim]... and {len(val.errors) - 10} more[/dim]")

    if not val.valid_offers:
        console.print("\n[yellow]No valid offers to write.[/yellow]")
        sys.exit(0)

    # ── Stage 5: Write Excel ────────────────────────────────
    console.print()
    with console.status("[bold blue]Writing Excel output..."):
        output_path, row_count, first_row, last_row = write_offers(
            str(template_path), val.valid_offers, output_dir=args.output
        )
        verification = verify_output(output_path, row_count, first_row)

    console.print(
        f"  [green]✓[/green] Wrote {row_count} rows to [bold]{output_path}[/bold]"
    )
    console.print(
        f"  [dim]Rows {first_row}–{last_row} | Verified: {verification['occupied_rows']} occupied[/dim]"
    )

    if not verification["count_match"]:
        console.print(
            f"  [red]⚠ Row count mismatch: expected {row_count}, found {verification['occupied_rows']}[/red]"
        )
    if not verification["placement_ok"]:
        console.print(
            f"  [red]⚠ Placement issue: first occupied row is {verification['first_occupied_row']}, expected {first_row}[/red]"
        )

    # ── Summary Panel ───────────────────────────────────────
    console.print()
    type_counts = Counter(o.get("Type", "?") for o in val.valid_offers)
    cat_counts = Counter(o.get("Category", "?") for o in val.valid_offers)

    summary_table = Table(
        box=box.ROUNDED, show_header=False, border_style="blue", padding=(0, 1)
    )
    summary_table.add_column("Key", style="dim", width=18)
    summary_table.add_column("Value", style="white")

    summary_table.add_row("Total offers", str(len(val.valid_offers)))
    summary_table.add_row("Dupes removed", str(val.dupes_removed))
    summary_table.add_row(
        "By type", ", ".join(f"{k}: {v}" for k, v in type_counts.most_common())
    )
    summary_table.add_row(
        "By category", ", ".join(f"{k}: {v}" for k, v in cat_counts.most_common())
    )
    summary_table.add_row("Model", model_label)
    summary_table.add_row("API calls", str(result.total_calls))
    summary_table.add_row("Total cost", f"${total_cost:.2f}")
    summary_table.add_row("Validation errors", str(len(val.errors)))
    summary_table.add_row("Output", str(output_path))

    console.print(
        Panel(summary_table, title="[bold]Run Summary[/bold]", border_style="blue")
    )

    # Preview last 2 rows
    if verification["preview"]:
        preview_table = Table(box=box.SIMPLE, show_header=True, header_style="dim")
        for col in [
            "Row",
            "Property",
            "Competitor",
            "StartDate",
            "Type",
            "Category",
            "OfferAmt",
            "Name",
        ]:
            preview_table.add_column(col)
        for row_data in verification["preview"]:
            preview_table.add_row(
                str(row_data["row"]),
                str(row_data.get("Property", "")),
                str(row_data.get("Competitor", "")),
                str(row_data.get("StartDate", "")),
                str(row_data.get("Type", "")),
                str(row_data.get("Category", "")),
                str(row_data.get("OfferAmt", "")),
                str(row_data.get("Name", ""))[:50],
            )
        console.print("\n[dim]Last inserted rows:[/dim]")
        console.print(preview_table)

    console.print()


if __name__ == "__main__":
    main()
