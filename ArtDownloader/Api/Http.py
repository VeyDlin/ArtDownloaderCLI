from threading import Event, Lock, Thread, current_thread
import requests
import time


class RequestCancelled(Exception):
    """The user stopped a pending API request."""


class SessionPool:
    """Reuse connections per live worker and retire completed workers on access."""

    def __init__(self) -> None:
        self.lock: Lock = Lock()
        self.sessions: dict[Thread, requests.Session] = {}
        self.closed: bool = False


    def current(self) -> requests.Session:
        with self.lock:
            if self.closed:
                raise RequestCancelled()
            completed: list[Thread] = [worker for worker in self.sessions if not worker.is_alive()]
            for worker in completed:
                self.sessions.pop(worker).close()
            owner: Thread = current_thread()
            session: requests.Session | None = self.sessions.get(owner)
            if session is None:
                session = requests.Session()
                session.headers['User-Agent'] = 'ArtDownloaderCLI/1.0'
                self.sessions[owner] = session
            return session


    def close(self) -> None:
        with self.lock:
            self.closed = True
            for session in self.sessions.values():
                session.close()
            self.sessions.clear()


class RateLimiter:
    """Shared pacing and server cooldown for all calls to one provider."""

    def __init__(self, interval: float) -> None:
        self.interval: float = max(0.0, interval)
        self.next_request: float = 0.0
        self.lock: Lock = Lock()


    def wait(self, cancelled: Event | None = None) -> None:
        while True:
            if cancelled is not None and cancelled.is_set():
                raise RequestCancelled()
            with self.lock:
                now: float = time.monotonic()
                delay: float = self.next_request - now
                if delay <= 0:
                    self.next_request = now + self.interval
                    return
            if cancelled is None:
                time.sleep(min(delay, 0.1))
            elif cancelled.wait(min(delay, 0.1)):
                raise RequestCancelled()


    def defer(self, seconds: float) -> None:
        with self.lock:
            self.next_request = max(self.next_request, time.monotonic() + max(0.0, seconds))
