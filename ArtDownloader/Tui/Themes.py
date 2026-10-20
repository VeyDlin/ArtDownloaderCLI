from dataclasses import dataclass
from textual.theme import Theme
from ArtDownloader.Api.Sites import Site
from ArtDownloader.Tui import Palette


@dataclass(frozen=True)
class ThemeSettings:
    accent: str
    highlight: str = Palette.HIGHLIGHT


SOURCE_STYLES: dict[Site, ThemeSettings] = {
    Site.CHAN: ThemeSettings(accent=Palette.ACCENT),
    Site.IDOL: ThemeSettings(accent=Palette.ACCENT),
    Site.RULE34: ThemeSettings(accent=Palette.SUCCESS),
    Site.DANBOORU: ThemeSettings(accent='#6ea8e0', highlight='#c8bd91')
}


def create_theme(site: Site, settings: ThemeSettings) -> Theme:
    return Theme(
        name=f'art-downloader-{site.value}',
        primary=settings.accent,
        accent=settings.accent,
        secondary=Palette.SECONDARY,
        success=Palette.SUCCESS,
        warning=Palette.WARNING,
        error=Palette.ERROR,
        foreground=Palette.FOREGROUND,
        background=Palette.BACKGROUND,
        surface=Palette.SURFACE,
        panel=Palette.PANEL,
        variables={
            'text-highlight': settings.highlight,
            **{f'source-{source.value}': style.accent for source, style in SOURCE_STYLES.items()}
        },
        dark=True
    )


SOURCE_THEMES: dict[Site, Theme] = {
    site: create_theme(site, settings) for site, settings in SOURCE_STYLES.items()
}
