# src/printing.py

import abc
import logging
import subprocess
import sys

from src.config import PRINT_BACKEND, PRINT_PRINTER_NAME

logger = logging.getLogger(__name__)


class Printer(abc.ABC):
    """Abstract base class defining the printer interface for ZPL-II."""

    @abc.abstractmethod
    def print(self, zpl: str) -> None:
        """
        Send ZPL-II code to the physical printer.

        :param zpl: ZPL-II code as a string.
        """
        ...


class WindowsPrinter(Printer):
    """Windows implementation using the win32print API."""

    def __init__(self, printer_name: str) -> None:
        """
        :param printer_name: Name of the Windows printer.
        """
        self.printer_name = printer_name

    def print(self, zpl: str) -> None:
        """
        Open the printer, send raw ZPL (UTF-8) and close it again.
        """
        import win32print

        logger.debug("Opening Windows printer %r", self.printer_name)
        hPrinter = win32print.OpenPrinter(self.printer_name)
        try:
            # DOCINFO for RAW mode
            hJob = win32print.StartDocPrinter(
                hPrinter,
                1,
                ("ZPL Job", None, "RAW"),
            )
            win32print.StartPagePrinter(hPrinter)

            # Encode as UTF-8 (funktionierte bereits im main-Testdruck)
            data = zpl.encode("utf-8")
            logger.debug("Writing %d bytes to printer", len(data))
            win32print.WritePrinter(hPrinter, data)

            win32print.EndPagePrinter(hPrinter)
            win32print.EndDocPrinter(hPrinter)
            logger.info("Windows print job submitted (%d bytes)", len(data))
        except Exception:
            logger.exception("Error during Windows printing")
            raise
        finally:
            win32print.ClosePrinter(hPrinter)


class LinuxPrinter(Printer):
    """Linux implementation using the standard `lp` command."""

    def __init__(self, printer_name: str) -> None:
        """
        :param printer_name: CUPS queue name or lp destination.
        """
        self.printer_name = printer_name

    def print(self, zpl: str) -> None:
        """
        Pipe ZPL into `lp -d <printer_name>`.
        """
        logger.debug("Calling lp -d %r", self.printer_name)
        process = subprocess.Popen(
            ["lp", "-d", self.printer_name],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stdout, stderr = process.communicate(zpl.encode("utf-8"))
        if process.returncode != 0:
            err = stderr.decode(sys.getdefaultencoding(), errors="ignore")
            logger.error("Linux print error: %s", err)
            raise RuntimeError(f"Failed to print on Linux: {err}")
        logger.info("Linux lp job submitted, stdout: %r", stdout.decode(errors="ignore"))


def get_printer() -> Printer:
    """
    Factory: liest PRINT_BACKEND und liefert das passende Printer-Objekt.

    :return: Instanz von WindowsPrinter oder LinuxPrinter.
    :raises ValueError: wenn PRINT_BACKEND ungültig ist.
    """
    backend = PRINT_BACKEND.lower()
    name = PRINT_PRINTER_NAME
    logger.debug("get_printer: backend=%r, printer_name=%r", backend, name)
    if backend == "windows":
        return WindowsPrinter(name)
    if backend == "linux":
        return LinuxPrinter(name)
    raise ValueError(f"Unknown printer backend: {PRINT_BACKEND}")
