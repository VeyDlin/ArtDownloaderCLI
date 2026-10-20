from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any
from ArtDownloader.Api.Sites import Site
import json
import threading


CONFIG_DIR: str = '.config'
SETTINGS_FILE: str = 'settings.json'
SESSION_FILE: str = 'session.json'

# Pre-.config layout, read once so an upgrade keeps the save folder and session.
LEGACY_CONFIG_FILES: tuple[str, ...] = ('config.user.json', 'config.json')
LEGACY_TOKENS_FILE: str = 'config.tokens.json'

DEFAULT_SAVE_DIR: str = 'data'
MAX_DELAY_SECONDS: float = 600.0
MIN_PARALLEL_DOWNLOADS: int = 1
MAX_PARALLEL_DOWNLOADS: int = 4
TAG_FORMATS: tuple[str, ...] = ('txt', 'json')


@dataclass
class Settings:
    """One source's settings. Credentials live separately in the session store."""

    save_dir: str = DEFAULT_SAVE_DIR
    page_delay: float = 3.0
    download_delay: float = 0.0
    jitter: float = 0.0
    parallel_downloads: int = 1
    # Tag sidecars to write next to each file: 'txt' (one line) and/or 'json'
    # (post metadata and tag categories when the source provides them).
    tag_formats: tuple[str, ...] = ('txt',)
    split_by_format: bool = False
    skip_existing: bool = True


    def normalized(self) -> 'Settings':
        """Clamps every value into its valid range."""
        return Settings(
            save_dir=self.save_dir.strip() or DEFAULT_SAVE_DIR,
            page_delay=clamp(self.page_delay, 0.0, MAX_DELAY_SECONDS),
            download_delay=clamp(self.download_delay, 0.0, MAX_DELAY_SECONDS),
            jitter=clamp(self.jitter, 0.0, MAX_DELAY_SECONDS),
            parallel_downloads=int(clamp(self.parallel_downloads, MIN_PARALLEL_DOWNLOADS, MAX_PARALLEL_DOWNLOADS)),
            tag_formats=tuple(name for name in TAG_FORMATS if name in self.tag_formats),
            split_by_format=self.split_by_format,
            skip_existing=self.skip_existing
        )


class AppConfig:
    """Per-site settings plus where they live. Everything is kept in <project>/.config."""

    def __init__(self, root: Path, settings: dict[Site, Settings]) -> None:
        self.root: Path = root
        self.settings: dict[Site, Settings] = settings
        self.lock: threading.Lock = threading.Lock()


    @property
    def config_dir(self) -> Path:
        return self.root / CONFIG_DIR


    @property
    def settings_path(self) -> Path:
        return self.config_dir / SETTINGS_FILE


    @property
    def session_path(self) -> Path:
        return self.config_dir / SESSION_FILE


    def settings_for(self, site: Site) -> Settings:
        return self.settings.get(site) or default_settings(site)


    def save_root(self, site: Site) -> Path:
        """The site's save folder: absolute as given, or relative to the project."""
        return resolve_path(self.root, self.settings_for(site).save_dir)


    def update(self, site: Site, settings: Settings) -> None:
        self.settings[site] = settings.normalized()
        self.save()


    def save(self) -> None:
        with self.lock:
            self.config_dir.mkdir(parents=True, exist_ok=True)
            data = {site.value: asdict(self.settings_for(site)) for site in Site}
            with self.settings_path.open('w', encoding='utf-8') as file:
                json.dump(data, file, indent=4)


def default_settings(site: Site, base_dir: str = DEFAULT_SAVE_DIR) -> Settings:
    """Each site saves into its own sub-folder: post ids of different sites are
    unrelated and would overwrite each other in a shared folder."""
    base = base_dir.rstrip('/\\') or DEFAULT_SAVE_DIR

    return Settings(save_dir=f'{base}/{site.value}')


def resolve_path(root: Path, value: str) -> Path:
    path = Path(value.strip() or DEFAULT_SAVE_DIR).expanduser()
    if path.is_absolute():
        return path

    return root / path


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def load_config(root: Path) -> AppConfig:
    config = AppConfig(root, {})

    if config.settings_path.exists():
        config.settings = read_settings(config.settings_path)
    else:
        legacy_dir = read_legacy_save_dir(root)
        config.settings = {site: default_settings(site, legacy_dir) for site in Site}
        config.save()

    migrate_legacy_session(root, config.session_path)

    return config


def read_settings(path: Path) -> dict[Site, Settings]:
    try:
        with path.open('r', encoding='utf-8') as file:
            raw = json.load(file)
    except (OSError, json.JSONDecodeError):
        raw = None

    if not isinstance(raw, dict):
        return {site: default_settings(site) for site in Site}

    per_site = any(isinstance(raw.get(site.value), dict) for site in Site)
    result: dict[Site, Settings] = {}
    for site in Site:
        if per_site:
            entry = raw.get(site.value)
            result[site] = settings_from(entry if isinstance(entry, dict) else {}, default_settings(site))
            continue

        # Earlier shared settings: each source inherits its own sub-folder.
        shared = settings_from(raw, Settings())
        result[site] = settings_from(
            {**asdict(shared), 'save_dir': default_settings(site, shared.save_dir).save_dir},
            default_settings(site)
        )

    return result


def settings_from(raw: dict[str, Any], defaults: Settings) -> Settings:
    values: dict[str, Any] = {}
    for field in fields(Settings):
        if field.name == 'tag_formats':
            values[field.name] = read_tag_formats(raw, defaults.tag_formats)
            continue

        values[field.name] = coerce(raw.get(field.name), getattr(defaults, field.name))

    return Settings(**values).normalized()


def read_tag_formats(raw: dict[str, Any], default: tuple[str, ...]) -> tuple[str, ...]:
    value = raw.get('tag_formats')
    if isinstance(value, list):
        return tuple(name for name in TAG_FORMATS if name in value)

    # Older files stored a yes/no 'save_tags'.
    legacy = raw.get('save_tags')
    if isinstance(legacy, bool):
        return ('txt',) if legacy else ()

    return default


def coerce(value: Any, default: Any) -> Any:
    """Keeps a stored value only when it has the setting's type (ints pass as floats)."""
    if isinstance(value, bool) != isinstance(default, bool):
        return default

    if isinstance(default, float) and isinstance(value, (int, float)):
        return float(value)

    if isinstance(value, type(default)):
        return value

    return default


def read_legacy_save_dir(root: Path) -> str:
    for name in LEGACY_CONFIG_FILES:
        path = root / name
        if not path.exists():
            continue

        try:
            with path.open('r', encoding='utf-8') as file:
                raw = json.load(file)
        except (OSError, json.JSONDecodeError):
            continue

        save = raw.get('save') if isinstance(raw, dict) else None
        save_dir = save.get('save_dir') if isinstance(save, dict) else None
        if isinstance(save_dir, str) and save_dir.strip():
            return save_dir.strip()

    return DEFAULT_SAVE_DIR


def migrate_legacy_session(root: Path, session_path: Path) -> None:
    legacy = root / LEGACY_TOKENS_FILE
    if not legacy.exists() or session_path.exists():
        return

    session_path.parent.mkdir(parents=True, exist_ok=True)
    legacy.replace(session_path)
