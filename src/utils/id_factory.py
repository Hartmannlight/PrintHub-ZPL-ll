import yaml
import time


class IdFactory:
    """
    Factory for generating and validating IDs based on category and type.

    IDs follow the format 'CATEGORY-TYPE-TIMESTAMP'.
    """

    def __init__(self, yaml_file="categories.yml"):
        with open(yaml_file, "r", encoding="utf-8") as file:
            self.data = yaml.safe_load(file)

    def get_categories(self):
        """Return a dictionary mapping category abbreviations to their names."""
        return {abbr: info["name"] for abbr, info in self.data.get("categories", {}).items()}

    def get_types(self, category_abbr):
        """Return a dictionary of types for the given category."""
        category = self.data.get("categories", {}).get(category_abbr, {})
        return category.get("types", {})

    def validate_category(self, category_abbr: str) -> bool:
        """Check if the given category exists."""
        return category_abbr in self.data.get("categories", {})

    def validate_type(self, category_abbr: str, type_abbr: str) -> bool:
        """Check if the given type exists in the category."""
        category = self.data.get("categories", {}).get(category_abbr, {})
        return type_abbr in category.get("types", {})

    def generate_code(self, category_abbr: str, type_abbr: str) -> str:
        """
        Generate an ID in the format 'CATEGORY-TYPE-TIMESTAMP' after validating inputs.

        :param category_abbr: Category abbreviation.
        :param type_abbr: Type abbreviation.
        :return: Generated ID string.
        :raises ValueError: If the category or type is invalid.
        """
        if not self.validate_category(category_abbr):
            raise ValueError(f"Category '{category_abbr}' does not exist.")
        if not self.validate_type(category_abbr, type_abbr):
            raise ValueError(f"Type '{type_abbr}' does not exist in category '{category_abbr}'.")
        timestamp = int(time.time() * 1000)
        return f"{category_abbr}-{type_abbr}-{timestamp}"

    def validate_code(self, code: str) -> bool:
        """
        Validate the given code.
        Expected format: 'CATEGORY-TYPE-TIMESTAMP'.

        :param code: The code string to validate.
        :return: True if valid, False otherwise.
        """
        parts = code.split("-")
        if len(parts) != 3:
            return False
        category, type_abbr, ts = parts
        if not (category.isupper() and len(category) == 3):
            return False
        if not type_abbr.isupper():
            return False
        try:
            int(ts)
        except ValueError:
            return False
        return self.validate_category(category) and self.validate_type(category, type_abbr)
