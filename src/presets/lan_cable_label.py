# src/presets/lan_cable_label.py
import logging
from src.presets.base_label import BaseLabelPreset
from src.grids.grid_label import GridLabel
from src.grids.grid_element import GridElement
from src.elements.text_element import TextElement
from src.elements.line_element import LineElement
from src.elements.data_matrix_element import DataMatrixElement
from src.utils.conversion import mm_to_pixels
from src.config import DPI

logger = logging.getLogger(__name__)


class LanCableLabel(BaseLabelPreset):
    """
    Preset for LAN cable labels:
      - Sections 'From' and 'To' each with nested grids
      - Middle column for a divider line
      - Connection DataMatrix in last row
    """

    COL_B_WIDTH_MM: float = 20.0
    NUM_ROWS: int = 5

    def __init__(
        self,
        label_width_mm: float,
        label_height_mm: float,
        from_id: str,
        from_location: str,
        from_ip: str,
        from_port: str,
        to_id: str,
        to_location: str,
        to_ip: str,
        to_port: str,
        connection_id: str,
    ) -> None:
        """
        :param label_width_mm: Label width in mm (>0)
        :param label_height_mm: Label height in mm (>0)
        :param from_id: DataMatrix ID for 'From'
        :param from_location: Location text for 'From'
        :param from_ip: IP text for 'From'
        :param from_port: Port text for 'From'
        :param to_id: DataMatrix ID for 'To'
        :param to_location: Location text for 'To'
        :param to_ip: IP text for 'To'
        :param to_port: Port text for 'To'
        :param connection_id: DataMatrix ID for the connection
        :raises ValueError: If dimensions are not positive
        """
        logger.debug("Initializing LanCableLabel(width=%.1f, height=%.1f)", label_width_mm, label_height_mm)
        if label_width_mm <= 0 or label_height_mm <= 0:
            raise ValueError("Label dimensions must be positive")

        self.label_width_mm = label_width_mm
        self.label_height_mm = label_height_mm
        self.from_id = from_id
        self.from_location = from_location
        self.from_ip = from_ip
        self.from_port = from_port
        self.to_id = to_id
        self.to_location = to_location
        self.to_ip = to_ip
        self.to_port = to_port
        self.connection_id = connection_id

    def create_zpl(self) -> str:
        """
        Generate ZPL code for the LAN cable label.

        :return: ZPL code as a string.
        """
        logger.debug("Starting create_zpl for LanCableLabel")
        main = self._build_main_grid()
        self._populate_section(
            main.cell(0, 0),
            width_mm=(self.label_width_mm - self.COL_B_WIDTH_MM) / 2,
            id_field=self.from_id,
            location=self.from_location,
            ip=self.from_ip,
            port=self.from_port,
            header="From:",
        )
        self._add_divider(main.cell(1, 0))
        self._populate_section(
            main.cell(2, 0),
            width_mm=(self.label_width_mm - self.COL_B_WIDTH_MM) / 2,
            id_field=self.to_id,
            location=self.to_location,
            ip=self.to_ip,
            port=self.to_port,
            header="To:",
        )
        return main.create()

    def _build_main_grid(self) -> GridLabel:
        """
        Build the main 3-column grid.

        :return: Configured GridLabel.
        """
        grid = GridLabel(real_width_mm=self.label_width_mm, real_height_mm=self.label_height_mm, cols=3, rows=1, draw_grid_lines=True)
        side = (self.label_width_mm - self.COL_B_WIDTH_MM) / 2
        grid.set_cell_size(0, 0, width_mm=side, height_mm=self.label_height_mm)
        grid.set_cell_size(1, 0, width_mm=self.COL_B_WIDTH_MM, height_mm=self.label_height_mm)
        grid.set_cell_size(2, 0, width_mm=side, height_mm=self.label_height_mm)
        return grid

    def _populate_section(
        self,
        cell,
        width_mm: float,
        id_field: str,
        location: str,
        ip: str,
        port: str,
        header: str,
    ) -> None:
        """
        Populate one side (From/To) of the label.

        :param cell: The GridCell to populate.
        :param width_mm: Section width in mm.
        :param id_field: DataMatrix ID code.
        :param location: Location text.
        :param ip: IP text.
        :param port: Port text.
        :param header: Header label.
        """
        sub = GridLabel(real_width_mm=width_mm, real_height_mm=self.label_height_mm, cols=1, rows=self.NUM_ROWS, draw_grid_lines=True)
        row_h = self.label_height_mm / self.NUM_ROWS
        for r in range(self.NUM_ROWS):
            sub.set_cell_size(0, r, width_mm, row_h)

        # Header row
        head = GridLabel(real_width_mm=width_mm, real_height_mm=row_h, cols=2, rows=1, draw_grid_lines=True)
        half = width_mm / 2
        head.set_cell_size(0, 0, width_mm=half, height_mm=row_h)
        head.set_cell_size(1, 0, width_mm=half, height_mm=row_h)
        head.cell(0, 0).add_element(TextElement(text=header, center_horizontal=True, center_vertical=True))
        head.cell(1, 0).add_element(
            DataMatrixElement.from_id(id_field, center_horizontal=True, center_vertical=True)
        )
        sub.cell(0, 0).add_element(GridElement(head))

        # Location, IP, Port, Connection DataMatrix
        sub.cell(0, 1).add_element(TextElement(text=location, center_horizontal=True, center_vertical=True))
        sub.cell(0, 2).add_element(TextElement(text=ip, center_horizontal=True, center_vertical=True))
        sub.cell(0, 3).add_element(TextElement(text=port, center_horizontal=True, center_vertical=True))
        sub.cell(0, 4).add_element(
            DataMatrixElement.from_id(self.connection_id, center_horizontal=True, center_vertical=True)
        )

        cell.add_element(GridElement(sub))

    def _add_divider(self, cell) -> None:
        """
        Add a vertical divider line in the middle column.

        :param cell: The GridCell for the divider.
        """
        x = mm_to_pixels(self.COL_B_WIDTH_MM) // 2
        h = mm_to_pixels(self.label_height_mm)
        cell.add_element(LineElement(x1=x, y1=0, x2=x, y2=h, thickness=2))
