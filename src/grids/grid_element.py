import logging
import re
from src.elements.elements import Element

logger = logging.getLogger(__name__)


class GridElement(Element):
    """
    Wraps a GridLabel so that it can be used as an element in another grid.
    """

    def __init__(self, grid_label: "GridLabel") -> None:
        """
        Initialize a GridElement.

        :param grid_label: A GridLabel instance.
        """
        self.grid_label = grid_label

    def to_zpl(self, label: "Label", offset_x: int = 0, offset_y: int = 0) -> str:
        """
        Convert the nested grid to its corresponding ZPL code and adjust offsets.

        :param label: The parent label.
        :param offset_x: Horizontal offset.
        :param offset_y: Vertical offset.
        :return: Adjusted ZPL code as a string.
        """
        full_zpl = self.grid_label.create()
        lines = full_zpl.splitlines()
        if lines and lines[0].strip() == "^XA":
            lines = lines[1:]
        if lines and lines[-1].strip() == "^XZ":
            lines = lines[:-1]
        nested_zpl = "\n".join(lines)

        def adjust_fo(match):
            x = int(match.group(1))
            y = int(match.group(2))
            new_x = x + offset_x
            new_y = y + offset_y
            return f"^FO{new_x},{new_y}"

        adjusted_zpl = re.sub(r'\^FO(\d+),(\d+)', adjust_fo, nested_zpl)
        logger.debug("Adjusted GridElement ZPL: %s", adjusted_zpl)
        return adjusted_zpl
