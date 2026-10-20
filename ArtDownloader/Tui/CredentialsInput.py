import re
from rich.text import Text
from textual.widgets import TextArea


FIELD_NAME: re.Pattern[str] = re.compile(r'(?:^|[&\s])(api_key|user_id)(?=\s*=)')
SEPARATOR: re.Pattern[str] = re.compile(r'[&=]')


class CredentialsInput(TextArea):
    def get_line(self, line_index: int) -> Text:
        line: Text = super().get_line(line_index)
        colors: dict[str, str] = self.app.get_css_variables()
        for match in FIELD_NAME.finditer(line.plain):
            line.stylize(colors['text-highlight'], *match.span(1))
        for match in SEPARATOR.finditer(line.plain):
            line.stylize(colors['secondary'], *match.span())
        return line
