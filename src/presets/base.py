from abc import ABC, abstractmethod


class BaseLabelPreset(ABC):
    """
    Abstract base class for label presets.
    """

    @abstractmethod
    def create_zpl(self) -> str:
        """
        Generate ZPL code for the label preset.

        :return: ZPL code as a string.
        """
        pass
