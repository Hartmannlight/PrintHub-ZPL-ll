# src/utils/label_helpers.py

import logging
from utils.id_factory import IdFactory
from elements.data_matrix_element import DataMatrixElement

logger = logging.getLogger(__name__)

def make_datamatrix(
    category: str,
    type_abbr: str,
    module_ratio: int = 3,
    center_horizontal: bool = True,
    center_vertical: bool = True
) -> DataMatrixElement:
    """
    Generate a validated DataMatrixElement with a newly created ID.

    :param category: Category abbreviation.
    :param type_abbr: Type abbreviation.
    :param module_ratio: Scale factor for the DataMatrix modules.
    :param center_horizontal: Center horizontally if True.
    :param center_vertical: Center vertically if True.
    :return: DataMatrixElement instance.
    """
    id_code = IdFactory().generate_code(category, type_abbr)
    logger.debug("make_datamatrix: generated ID=%s for %s-%s", id_code, category, type_abbr)
    return DataMatrixElement.from_id(
        id_code,
        module_ratio=module_ratio,
        center_horizontal=center_horizontal,
        center_vertical=center_vertical
    )
