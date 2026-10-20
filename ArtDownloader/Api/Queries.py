from ArtDownloader.Api.Filters import Rating, SearchFilters, Sort, combine_query, user_name
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


def build_query(site: Site, query: str, filters: SearchFilters) -> str:
    if filters.sort not in definition_for(site).filters.sorts:
        raise ValueError('This sort order is not supported by this site')

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
