# CompShop — Gaming Competitor Offer Extraction

Extracts and normalizes gaming-related competitor offers from casino promotional email PDFs into a structured Excel file.

## Quick Start

### 1. Install (one command)

```
pip install git+https://github.com/carlosreynoso96-ai/compshop.git
```

### 2. Set your API key

Create a `.env` file in the folder you'll run from:

```
ANTHROPIC_API_KEY=sk-ant-your-key-here
```

Or set it as an environment variable:

**Windows (PowerShell):**
```powershell
$env:ANTHROPIC_API_KEY = "sk-ant-your-key-here"
```

**Mac/Linux:**
```bash
export ANTHROPIC_API_KEY=sk-ant-your-key-here
```

### 3. Run

```
compshop --property "MGM Detroit" --input ./pdfs/ --template ./CompShopAgentTemplate.xlsx
```

## Options

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `--property` | Yes | — | MGM Property name (e.g., "MGM Detroit") |
| `--input` | Yes | — | Path to folder containing PDF files |
| `--template` | Yes | — | Path to CompShopAgentTemplate.xlsx |
| `--competitor` | No | auto-detect | Competitor name (matched from REFERENCE tab) |
| `--output` | No | current dir | Output folder for Excel file |
| `--model` | No | opus | Model: `opus` (accurate) or `sonnet` (faster) |
| `--batch-size` | No | 20 | PDFs per API call |
| `--property-keyword` | No | auto | Keyword to match in PDF filenames |
| `--dry-run` | No | — | Scan PDFs without making API calls |
| `--latest-only` | No | — | Process only the newest qualifying PDF |
| `--no-ocr` | No | — | Disable automatic OCR for scanned PDFs |

## Examples

**Standard run (Opus, all PDFs):**
```
compshop --property "MGM Detroit" --input C:\CompShop\PDFs\ --template C:\CompShop\CompShopAgentTemplate.xlsx
```

**Quick run with Sonnet:**
```
compshop --property "MGM Detroit" --input ./pdfs/ --template ./template.xlsx --model sonnet
```

**Dry run (see what PDFs qualify without API calls):**
```
compshop --property "MGM Detroit" --input ./pdfs/ --template ./template.xlsx --dry-run
```

**Latest PDF only:**
```
compshop --property "MGM Detroit" --input ./pdfs/ --template ./template.xlsx --latest-only
```

**Custom batch size (10 PDFs per API call):**
```
compshop --property "MGM Detroit" --input ./pdfs/ --template ./template.xlsx --batch-size 10
```

## Output

Creates `MasterCompShopData_YYYY-MM.xlsx` in the output directory with all extracted offers written to the Data tab. The file follows the exact schema from `CompShopAgentTemplate.xlsx`.

## Updating

```
pip install --upgrade git+https://github.com/carlosreynoso96-ai/compshop.git
```

## Cost

At 500 PDFs per run (batched 20 per call):
- **Opus:** ~$7.76
- **Sonnet:** ~$4.71

Costs scale linearly with PDF count.

## Requirements

- Python 3.10+
- Anthropic API key
- **Tesseract OCR** (for scanned/image-only PDFs) — [Download installer](https://github.com/UB-Mannheim/tesseract/wiki). Install to default `C:\Program Files\Tesseract-OCR`. Compshop auto-detects it.
