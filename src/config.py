"""
Printer configuration settings.
"""

DPI = 203
LOGGING_LEVEL = "INFO"

DEFAULT_FONT = "0"
DEFAULT_FONT_SIZE = 20

# Quality levels for the ^BX Data Matrix barcode command:
# Acceptable values: 0, 50, 80, 100, 140, 200.
# While the ZPL default is 0, ECC 200 (i.e. quality 200) is recommended for new applications.
DEFAULT_BARCODE_QUALITY = 200
