# src/presets/base.py
import logging
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class BaseLabelPreset(ABC):
    """
    Abstract base class for all label presets.

    Subclasses must implement `create_zpl()` to generate the ZPL code.
    """

    @abstractmethod
    def create_zpl(self) -> str:
        """
        Generate the ZPL code for this label preset.

        :return: ZPL code as a string (including ^XA and ^XZ).
        """
        ...

    def __init_subclass__(cls, **kwargs):
        """
        Automatically log registration of preset subclasses.
        """
        super().__init_subclass__(**kwargs)
        logger.debug("Registering preset subclass: %s", cls.__name__)
