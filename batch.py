"""batch.py: run a JSONL of prompts through an LLM, answers back as JSONL.

Resumable: ids already present in the output file are skipped, so re-running
after an interruption only does the work that is left.
"""
import argparse
import json
import os
import random
import sys
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor

from openai import OpenAI

# USD per 1M tokens (input, output). Rough figures, for an estimate only.
PRICES = {"gpt-4o-mini": (0.15, 0.60), "gpt-4o": (2.50, 10.00)}


class NoContent(Exception):
    """The API replied but carried no assistant text (refusal, tool call...)."""


def status_of(err):
    """Best-effort HTTP status from an exception; None if not an API error."""
    for attr in ("status_code", "http_status"):
        val = getattr(err, attr, None)
        if isinstance(val, int):
            return val
    resp = getattr(err, "response", None)
    val = getattr(resp, "status_code", None)
    return val if isinstance(val, int) else None


def retryable(err):
    """429 and 5xx deserve another attempt. Other 4xx never will succeed."""
    if isinstance(err, NoContent):
        return False
    code = status_of(err)
    if code is None:
        return True                      # transport error / timeout
    if code == 429:
        return True
    return code >= 500


class RateLimiter:
    """Sliding-window limiter over requests/min and tokens/min. 0 disables."""

    def __init__(self, rpm, tpm):
        self.rpm = max(0, rpm)
        self.tpm = max(0, tpm)
        self.lock = threading.Lock()
        self.reqs = deque()
        self.toks = deque()

    @staticmethod
    def _trim(window, now):
        while window and now - window[0][0] >= 60.0:
            window.popleft()

    def acquire(self, est_tokens):
        if not self.rpm and not self.tpm:
            return
        while True:
            with self.lock:
                now = time.monotonic()
                self._trim(self.reqs, now)
                self._trim(self.toks, now)
                wait = 0.0
                if self.rpm and len(self.reqs) >= self.rpm:
                    wait = max(wait, 60.0 - (now - self.reqs[0][0]))
                if self.tpm and self.toks:
                    used = sum(tok for _ts, tok in self.toks)
                    if used + est_tokens > self.tpm:
                        wait = max(wait, 60.0 - (now - self.toks[0][0]))
                if wait <= 0:
                    self.reqs.append((now, 1))
                    self.toks.append((now, est_tokens))
                    return
            time.sleep(min(wait, 5.0) + random.random() * 0.05)


class Progress:
    """Counters plus a one-line stderr progress display."""

    def __init__(self, total):
        self.total = total
        self.ok = 0
        self.failed = 0
        self.in_tok = 0
        self.out_tok = 0
        self.t0 = time.monotonic()
        self.lock = threading.Lock()

    def add(self, ok, in_tok=0, out_tok=0):
        with self.lock:
            if ok:
                self.ok += 1
            else:
                self.failed += 1
            self.in_tok += in_tok
            self.out_tok += out_tok
            done = self.ok + self.failed
            elapsed = time.monotonic() - self.t0
            rate = done / elapsed if elapsed > 0 else 0.0
            left = max(0, self.total - done)
            eta = int(left / rate) if rate > 0 else 0
            sys.stderr.write(
                "\r%d/%d ok=%d fail=%d %.1f req/s eta %ds    "
                % (done, self.total, self.ok, self.failed, rate, eta))
            sys.stderr.flush()

    def cost(self, model):
        price_in, price_out = PRICES.get(model, (0.0, 0.0))
        return (self.in_tok * price_in + self.out_tok * price_out) / 1e6


def load_done(path):
    """Ids already answered. A truncated line is reported, never swallowed."""
    done = set()
    if not os.path.exists(path):
        return done
    with open(path, encoding="utf-8") as f:
        for num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                done.add(json.loads(line)["id"])
            except (ValueError, KeyError, TypeError) as err:
                sys.stderr.write(
                    "warn: %s line %d unreadable (%s), that id will rerun\n"
                    % (path, num, type(err).__name__))
    return done


def ask(client, row, args, limiter, tries=4):
    """One prompt, with rate limiting and classified retries."""
    model = row.get("model") or args.model
    system = row.get("system") or args.system
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": row["prompt"]})

    kwargs = {"model": model, "messages": messages}
    temperature = row.get("temperature", args.temperature)
    if temperature is not None:
        kwargs["temperature"] = temperature
    max_tokens = row.get("max_tokens", args.max_tokens)
    if max_tokens:
        kwargs["max_tokens"] = max_tokens
    if args.seed is not None:
        kwargs["seed"] = args.seed

    # ~4 chars per token is close enough to budget the token window.
    estimate = len(row["prompt"]) // 4 + (max_tokens or 256)

    last = None
    for attempt in range(tries):
        limiter.acquire(estimate)
        try:
            resp = client.chat.completions.create(**kwargs)
            choice = resp.choices[0]
            text = choice.message.content
            if text is None:
                raise NoContent("finish_reason=%s"
                                % getattr(choice, "finish_reason", "?"))
            usage = getattr(resp, "usage", None)
            return {"text": text, "model": model,
                    "in_tok": getattr(usage, "prompt_tokens", 0) or 0,
                    "out_tok": getattr(usage, "completion_tokens", 0) or 0}
        except Exception as err:
            last = err
            if not retryable(err) or attempt == tries - 1:
                break
            # Jitter, so workers do not all retry on the same beat.
            time.sleep(min(30.0, 2 ** attempt) * (1.0 + random.random() * 0.3))
    raise last


def main():
    ap = argparse.ArgumentParser(
        prog="batch", description="run a JSONL of prompts through an LLM")
    ap.add_argument("src", help="input JSONL, one {id, prompt} object per line")
    ap.add_argument("-o", "--out", required=True, help="output JSONL")
    ap.add_argument("--errors",
                    help="failure sidecar (default: <out>.errors.jsonl)")
    ap.add_argument("--model", default="gpt-4o-mini")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--rpm", type=int, default=300,
                    help="requests per minute ceiling, 0 to disable")
    ap.add_argument("--tpm", type=int, default=200000,
                    help="tokens per minute ceiling, 0 to disable")
    ap.add_argument("--temperature", type=float, default=None)
    ap.add_argument("--max-tokens", type=int, default=None)
    ap.add_argument("--system", default=None,
                    help="system prompt applied to every row")
    ap.add_argument("--seed", type=int, default=None)
    args = ap.parse_args()

    if not os.environ.get("OPENAI_API_KEY"):
        sys.exit("OPENAI_API_KEY is not set")

    done = load_done(args.out)
    errors_path = args.errors or (args.out + ".errors.jsonl")
    client = OpenAI()
    limiter = RateLimiter(args.rpm, args.tpm)
    counts = {"bad": 0, "dup": 0, "skipped": len(done)}
    seen = set()
    write_lock = threading.Lock()

    with open(args.src, encoding="utf-8") as f:
        total = sum(1 for line in f if line.strip())
    progress = Progress(max(0, total - len(done)))

    with open(args.out, "a", encoding="utf-8") as out_f, \
            open(errors_path, "a", encoding="utf-8") as err_f:

        def emit(handle, obj):
            with write_lock:
                handle.write(json.dumps(obj, ensure_ascii=False) + "\n")
                handle.flush()

        def work(item):
            num, row = item
            try:
                res = ask(client, row, args, limiter)
            except Exception as err:
                emit(err_f, {"line": num, "id": row.get("id"),
                             "error_type": type(err).__name__,
                             "error": str(err)[:500],
                             "status": status_of(err), "row": row})
                progress.add(False)
                return
            emit(out_f, {"id": row["id"], "answer": res["text"],
                         "model": res["model"]})
            progress.add(True, res["in_tok"], res["out_tok"])

        # Bounded queue: memory stays flat no matter how big the input is.
        slots = threading.Semaphore(max(1, args.workers) * 4)
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
# TODO: clean this up
            with open(args.src, encoding="utf-8") as f:
                for num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                        row_id = row["id"]
                        prompt = row["prompt"]
                    except (ValueError, KeyError, TypeError) as err:
                        # One bad line must not take the whole run down.
                        counts["bad"] += 1
                        emit(err_f, {"line": num,
                                     "error_type": type(err).__name__,
                                     "error": str(err)[:200],
                                     "raw": line[:500]})
                        continue
                    if not isinstance(prompt, str) or not prompt.strip():
                        counts["bad"] += 1
                        emit(err_f, {"line": num, "id": row_id,
                                     "error_type": "EmptyPrompt",
                                     "error": "prompt missing or blank",
                                     "raw": line[:500]})
                        continue
                    if row_id in seen:
                        counts["dup"] += 1
                        sys.stderr.write(
                            "\nwarn: duplicate id %r on line %d, skipped\n"
                            % (row_id, num))
                        continue
                    seen.add(row_id)
                    if row_id in done:
                        continue
                    slots.acquire()
                    fut = pool.submit(work, (num, row))
                    fut.add_done_callback(lambda _f: slots.release())

    sys.stderr.write("\n")
    print("ok=%d failed=%d resumed=%d bad_lines=%d dup_ids=%d"
          % (progress.ok, progress.failed, counts["skipped"],
             counts["bad"], counts["dup"]))
    print("tokens: %d in, %d out | est. cost $%.4f"
          % (progress.in_tok, progress.out_tok, progress.cost(args.model)))
    if progress.failed or counts["bad"]:
        print("failures written to %s" % errors_path)


if __name__ == "__main__":
    main()
