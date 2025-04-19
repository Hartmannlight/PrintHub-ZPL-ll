# src/main.py

"""
Entry point for the PrintHub ZPL API:
- konfiguriert Logging
- führt einen Testdruck durch
- startet den FastAPI/Uvicorn‑Server
"""

import logging
import uvicorn

from src.api import app
from src.printing import get_printer


def perform_test_print() -> None:
    """
    Sendet einen einfachen ZPL‑Teststring an den konfigurierten Drucker.
    """
    printer = get_printer()
    test_zpl = "^XA^FO50,50^ADN,36,20^FDTest ZPL Print^FS^XZ"

    logging.info(
        "Sending test ZPL to printer '%s' using %s backend.",
        printer.printer_name,
        type(printer).__name__,
    )

    try:
        printer.print(test_zpl)
        logging.info("Test print sent successfully.")
    except Exception as error:
        logging.error("Test print failed: %s", error)


def main() -> None:
    """
    Konfiguriert das Root‑Logger‑Format, führt den Testdruck aus
    und startet den FastAPI/Uvicorn‑Server **ohne** auto‑reload.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="[%(levelname)s] %(asctime)s – %(message)s",
    )

    # Testdruck **einmalig** im gleichen Prozess
    #perform_test_print()

    # WICHTIG: reload=False, damit kein separater Child-Server aufgerufen wird
    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
