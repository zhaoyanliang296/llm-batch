# llm-batch

Feed a thousand prompts, get a thousand answers

Started as a weekend hack, grew on me.

## Usage

```bash
python batch.py prompts.jsonl -o answers.jsonl --workers 4 --rpm 300
```

## Install

```bash
pip install -r requirements.txt
export OPENAI_API_KEY=sk-...
```

## What it does

- Failures go to a sidecar file with error type, message and status
- Progress, token counts and a cost estimate on stderr
- Per-row overrides for model, system, temperature and max_tokens
- JSONL in, JSONL out: the input is streamed line by line
- A bad input line is logged and skipped, never fatal
- 4xx fails fast; 429 and 5xx retry with jittered backoff
- Real rate limiting: sliding windows on requests/min and tokens/min
- Idempotent: ids already in the output are skipped on a rerun

## Project structure

```text
├── docs/
│   ├── faq.md
│   ├── tradeoffs.md
│   └── usage.md
├── tests/
│   └── test_smoke.py
├── .gitignore
├── CHANGELOG.md
├── CONTRIBUTING.md
├── LICENSE
├── SECURITY.md
├── batch.py
├── prompts.sample.jsonl
└── requirements.txt
```

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m pytest -q
```

## Acknowledgments

- README structure inspired by popular OSS templates
- Thanks to everyone opening issues with ideas

## License

MIT - see [LICENSE](LICENSE).
