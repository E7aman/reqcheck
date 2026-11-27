# ReqCheck

**AI-powered requirements validation for software specifications.**

ReqCheck is a requirements analysis tool that combines deterministic rule-based validation with AI-assisted review to identify defects in software specifications and generate structured, evidence-based reports.

## Overview

ReqCheck helps teams review software requirements before development begins. It identifies potentially ambiguous, incomplete, inconsistent, and difficult-to-verify requirements while grounding findings in quotations and locations from the source document.

The project was developed for the **BCC-HUB × MNU FinTech Hackathon**, addressing the challenge of applying AI agents to technical specification analysis in fintech.

## Key Features

- **Hybrid analysis:** combines deterministic validation rules with AI-assisted reasoning.
- **Offline rule-based mode:** performs structural and pattern-based checks without an API key or network connection.
- **Requirements extraction:** segments specifications into individually identifiable requirements.
- **Quality assessment:** analyzes clarity, completeness, consistency, and verifiability.
- **Cross-requirement analysis:** identifies potential contradictions, gaps, and cross-reference issues.
- **Acceptance criteria coverage:** evaluates whether requirements are supported by acceptance criteria.
- **Evidence-based findings:** validates source quotations and document locations before including findings.
- **Structured reporting:** generates Markdown reports and optional JSON output.
- **Resilience mechanisms:** supports response caching, retries, model fallback configuration, and partial reports when AI services are unavailable.

## Analysis Workflow

ReqCheck follows a multi-stage analysis pipeline:

1. **Document parsing** — loads and normalizes the input specification.
2. **Deterministic validation** — checks document structure and applies rule-based quality checks.
3. **Requirements segmentation** — extracts individual requirements using AI.
4. **Individual analysis** — evaluates the quality of each extracted requirement.
5. **Document-level analysis** — checks contradictions, gaps, and cross-references.
6. **Coverage assessment** — evaluates acceptance criteria coverage.
7. **Evidence verification** — checks AI-generated findings against the original document and filters unsupported results.
8. **Report generation** — produces a structured review report.

## Supported Input Formats

| Format | Notes |
| --- | --- |
| Markdown (`.md`, `.markdown`) | UTF-8 text |
| Plain text (`.txt`) | UTF-8 text |
| PDF (`.pdf`) | Text-layer PDFs; scanned PDFs without a text layer are not OCR-processed |
| Word (`.docx`) | Paragraphs, headings, and tables |

## Requirements

- Python 3.10 or newer
- For AI-assisted analysis: a Google Gemini API key and internet access
- For rule-based analysis and automated tests: no API key or internet connection required

## Installation

Clone the repository:

```bash
git clone https://github.com/E7aman/reqcheck.git
cd reqcheck
```

Create and activate a virtual environment:

```bash
python -m venv .venv
```

Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

Install dependencies:

```bash
pip install -r requirements.txt
```

## Configuration

Create a `.env` file in the repository root:

```env
GEMINI_API_KEY=your_api_key_here
```

`GOOGLE_API_KEY` is also accepted.

Optional configuration:

- `GEMINI_MODEL` — model name or comma-separated fallback model list.
- `LLM_MIN_INTERVAL` — minimum delay between consecutive LLM requests.

Keep API keys private. Never commit `.env` files or credentials to the repository.

## Usage

Run all commands from the repository root.

### AI-assisted analysis

```bash
python -m validator tests/fixtures/requirements.md out/report.md --json out/result.json
```

This command runs the complete analysis pipeline and generates:

- `out/report.md` — human-readable Markdown report.
- `out/result.json` — structured JSON results.

### Rule-based analysis

```bash
python -m validator tests/fixtures/requirements.md out/report.md --lint-only
```

This mode runs deterministic checks without requiring an API key or network access.

### Command-line help

```bash
python -m validator --help
```

You can replace the example input with your own `.md`, `.markdown`, `.txt`, `.pdf`, or `.docx` specification.

## Reports

ReqCheck generates structured reports containing:

- Extracted requirements and identifiers.
- Individual requirement quality assessments.
- Document-level observations.
- Potential contradictions and missing information.
- Acceptance criteria coverage.
- Prioritized findings and recommendations.

AI-generated findings are checked against source evidence. Unsupported quotations and findings may be discarded during verification.

JSON output is available through the optional `--json` argument.

## Testing

Run the automated test suite from the repository root:

```bash
python -m unittest discover -s tests -t . -v
```

The test suite covers:

- Command-line behavior and error handling.
- Document loading and parsing.
- Deterministic validation rules.
- AI response handling and fallback behavior.
- Analysis pipeline stages.
- Evidence verification.
- Error recovery and robustness.

## Limitations

- AI-generated findings may be incorrect or incomplete and require human review.
- Analysis quality and availability depend on the configured model and external API service.
- API quotas, rate limits, and service outages may affect AI-assisted analysis.
- Scanned PDFs without an extractable text layer are not supported because OCR is not included.
- Rule-based validation relies on predefined patterns and cannot detect every requirements defect.
- A successful analysis does not guarantee that a specification is complete or implementation-ready.

## Documentation

- [Russian Runbook](RUNBOOK.md) — setup, configuration, quota limits, testing, evaluation, and troubleshooting.

## Disclaimer

ReqCheck is an automated requirements review assistant. Its findings are advisory and should be evaluated by qualified reviewers before being used for development or business decisions.
