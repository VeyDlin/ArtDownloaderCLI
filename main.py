from pathlib import Path
from ArtDownloader.Config import load_config
from ArtDownloader.Tui import ArtDownloaderApp
import sys


# A release build keeps data/ and .config/ next to the executable, not in its
# temporary unpack folder.
ROOT: Path = Path(sys.executable if getattr(sys, 'frozen', False) else __file__).resolve().parent


def main() -> int:
    try:
        config = load_config(ROOT)
    except (OSError, ValueError) as err:
        print(f'Cannot read config: {err}', file=sys.stderr)
        return 1

    ArtDownloaderApp(config).run()

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
