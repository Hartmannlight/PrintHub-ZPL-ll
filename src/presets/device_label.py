from src.presets.base import BaseLabelPreset
from src.label import Label
from src.elements.data_matrix_element import DataMatrixElement
from src.utils.id_factory import IdFactory

class DeviceLabel(BaseLabelPreset):
    """
    Device Label preset.

    Creates a label with a single DataMatrix element that has a module ratio of 4 and is
    offset by 2 pixels to the right and 2 pixels downward (without centering). The DataMatrix
    contains an ID generated from category 'ELE' using type 'STGS'.
    """
    def __init__(self, label_width_mm: float, label_height_mm: float) -> None:
        """
        Initialize the Device Label preset.

        :param label_width_mm: Label width in millimeters.
        :param label_height_mm: Label height in millimeters.
        """
        self.label_width_mm = label_width_mm
        self.label_height_mm = label_height_mm

    def create_zpl(self) -> str:
        """
        Generate ZPL code for the Device label.

        :return: ZPL code as a string.
        """
        id_factory = IdFactory()
        generated_id = id_factory.generate_code("ELE", "STGS")
        data_matrix = DataMatrixElement.from_id(
            generated_id,
            x=2,
            y=2,
            module_ratio=4,
            center_horizontal=False,
            center_vertical=False
        )
        return Label(data_matrix, width_mm=self.label_width_mm, height_mm=self.label_height_mm).zpl
