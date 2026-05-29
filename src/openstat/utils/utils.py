import time

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from src.utils.net import is_internet_available, require_internet, wait_for_internet

__all__ = [
    "wait_for_selector_with_retry",
    "is_internet_available",
    "wait_for_internet",
    "require_internet",
]


def wait_for_selector_with_retry(page, selector, timeout=30000, retry_interval=5, max_attempts=None):
    """Retries waiting for a selector, reloads the page if necessary, and handles internet loss."""
    attempt = 1
    while True:
        try:
            return page.wait_for_selector(selector, timeout=timeout)
        except PlaywrightTimeoutError:
            print(f"[Attempt {attempt}] Timeout waiting for selector: {selector}")
            if not is_internet_available():
                print("Internet lost. Waiting to reconnect...")
                wait_for_internet()
                print("Reloading page after reconnecting...")
            else:
                print(f"⚠ Selector not found. Reloading page in {retry_interval} seconds...")
                time.sleep(retry_interval)
            try:
                page.reload(timeout=timeout)
                page.wait_for_load_state("networkidle", timeout=timeout)
            except Exception as e:
                print(f"Reload failed: {e}. Retrying...")
            attempt += 1
            if max_attempts and attempt > max_attempts:
                raise Exception(f"Max attempts reached for selector: {selector}")
