from collections.abc import Callable
from pathlib import Path
from tempfile import NamedTemporaryFile
import requests


CHUNK_SIZE: int = 1 << 16


def save_response(
    response: requests.Response,
    destination: Path,
    should_abort: Callable[[], bool] | None = None,
    on_progress: Callable[[int, int | None], None] | None = None
) -> bool:
    """Replace the destination only after a complete, uncancelled transfer."""
    temporary: Path | None = None
    received: int = 0
    try:
        with response:
            header: str = response.headers.get('Content-Length', '')
            total: int | None = int(header) if header.isdigit() else None
            if should_abort is not None and should_abort():
                return False
            if on_progress is not None:
                on_progress(0, total)
            with NamedTemporaryFile(
                dir=destination.parent, prefix=f'.{destination.name}.', suffix='.part', delete=False
            ) as stream:
                temporary = Path(stream.name)
                for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                    if should_abort is not None and should_abort():
                        return False
                    if not chunk:
                        continue
                    stream.write(chunk)
                    received += len(chunk)
                    if on_progress is not None:
                        on_progress(received, total)
            if should_abort is not None and should_abort():
                return False
            if total is not None and not response.headers.get('Content-Encoding') and received != total:
                raise requests.ConnectionError('The server sent an incomplete file')
            if received == 0:
                raise requests.ConnectionError('The server sent an empty file')
        temporary.replace(destination)
        return True
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
