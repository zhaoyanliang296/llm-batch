# Trade-offs

## Threads, not the async client

The work is IO-bound and a thread pool keeps this readable. `AsyncOpenAI`
with `asyncio.gather` reaches a higher ceiling per process; if you need more
than a few hundred requests a minute, switch.

## When the Batch API is the better tool

This script uses the normal chat completions endpoint, which is right when
you want answers now and want to watch progress.

OpenAI's Batch API costs roughly half as much and has far higher limits, but
results arrive inside a 24 hour window. For large offline jobs -- backfills,
evaluations, dataset generation -- Batch is usually the better deal and this
script is the wrong tool.

| Situation | Use |
|---|---|
| Must finish in minutes | this script |
| Iterating on prompts | this script |
| Thousands of rows, hours are fine | Batch API |
| Cost is the binding constraint | Batch API |

## About the cost estimate

`PRICES` in `batch.py` is hardcoded and will drift. Check current pricing
before trusting the figure printed at the end of a run.
