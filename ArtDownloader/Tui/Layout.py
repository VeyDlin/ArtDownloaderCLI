from textual.containers import Horizontal
from textual.geometry import Region, Size, Spacing
from textual.layout import ArrangeResult, WidgetPlacement
from textual.layouts.horizontal import HorizontalLayout
from textual.widget import Widget


class WrappedRowLayout(HorizontalLayout):
    def arrange(
        self, parent: Widget, children: list[Widget], size: Size, greedy: bool = True
    ) -> ArrangeResult:
        measured: ArrangeResult = super().arrange(parent, children, size, greedy)
        placements: ArrangeResult = []
        x: int = 0
        y: int = 0
        row_height: int = 0
        previous_right: int = 0
        for placement in measured:
            margin: Spacing = placement.margin
            width: int = placement.region.width
            gap: int = max(previous_right, margin.left)
            if x and x + gap + width + margin.right > size.width:
                x = 0
                y += row_height
                row_height = 0
                gap = margin.left
            x += gap
            region: Region = Region(x, y + margin.top, width, placement.region.height)
            placements.append(WidgetPlacement(
                region, placement.offset, margin, placement.widget,
                placement.order, placement.fixed, placement.overlay, placement.absolute
            ))
            x += width
            previous_right = margin.right
            row_height = max(row_height, margin.top + region.height + margin.bottom)
        return placements


class WrappedRow(Horizontal):
    DEFAULT_CSS = '''
    WrappedRow {
        width: 1fr;
        height: auto;
    }
    '''


    @property
    def layout(self) -> WrappedRowLayout:
        return WrappedRowLayout()


class BottomAlignedRow(Horizontal):
    def process_layout(self, placements: list[WidgetPlacement]) -> list[WidgetPlacement]:
        bottom: int = max(
            (placement.region.bottom + placement.margin.bottom for placement in placements),
            default=0
        )
        return [
            WidgetPlacement(
                placement.region.translate((0, bottom - placement.margin.bottom - placement.region.bottom)),
                placement.offset, placement.margin, placement.widget,
                placement.order, placement.fixed, placement.overlay, placement.absolute
            )
            for placement in placements
        ]
