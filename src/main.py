"""
Main file for testing all preset label types.
For each preset class (or function), an instance is created,
its ZPL code is generated and printed, and a preview is attempted via the Labelary API.
"""

import logging
import os

from src.presets.cable_type_label import CableTypeLabel
from src.presets.cable_usage_label import CableUsageLabel
from src.presets.lan_cable_label import LanCableLabel
from src.presets.micro_controller_label import MicroControllerLabel
from src.presets.network_device_label import NetworkDeviceLabel
from src.presets.qr import QRLabel
from src.presets.text import TextLabel
from src.presets import image  # Module with the image preset (function "create")
from src.label import Label
from src.utils.labelary_client import LabelaryClient

# Configure logging to display debug messages.
logging.basicConfig(level=logging.DEBUG, format='[%(levelname)s] %(asctime)s - %(message)s')

# Gemeinsame Label-Dimensionen für alle Tests
COMMON_LABEL_WIDTH = 74
COMMON_LABEL_HEIGHT = 26


def display_label(zpl_code: str, width_mm: float, height_mm: float, label_name: str) -> None:
    """
    Request a preview image from the Labelary API using the provided ZPL code.
    If a preview is returned, it is shown; otherwise, a message is printed.

    :param zpl_code: The complete ZPL code for the label.
    :param width_mm: The label width in millimeters.
    :param height_mm: The label height in millimeters.
    :param label_name: A name for the label (for logging and display purposes).
    """
    client = LabelaryClient()
    try:
        preview = client.preview_label(zpl_code, width_mm, height_mm)
        if preview:
            preview.show(title=label_name)
        else:
            print(f"No preview available for {label_name}.")
    except Exception as e:
        print(f"Error displaying {label_name}: {e}")


def test_cable_type_label() -> None:
    """
    Test the CableTypeLabel preset.
    """
    try:
        preset = CableTypeLabel(
            label_width_mm=COMMON_LABEL_WIDTH,
            label_height_mm=COMMON_LABEL_HEIGHT,
            from_text="USB-C",
            to_text="USB-C",
            length=150,
            spec_text="240W\n40 Gbit/s\nDP",
            type_abbr="USB"
        )
        zpl = preset.create_zpl()
        print("CableTypeLabel ZPL:")
        print(zpl)
        display_label(zpl, COMMON_LABEL_WIDTH, COMMON_LABEL_HEIGHT, "CableTypeLabel")
    except Exception as e:
        print("Error testing CableTypeLabel:", e)


def test_cable_usage_label() -> None:
    """
    Test the CableUsageLabel preset.
    """
    try:
        preset = CableUsageLabel(
            label_width_mm=COMMON_LABEL_WIDTH,
            label_height_mm=COMMON_LABEL_HEIGHT,
            from_text="Usage From",
            to_text="Usage To"
        )
        zpl = preset.create_zpl()
        print("CableUsageLabel ZPL:")
        print(zpl)
        display_label(zpl, COMMON_LABEL_WIDTH, COMMON_LABEL_HEIGHT, "CableUsageLabel")
    except Exception as e:
        print("Error testing CableUsageLabel:", e)


def test_image_label() -> None:
    """
    Test the Image preset by creating a label from an image file.
    """
    try:
        # Provide a valid path to an image file you want to test.
        image_file = "img.jpg"
        if not os.path.exists(image_file):
            print(f"Image file '{image_file}' not found. Skipping ImageLabel test.")
            return
        label_obj: Label = image.create(
            file_path=image_file,
            label_width_mm=COMMON_LABEL_WIDTH,
            label_height_mm=COMMON_LABEL_HEIGHT,
            image_width_mm=COMMON_LABEL_WIDTH,
            image_height_mm=COMMON_LABEL_HEIGHT
        )
        zpl = label_obj.zpl
        print("ImageLabel ZPL:")
        print(zpl)
        display_label(zpl, COMMON_LABEL_WIDTH, COMMON_LABEL_HEIGHT, "ImageLabel")
    except Exception as e:
        print("Error testing ImageLabel:", e)


def test_lan_cable_label() -> None:
    """
    Test the LanCableLabel preset.
    """
    try:
        preset = LanCableLabel(
            label_width_mm=COMMON_LABEL_WIDTH,
            label_height_mm=COMMON_LABEL_HEIGHT,
            from_id="NET-ROUT-1234567890123",
            from_location="Server Room A",
            from_ip="192.168.1.100",
            from_port="8080",
            to_id="NET-SWCH-1234567890123",
            to_location="Switch B",
            to_ip="192.168.1.101",
            to_port="80",
            connection_id="KAB-NTZW-1234567890123"
        )
        zpl = preset.create_zpl()
        print("LanCableLabel ZPL:")
        print(zpl)
        display_label(zpl, COMMON_LABEL_WIDTH, COMMON_LABEL_HEIGHT, "LanCableLabel")
    except Exception as e:
        print("Error testing LanCableLabel:", e)


def test_micro_controller_label() -> None:
    """
    Test the MicroControllerLabel preset.
    """
    try:
        preset = MicroControllerLabel(
            label_width_mm=COMMON_LABEL_WIDTH,
            label_height_mm=COMMON_LABEL_HEIGHT,
            mcu_type="ATmega328P"
        )
        zpl = preset.create_zpl()
        print("MicroControllerLabel ZPL:")
        print(zpl)
        display_label(zpl, COMMON_LABEL_WIDTH, COMMON_LABEL_HEIGHT, "MicroControllerLabel")
    except Exception as e:
        print("Error testing MicroControllerLabel:", e)


def test_network_device_label() -> None:
    """
    Test the NetworkDeviceLabel preset.
    """
    try:
        preset = NetworkDeviceLabel(
            label_width_mm=COMMON_LABEL_WIDTH,
            label_height_mm=COMMON_LABEL_HEIGHT,
            device_id="NET-SRV-1234567890123",
            name="Server",
            location="Data Center",
            ip="10.0.0.1",
            hostname="server01",
            extras="Extra Info"
        )
        zpl = preset.create_zpl()
        print("NetworkDeviceLabel ZPL:")
        print(zpl)
        display_label(zpl, COMMON_LABEL_WIDTH, COMMON_LABEL_HEIGHT, "NetworkDeviceLabel")
    except Exception as e:
        print("Error testing NetworkDeviceLabel:", e)


def test_qr_label() -> None:
    """
    Test the QRLabel preset.
    """
    try:
        preset = QRLabel(
            data="https://example.com",
            qr_magnification=4,
            label_width_mm=COMMON_LABEL_WIDTH,
            label_height_mm=COMMON_LABEL_HEIGHT
        )
        zpl = preset.create_zpl()
        print("QRLabel ZPL:")
        print(zpl)
        display_label(zpl, COMMON_LABEL_WIDTH, COMMON_LABEL_HEIGHT, "QRLabel")
    except Exception as e:
        print("Error testing QRLabel:", e)


def test_text_label() -> None:
    """
    Test the TextLabel preset.
    """
    try:
        preset = TextLabel(
            content="Hello, world!",
            font="0",
            label_width_mm=COMMON_LABEL_WIDTH,
            label_height_mm=COMMON_LABEL_HEIGHT
        )
        zpl = preset.create_zpl()
        print("TextLabel ZPL:")
        print(zpl)
        display_label(zpl, COMMON_LABEL_WIDTH, COMMON_LABEL_HEIGHT, "TextLabel")
    except Exception as e:
        print("Error testing TextLabel:", e)


def main() -> None:
    """
    Main function to test all preset label types.
    All tests use the dimensions defined by COMMON_LABEL_WIDTH and COMMON_LABEL_HEIGHT.
    """
    # Uncomment any tests you want to run:
    test_cable_type_label()
    test_cable_usage_label()
    test_image_label()
    test_lan_cable_label()
    test_micro_controller_label()
    test_network_device_label()
    test_qr_label()
    test_text_label()


if __name__ == "__main__":
    main()
