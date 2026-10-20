from dataclasses import replace
from datetime import date
from collections.abc import Mapping
from typing import TypeVar
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.validation import Integer
from textual.widgets import Input, Label, OptionList, Rule, Static
from rich.markup import escape
from ArtDownloader.Api.Source import Source
from ArtDownloader.Api.Sites import FilterSupport, Site, definition_for
from ArtDownloader.Api.Queries import build_query
from ArtDownloader.Api.Filters import (
    DateRange,
    Duration,
    FileType,
    Rating,
    Resolution,
    SearchFilters,
    Sort,
    count_operators
)
from ArtDownloader.Tui.Navigation import ArrowNavigation
from ArtDownloader.Tui.Sites import site_title
from ArtDownloader.Tui.Suggestions import MIN_TERM_LENGTH, NameInput, SuggestionMenu
from ArtDownloader.Tui.Widgets import Action, ChoiceOption, ChoiceRow, CycleRow, Mark
import asyncio


SORT_LABELS: dict[Sort, str] = {
    Sort.NEWEST: 'newest',
    Sort.OLDEST: 'oldest',
    Sort.UPDATED: 'updated',
    Sort.POPULARITY: 'popular',
    Sort.QUALITY: 'quality',
    Sort.RANDOM: 'random',
    Sort.RECENTLY_FAVORITED: 'recently liked',
    Sort.RECENTLY_VOTED: 'recently voted'
}

RATING_LABELS: dict[Rating, str] = {
    Rating.GENERAL: 'G',
    Rating.QUESTIONABLE: 'R15+',
    Rating.EXPLICIT: 'R18+'
}

DATE_LABELS: dict[DateRange, str] = {
    DateRange.ANY: 'any time',
    DateRange.TODAY: 'today',
    DateRange.LAST_24_HOURS: '24 hours',
    DateRange.WEEK: 'week',
    DateRange.MONTH: 'month',
    DateRange.CUSTOM: 'custom'
}

DATE_SUMMARY: dict[DateRange, str] = {
    DateRange.TODAY: 'today',
    DateRange.LAST_24_HOURS: 'last 24 hours',
    DateRange.WEEK: 'last week',
    DateRange.MONTH: 'last month'
}

STAR_LABELS: dict[int, str] = {0: 'any', 1: '1+', 2: '2+', 3: '3+', 4: '4+', 5: '5+'}

RESOLUTION_LABELS: dict[Resolution, str] = {
    Resolution.ANY: 'any',
    Resolution.HD: 'HD',
    Resolution.FULL_HD: 'Full HD',
    Resolution.QHD: '2K',
    Resolution.UHD: '4K'
}

TYPE_LABELS: dict[FileType, str] = {
    FileType.ANY: 'any',
    FileType.IMAGE: 'image',
    FileType.GIF: 'gif',
    FileType.VIDEO: 'video'
}

DURATION_LABELS: dict[Duration, str] = {
    Duration.ANY: 'any',
    Duration.UNDER_1_MIN: 'under 1 min',
    Duration.ONE_TO_FIVE_MIN: '1–5 min',
    Duration.FIVE_TO_TEN_MIN: '5–10 min',
    Duration.OVER_10_MIN: 'over 10 min'
}

USER_FIELDS: tuple[tuple[str, str], ...] = (
    ('liked-by', 'liked by'),
    ('uploaded-by', 'uploaded by'),
    ('voted-by', 'voted by')
)

SUGGEST_DEBOUNCE_SECONDS: float = 0.25
DATE_FORMAT_HINT: str = 'YYYY-MM-DD'
ChoiceValue = TypeVar('ChoiceValue')


def rating_labels(site: Site) -> dict[Rating, str]:
    if site is Site.RULE34:
        return {
            Rating.GENERAL: 'safe',
            Rating.QUESTIONABLE: 'questionable',
            Rating.EXPLICIT: 'explicit'
        }
    return RATING_LABELS


def sort_labels(site: Site) -> dict[Sort, str]:
    labels: dict[Sort, str] = {
        value: SORT_LABELS[value] for value in definition_for(site).filters.sorts
    }
    if site is Site.RULE34:
        labels[Sort.POPULARITY] = 'score'
    return labels


def summarize(filters: SearchFilters, site: Site = Site.CHAN) -> list[str]:
    """Short human-readable pieces, in the order the dialog shows them."""
    parts: list[str] = []
    if filters.sort is not Sort.NEWEST:
        parts.append(sort_labels(site)[filters.sort])

    ratings: dict[Rating, str] = rating_labels(site)
    allowed = filters.allowed_ratings()
    left_out = filters.left_out_rating()
    if len(allowed) == 1:
        parts.append(f'{ratings[allowed[0]]} only')
    elif left_out is not None:
        parts.append(f'no {ratings[left_out]}')

    if filters.date_range is DateRange.CUSTOM and filters.date_from is not None:
        parts.append(f'{filters.date_from:%Y-%m-%d} – {(filters.date_to or date.today()):%Y-%m-%d}')
    elif filters.date_range in DATE_SUMMARY:
        parts.append(DATE_SUMMARY[filters.date_range])

    if filters.min_stars:
        parts.append(f'{STAR_LABELS[filters.min_stars]} stars')
    if filters.min_score:
        parts.append(f'score ≥ {filters.min_score}')
    if filters.min_width:
        parts.append(f'width ≥ {filters.min_width}')
    if filters.min_height:
        parts.append(f'height ≥ {filters.min_height}')

    if filters.resolution is not Resolution.ANY:
        parts.append(f'≥ {RESOLUTION_LABELS[filters.resolution]}')

    if filters.file_type is not FileType.ANY:
        kind = TYPE_LABELS[filters.file_type]
        if filters.file_type is FileType.VIDEO and filters.duration is not Duration.ANY:
            kind = f'{kind} {DURATION_LABELS[filters.duration]}'
        parts.append(kind)

    for label, name in (('liked by', filters.liked_by), ('uploaded by', filters.uploaded_by), ('voted by', filters.voted_by)):
        if name.strip():
            parts.append(f'{label} {name.strip()}')

    return parts


def parse_day(text: str, name: str) -> date | None:
    cleaned = text.strip()
    if not cleaned:
        return None

    try:
        return date.fromisoformat(cleaned)
    except ValueError:
        raise ValueError(f'{name} must be a date like {DATE_FORMAT_HINT}') from None


class FiltersScreen(ModalScreen[SearchFilters | None], ArrowNavigation):
    """Search filters for one tab. Dismisses with the new filters, or None."""

    BINDINGS = [Binding('escape', 'close', 'Close')]


    def __init__(self, api: Source, filters: SearchFilters, query: str, anonymous: bool) -> None:
        super().__init__()
        # Suggestions for user names use this (anonymous) client.
        self.api: Source = api
        self.support: FilterSupport = definition_for(api.site).filters
        self.filters: SearchFilters = filters
        self.query_text: str = query
        self.anonymous: bool = anonymous


    def compose(self) -> ComposeResult:
        f = self.filters
        with Vertical(id='filters-dialog', classes='dialog'):
            with Horizontal(classes='line'):
                yield Static(f'[b]{site_title(self.api.site)}[/] filters', classes='fill')
                yield Action('esc', id='close')

            yield Rule()

            yield from self.choice_field('sort', 'sort', sort_labels(self.api.site), f.sort)

            marks: dict[object, Mark] = {rating: Mark.NOT for rating in f.excluded_ratings}
            marks.update({rating: Mark.ONLY for rating in f.only_ratings})
            with Horizontal(classes='field'):
                yield Label('age rating', classes='caption')
                yield CycleRow(list(rating_labels(self.api.site).items()), marks, id='rating')
                yield Static('[dim]click: only → not[/]', classes='unit')

            yield from self.choice_field('date', 'date', DATE_LABELS, f.date_range)
            with Horizontal(classes='field date-bounds'):
                yield Label('', classes='caption')
                yield Label('from', classes='inline-caption')
                yield Input(
                    value=f'{f.date_from:%Y-%m-%d}' if f.date_from else '',
                    placeholder=DATE_FORMAT_HINT,
                    restrict=r'[0-9-]*',
                    id='date-from',
                    compact=True,
                    classes='date'
                )
                yield Label('to', classes='inline-caption')
                yield Input(
                    value=f'{f.date_to:%Y-%m-%d}' if f.date_to else '',
                    placeholder='today',
                    restrict=r'[0-9-]*',
                    id='date-to',
                    compact=True,
                    classes='date'
                )
            yield from self.choice_field('stars', 'min rating', STAR_LABELS, f.min_stars, hint='stars and up')
            yield from self.number_field('min-score', 'min score', f.min_score, 'votes, not stars')
            yield from self.number_field('min-width', 'min width', f.min_width, 'pixels')
            yield from self.number_field('min-height', 'min height', f.min_height, 'pixels')
            yield from self.choice_field('size', 'min size', RESOLUTION_LABELS, f.resolution)
            yield from self.choice_field('type', 'file type', TYPE_LABELS, f.file_type)
            yield from self.choice_field('duration', 'duration', DURATION_LABELS, f.duration, hint='video only')

            values = {'liked-by': f.liked_by, 'uploaded-by': f.uploaded_by, 'voted-by': f.voted_by}
            for field_id, caption in USER_FIELDS:
                menu = SuggestionMenu(id=f'{field_id}-menu')
                with Vertical(classes=f'field-group user-{field_id}'):
                    with Horizontal(classes='field-row'):
                        yield Label(caption, classes='caption')
                        yield NameInput(menu, value=values[field_id], placeholder='user name', id=field_id)
                    yield menu

            # Action row: the message slot keeps its place, so nothing moves.
            with Horizontal(classes='line actions'):
                yield Static('', id='filters-message', classes='fill message')
                yield Action('reset', id='reset')
                yield Action('cancel', id='cancel')
                yield Action('❯ apply', 'accent', id='apply')


    def choice_field(
        self,
        field_id: str,
        caption: str,
        labels: Mapping[ChoiceValue, str],
        value: ChoiceValue,
        hint: str = ''
    ) -> ComposeResult:
        with Horizontal(classes='field'):
            yield Label(caption, classes='caption')
            yield ChoiceRow(list(labels.items()), value, id=field_id)
            if hint:
                yield Static(f'[dim]{hint}[/]', classes='unit')


    def number_field(self, field_id: str, caption: str, value: int, hint: str) -> ComposeResult:
        with Horizontal(classes='field'):
            yield Label(caption, classes='caption')
            yield Input(
                value=str(value) if value else '', placeholder='any',
                restrict=r'[0-9]*',
                validators=Integer(minimum=0, maximum=999999999),
                valid_empty=True, max_length=9,
                id=field_id, compact=True, classes='number'
            )
            yield Static(f'[dim]{hint}[/]', classes='unit')


    def on_mount(self) -> None:
        self.apply_capabilities()
        self.sync_dependent_fields()
        self.refresh_message()
        row = self.query_one('#sort', ChoiceRow)
        for option in row.query(ChoiceOption):
            if option.selected:
                option.focus()
                break


    def apply_capabilities(self) -> None:
        visibility: dict[str, bool] = {
            '#date': self.support.dates,
            '#stars': self.support.stars,
            '#size': self.support.resolution,
            '#type': self.support.file_type,
            '#duration': self.support.duration,
            '#min-score': self.support.score,
            '#min-width': self.support.dimensions,
            '#min-height': self.support.dimensions
        }
        for selector, visible in visibility.items():
            parent = self.query_one(selector).parent
            if parent is not None:
                parent.display = visible
        self.query_one('.date-bounds').display = self.support.dates
        for field_id, caption in USER_FIELDS:
            self.query_one(f'.user-{field_id}').display = field_id in self.support.user_fields


    def on_choice_row_changed(self, event: ChoiceRow.Changed) -> None:
        self.sync_dependent_fields()
        self.refresh_message()


    def on_cycle_row_changed(self, event: CycleRow.Changed) -> None:
        self.refresh_message()


    def on_input_changed(self, event: Input.Changed) -> None:
        if self.support.user_suggestions and event.input.id in self.support.user_fields and event.input.has_focus:
            self.suggest_users(event.input.id, event.value)

        self.refresh_message()


    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id in {field_id for field_id, _ in USER_FIELDS}:
            menu = self.query_one(f'#{event.input.id}-menu', SuggestionMenu)
            choice = menu.selected()
            if choice is not None:
                self.query_one(f'#{event.input.id}', NameInput).accept(choice)
                return

        self.apply()


    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        menu_id = event.option_list.id or ''
        if event.option.id is None or not menu_id.endswith('-menu'):
            return

        field = self.query_one(f'#{menu_id.removesuffix("-menu")}', NameInput)
        field.accept(event.option.id)
        field.focus()


    def on_action_pressed(self, event: Action.Pressed) -> None:
        action_id = event.action.id
        if action_id == 'apply':
            self.apply()
        elif action_id == 'reset':
            self.reset()
        elif action_id in ('cancel', 'close'):
            self.action_close()


    def action_close(self) -> None:
        self.dismiss(None)


    @work(exclusive=True, group='users', exit_on_error=False)
    async def suggest_users(self, field_id: str, value: str) -> None:
        menu = self.query_one(f'#{field_id}-menu', SuggestionMenu)
        if len(value.strip()) < MIN_TERM_LENGTH:
            menu.close()
            return

        # Exclusive: a newer keystroke cancels this worker during the sleep.
        await asyncio.sleep(SUGGEST_DEBOUNCE_SECONDS)
        names = await asyncio.to_thread(self.api.autocomplete_users, value)
        if self.query_one(f'#{field_id}', NameInput).has_focus:
            menu.show_names(value, names)


    def sync_dependent_fields(self) -> None:
        """Date inputs only for a custom range, duration only for video."""
        custom = self.query_one('#date', ChoiceRow).value is DateRange.CUSTOM
        for selector in ('#date-from', '#date-to'):
            self.query_one(selector, Input).disabled = not custom

        video = self.query_one('#type', ChoiceRow).value is FileType.VIDEO
        self.query_one('#duration', ChoiceRow).disabled = not video


    def reset(self) -> None:
        defaults = SearchFilters()
        self.query_one('#sort', ChoiceRow).select(defaults.sort)
        self.query_one('#rating', CycleRow).clear()
        self.query_one('#date', ChoiceRow).select(defaults.date_range)
        self.query_one('#stars', ChoiceRow).select(defaults.min_stars)
        self.query_one('#size', ChoiceRow).select(defaults.resolution)
        self.query_one('#type', ChoiceRow).select(defaults.file_type)
        self.query_one('#duration', ChoiceRow).select(defaults.duration)
        for selector in ('#date-from', '#date-to', '#liked-by', '#uploaded-by', '#voted-by'):
            self.query_one(selector, Input).value = ''
        for selector in ('#min-score', '#min-width', '#min-height'):
            self.query_one(selector, Input).value = ''

        self.sync_dependent_fields()
        self.refresh_message()


    def read_form(self) -> SearchFilters:
        date_range: DateRange = self.choice_value('#date', DateRange)
        date_from = parse_day(self.query_one('#date-from', Input).value, 'from')
        date_to = parse_day(self.query_one('#date-to', Input).value, 'to')
        if date_range is DateRange.CUSTOM:
            if date_from is None:
                raise ValueError(f'a custom date range needs a start date ({DATE_FORMAT_HINT})')
            if date_to is not None and date_to < date_from:
                raise ValueError('the end date is before the start date')

        ratings = self.query_one('#rating', CycleRow)
        filters = replace(
            self.filters,
            sort=self.choice_value('#sort', Sort),
            only_ratings=frozenset(value for value in ratings.marked(Mark.ONLY) if isinstance(value, Rating)),
            excluded_ratings=frozenset(value for value in ratings.marked(Mark.NOT) if isinstance(value, Rating)),
            date_range=date_range,
            date_from=date_from if date_range is DateRange.CUSTOM else None,
            date_to=date_to if date_range is DateRange.CUSTOM else None,
            min_stars=self.choice_value('#stars', int),
            min_score=self.read_number('#min-score', 'score'),
            min_width=self.read_number('#min-width', 'width'),
            min_height=self.read_number('#min-height', 'height'),
            resolution=self.choice_value('#size', Resolution),
            file_type=self.choice_value('#type', FileType),
            duration=self.choice_value('#duration', Duration),
            liked_by=self.query_one('#liked-by', Input).value.strip(),
            uploaded_by=self.query_one('#uploaded-by', Input).value.strip(),
            voted_by=self.query_one('#voted-by', Input).value.strip()
        )
        if not filters.allowed_ratings():
            raise ValueError('every age rating is excluded')
        build_query(self.api.site, '', filters)

        return filters


    def choice_value(self, selector: str, kind: type[ChoiceValue]) -> ChoiceValue:
        value: object = self.query_one(selector, ChoiceRow).value
        if not isinstance(value, kind):
            raise ValueError('Select a valid filter option')
        return value


    def read_number(self, selector: str, label: str) -> int:
        value: str = self.query_one(selector, Input).value.strip()
        if not value:
            return 0
        if not value.isascii() or not value.isdigit() or len(value) > 9:
            raise ValueError(f'{label} must be a whole number from 0 to 999999999')
        return int(value)


    def operator_count(self, filters: SearchFilters) -> int:
        return count_operators(build_query(self.api.site, self.query_text, filters))


    def refresh_message(self) -> None:
        """Keeps the anonymous operator-tag budget visible while filters change."""
        message = self.query_one('#filters-message', Static)
        limit: int | None = self.support.anonymous_limit
        if limit is None:
            message.update('')
            return
        try:
            filters = self.read_form()
        except ValueError:
            message.update('')
            return

        used = self.operator_count(filters)
        if not self.anonymous:
            message.update(f'[dim]{used} advanced filter(s)[/]' if used else '')
            return

        if used > limit:
            message.update(
                f'[$error]{used} advanced filters · {limit} allowed without sign-in[/]'
            )
            return

        message.update(f'[dim]advanced filters {used}/{limit} without sign-in[/]')


    def apply(self) -> None:
        message = self.query_one('#filters-message', Static)
        try:
            filters = self.read_form()
        except ValueError as err:
            message.update(f'[$error]{escape(str(err))}[/]')
            return

        limit: int | None = self.support.anonymous_limit
        if self.anonymous and limit is not None and self.operator_count(filters) > limit:
            message.update(
                f'[$error]Sankaku allows {limit} advanced filters without sign-in · '
                'remove some or sign in[/]'
            )
            return

        self.dismiss(filters)
