from datetime import datetime
from ArtDownloader.Api.Filters import (
    Duration, FileType, Rating, Resolution, SearchFilters, Sort, combine_query, user_name
)
from ArtDownloader.Api.Sites import Site, definition_for


RULE34_SORTS: dict[Sort, str] = {
    Sort.NEWEST: '',
    Sort.OLDEST: 'sort:id:asc',
    Sort.POPULARITY: 'sort:score:desc',
    Sort.UPDATED: 'sort:updated:desc',
    Sort.RANDOM: 'sort:random'
}
RULE34_RATINGS: dict[Rating, str] = {
    Rating.GENERAL: 'safe',
    Rating.QUESTIONABLE: 'questionable',
    Rating.EXPLICIT: 'explicit'
}
DANBOORU_SORTS: dict[Sort, str] = {
    Sort.NEWEST: '',
    Sort.OLDEST: 'order:id_asc',
    Sort.POPULARITY: 'order:score',
    Sort.UPDATED: 'order:change'
}
DANBOORU_RATINGS: dict[Rating, str] = {
    Rating.GENERAL: 'g', Rating.SENSITIVE: 's', Rating.QUESTIONABLE: 'q', Rating.EXPLICIT: 'e'
}
DANBOORU_FILE_TYPES: dict[FileType, str] = {
    FileType.ANY: '',
    FileType.IMAGE: 'filetype:jpg,png,gif,webp,avif',
    FileType.GIF: 'filetype:gif',
    FileType.VIDEO: 'filetype:mp4,webm'
}


def build_query(site: Site, query: str, filters: SearchFilters) -> str:
    support = definition_for(site).filters
    if filters.sort not in support.sorts:
        raise ValueError('This sort order is not supported by this site')
    if (filters.only_ratings | filters.excluded_ratings) - set(support.ratings):
        raise ValueError('These content ratings are not supported by this site')
    if not filters.allowed_ratings(support.ratings):
        raise ValueError('Every age rating is excluded')
    if site is Site.DANBOORU:
        return danbooru_query(query, filters)

    if site is not Site.RULE34:
        if filters.min_score or filters.min_width or filters.min_height:
            raise ValueError('Use the size and star filters for Sankaku')
        return combine_query(query, filters)

    supported: SearchFilters = SearchFilters(
        sort=filters.sort,
        only_ratings=filters.only_ratings,
        excluded_ratings=filters.excluded_ratings,
        min_score=filters.min_score,
        min_width=filters.min_width,
        min_height=filters.min_height,
        uploaded_by=filters.uploaded_by
    )
    if supported != filters:
        raise ValueError('These filters are not supported by Rule34')
    if min(filters.min_score, filters.min_width, filters.min_height) < 0:
        raise ValueError('Score and dimensions must be zero or greater')

    tags: list[str] = [query.strip(), RULE34_SORTS[filters.sort]]
    allowed: list[Rating] = filters.allowed_ratings()
    if not allowed:
        raise ValueError('Every age rating is excluded')
    if len(allowed) == 1:
        tags.append(f'rating:{RULE34_RATINGS[allowed[0]]}')
    else:
        left_out: Rating | None = filters.left_out_rating()
        if left_out is not None:
            tags.append(f'-rating:{RULE34_RATINGS[left_out]}')

    for name, value in (
        ('score', filters.min_score), ('width', filters.min_width), ('height', filters.min_height)
    ):
        if value:
            tags.append(f'{name}:>={value}')
    if filters.uploaded_by.strip():
        tags.append(f'user:{user_name(filters.uploaded_by)}')

    return ' '.join(tag for tag in tags if tag)


def danbooru_query(query: str, filters: SearchFilters) -> str:
    if filters.min_stars or filters.voted_by.strip():
        raise ValueError('Star ratings and voted-by filters are not supported by Danbooru')
    if min(filters.min_score, filters.min_width, filters.min_height) < 0:
        raise ValueError('Score and dimensions must be zero or greater')
    tags: list[str] = [query.strip(), DANBOORU_SORTS[filters.sort]]
    allowed: list[Rating] = filters.allowed_ratings(tuple(DANBOORU_RATINGS))
    if len(allowed) == 1:
        tags.append(f'rating:{DANBOORU_RATINGS[allowed[0]]}')
    else:
        tags.extend(f'-rating:{code}' for rating, code in DANBOORU_RATINGS.items() if rating not in allowed)
    start, end = filters.date_bounds(datetime.now().astimezone())
    if start is not None and end is not None:
        tags.append(f'date:{start.isoformat()}...{end.isoformat()}')
    for name, value in (
        ('score', filters.min_score), ('width', filters.min_width), ('height', filters.min_height)
    ):
        if value:
            tags.append(f'{name}:>={value}')
    if filters.resolution is not Resolution.ANY:
        tags.append(f'mpixels:>={filters.resolution.value:g}')
    tags.append(DANBOORU_FILE_TYPES[filters.file_type])
    if filters.file_type is FileType.VIDEO and filters.duration is not Duration.ANY:
        low, high = filters.duration.value
        tags.append(f'duration:>={low}' if high is None else f'duration:{low}..{high}')
    for name, username in (('fav', filters.liked_by), ('user', filters.uploaded_by)):
        if username.strip():
            tags.append(f'{name}:{user_name(username)}')
    return ' '.join(tag for tag in tags if tag)
