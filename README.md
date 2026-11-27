# ReqCheck

**AI-powered requirements validation for software specifications.** ReqCheck combines deterministic rule-based checks with AI analysis to identify defects in requirements and produce structured, evidence-based review reports.


## Overview

ReqCheck reviews software requirements before development starts. It helps identify ambiguous, incomplete, inconsistent, or difficult-to-verify requirements and grounds findings in quotations from the source document.

Built for the **BCC-HUB × MNU FinTech Hackathon** task on AI agents for analyzing technical specifications in fintech.

## Features

- Rule-based validation that works without an API key or network connection
- AI-assisted analysis powered by Google Gemini
- Requirements segmentation and individual requirement review
- Contradiction, gap, and cross-reference analysis
- Acceptance-criteria coverage assessment
- Findings grounded in source quotations and document locations
- Markdown reports and optional JSON output
- Response caching, retries, and model fallback configuration
- Partial reports when AI service limits prevent a complete analysis

## Analysis Workflow

1. Parse and normalize the input document
2. Run deterministic checks
3. Segment requirements with AI
4. Analyze individual requirements
5. Check contradictions, gaps, and cross-references
6. Assess acceptance-criteria coverage
7. Verify AI findings against source evidence
8. Generate a review report

## Supported Input Formats

| Format | Notes |
| --- | --- |
| Markdown (`.md`, `.markdown`) | UTF-8 text |
| Plain text (`.txt`) | UTF-8 text |
| PDF (`.pdf`) | Text-layer PDFs; scanned PDFs without a text layer are not OCR-processed |
| Word (`.docx`) | Paragraphs, headings, and tables |


## Requirements

- Python 3.10 or newer
- For AI analysis: a Gemini API key and internet access
- For rule-based mode and tests: no API key or internet required

## Installation

Clone the repository and enter its directory:

```bash
git clone https://github.com/E7aman/reqcheck.git
cd reqcheck
```

Install dependencies:

```bash
python -m venv .venv
```

Activate the environment (Windows PowerShell):

```powershell
.venv\Scripts\Activate.ps1
```

Install packages:

```bash
pip install -r requirements.txt
```

## Configuration

Create a `.env` file in the repository root and set your Gemini API key:


```env
GEMINI_API_KEY=your_api_key_here
```

`GOOGLE_API_KEY` is also accepted. Optional settings include `GEMINI_MODEL` (a model name or comma-separated fallback list) and `LLM_MIN_INTERVAL` (minimum delay between requests). Do not commit your `.env` file or API keys.


## Usage

Run commands from the repository root.


### AI-assisted analysis

```bash
python -m validator tests/fixtures/requirements.md out/report.md --json out/result.json
```

### Rule-based mode (no API key required)

```bash
python -m validator tests/fixtures/requirements.md out/report.md --lint-only
```

### Help

```bash
python -m validator --help
```

You can also provide your own `.pdf`, `.docx`, `.txt`, or Markdown specification as the input file.

## Reports

ReqCheck produces a Markdown report. JSON output can optionally be generated with `--json`.
Reports include requirement segmentation, quality findings, document-level observations, acceptance coverage, a summary, and prioritized recommendations. AI findings include source quotes and locations when available.


## Testing

Run the test suite from the repository root:


```bash
python -m unittest discover -v
```

## Limitations

- AI findings may be incorrect or incomplete and should be reviewed by a human.
- Analysis quality and availability depend on the configured model and API service.
- Scanned PDFs without an extractable text layer are not supported (OCR is not included).
- Rule-based checks are pattern-based and cannot identify every requirements defect.

## Documentation

- [Russian runbook](RUNBOOK.md): setup, quota limits, testing, evaluation, troubleshooting

## Disclaimer

ReqCheck is an automated review assistant. Its output is advisory and should not replace human judgment.
