DEFAULT_LINE_PADDING = 5

class Element:
    """
    Abstract base class for label elements.
    """
    def to_zpl(self, label: "Label", offset_x: int = 0, offset_y: int = 0) -> str:
        raise NotImplementedError("Subclasses must implement the to_zpl method.")
