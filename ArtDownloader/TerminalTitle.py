from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TextIO
from ArtDownloader.Animation import SPINNER_FRAMES, SPINNER_INTERVAL_SECONDS
import ctypes
import os
import sys
import time


APP_NAME: str = 'ArtDownloaderCLI'


@dataclass(frozen=True)
class DownloadState:
    source: str
    saved: int = 0
    paused: bool = False
    stopping: bool = False


class TerminalTitle:
    """Pure title animation; the UI only supplies download snapshots."""

    def __init__(
        self,
        writer: Callable[[str], None],
        interval: float = SPINNER_INTERVAL_SECONDS
    ) -> None:
        self.writer: Callable[[str], None] = writer
        self.interval: float = interval
        self.last_update: float = float('-inf')
        self.last_title: str = ''
        self.last_states: tuple[DownloadState, ...] = ()
        self.last_source: str = ''
        self.frame: int = 0


    def update(
        self,
        states: Sequence[DownloadState],
        now: float | None = None,
        selected_source: str = ''
    ) -> None:
        moment: float = time.monotonic() if now is None else now
        current: tuple[DownloadState, ...] = tuple(states)
        changed: bool = current != self.last_states or selected_source != self.last_source
        if not changed and moment - self.last_update < self.interval:
            return
        self.last_update = moment
        self.last_states = current
        self.last_source = selected_source
        base_title: str = f'{APP_NAME} | {selected_source}' if selected_source else APP_NAME
        title: str = base_title
        if current:
            active: bool = any(not state.paused and not state.stopping for state in current)
            parts: list[str] = []
            for state in current:
                status: str = 'stopping' if state.stopping else 'paused' if state.paused else 'downloading'
                parts.append(f'{state.source}: {status}')
            prefix: str = f'{SPINNER_FRAMES[self.frame % len(SPINNER_FRAMES)]} ' if active else ''
            title = f'{prefix}{base_title} | {"; ".join(parts)} | {sum(state.saved for state in current)} saved'
            if active:
                self.frame += 1
        else:
            self.frame = 0
        if title != self.last_title:
            self.writer(title)
            self.last_title = title


class TerminalWindow:
    """Platform output and title restoration, separate from animation logic."""

    def __init__(self, stream: TextIO | None = None, enabled: bool = True) -> None:
        self.stream: TextIO | None = stream if stream is not None else sys.__stdout__
        self.enabled: bool = enabled and self.stream is not None and self.stream.isatty()
        self.original_title: str = ''
        self.started: bool = False
        if sys.platform != 'win32' and os.environ.get('TERM') in (None, '', 'dumb'):
            self.enabled = False


    def start(self) -> None:
        if not self.enabled or self.started or self.stream is None:
            return
        if sys.platform == 'win32':
            ctypes.windll.kernel32.SetConsoleTitleW.argtypes = [ctypes.c_wchar_p]
            ctypes.windll.kernel32.GetConsoleTitleW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint]
            buffer = ctypes.create_unicode_buffer(32768)
            ctypes.windll.kernel32.GetConsoleTitleW(buffer, len(buffer))
            self.original_title = buffer.value
        else:
            self.stream.write('\x1b[22;0t')
            self.stream.flush()
        self.started = True


    def write(self, title: str) -> None:
        if not self.enabled or self.stream is None:
            return
        self.start()
        safe: str = ''.join(character for character in title if character.isprintable())
        if sys.platform == 'win32':
            ctypes.windll.kernel32.SetConsoleTitleW(safe)
        else:
            self.stream.write(f'\x1b]0;{safe}\x07')
            self.stream.flush()


    def close(self) -> None:
        if not self.enabled or not self.started or self.stream is None:
            return
        if sys.platform == 'win32':
            ctypes.windll.kernel32.SetConsoleTitleW(self.original_title)
        else:
            self.stream.write('\x1b[23;0t')
            self.stream.flush()
        self.started = False
