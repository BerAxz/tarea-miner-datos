"""Ordered, bounded concurrency, including on Python 3.10."""

from collections import deque
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait


def bounded_map(function, values, workers):
    if workers < 1:
        raise ValueError("workers debe ser mayor que cero")
    with ThreadPoolExecutor(max_workers=workers) as executor:
        pending = deque()
        values = iter(values)
        for _ in range(workers * 2):
            try:
                pending.append(executor.submit(function, next(values)))
            except StopIteration:
                break
        while pending:
            yield pending.popleft().result()
            try:
                pending.append(executor.submit(function, next(values)))
            except StopIteration:
                pass


def bounded_unordered_map(function, values, workers):
    """Checkpoint finished batches immediately, even if an earlier batch is slow."""
    if workers < 1:
        raise ValueError("workers debe ser mayor que cero")
    values = iter(values)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        pending = set()

        def submit():
            try:
                pending.add(executor.submit(function, next(values)))
            except StopIteration:
                pass

        for _ in range(workers * 2):
            submit()
        while pending:
            done, pending = wait(pending, return_when=FIRST_COMPLETED)
            error = None
            for future in done:
                try:
                    result = future.result()
                except Exception as exc:
                    error = exc
                    continue
                yield result
                submit()
            if error is not None:
                for future in pending:
                    future.cancel()
                raise error
