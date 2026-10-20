# U+2733 renders as a color emoji in Windows Terminal; U+2737 remains text.
# Dingbat frames share an advance width in Windows title fonts; middle dot does not.
SPINNER_FRAMES: tuple[str, ...] = ('✻', '✽', '✶', '✷', '✢', '✷', '✶', '✽')
SPINNER_INTERVAL_SECONDS: float = 0.12
