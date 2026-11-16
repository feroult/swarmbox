"""wait_until: poll a condition with a short step and a timeout, instead of a fixed sleep.

    from waiting import wait_until
    self.assertTrue(wait_until(lambda: os.path.exists(marker), 5), "the marker never appeared")

It returns the first truthy value the function gives (so it can also fetch what it waited for), or the last falsy one when the time is
up; it never raises on timeout, so the assertion that follows says what was expected.
"""
import time


def wait_until(fn, seconds=10.0, step=0.02):
    end = time.monotonic() + seconds
    while True:
        try:
            value = fn()
        except OSError:    # a file that is not there yet, a connection that is not up yet
            value = None
        if value or time.monotonic() >= end:
            return value
        time.sleep(step)

