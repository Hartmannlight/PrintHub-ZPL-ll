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
from src.presets.device_label import DeviceLabel
from src.presets.food_label import FoodLabel
from src.presets.pcb_label import PcbLabel
from src.presets.power_supply_label import PowerSupplyLabel
from src.presets.storage_device_label import StorageDeviceLabel
from src.label import Label
from src.presets.text_header_label import TextHeaderLabel
from src.utils.labelary_client import LabelaryClient

# Configure logging to display debug messages.
logging.basicConfig(level=logging.DEBUG, format='[%(levelname)s] %(asctime)s - %(message)s')

COMMON_LABEL_WIDTH = 74
COMMON_LABEL_HEIGHT = 26


def display_label(zpl_code: str, width_mm: float, height_mm: float, label_name: str) -> None:
    """
    Request a preview image from the Labelary API using the provided ZPL code.
    If a preview is returned, it is shown; otherwise, a message is printed.
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


def test_device_label() -> None:
    """
    Test the DeviceLabel preset.
    """
    try:
        preset = DeviceLabel(
            label_width_mm=COMMON_LABEL_WIDTH,
            label_height_mm=COMMON_LABEL_HEIGHT
        )
        zpl = preset.create_zpl()
        print("DeviceLabel ZPL:")
        print(zpl)
        display_label(zpl, COMMON_LABEL_WIDTH, COMMON_LABEL_HEIGHT, "DeviceLabel")
    except Exception as e:
        print("Error testing DeviceLabel:", e)


def test_food_label() -> None:
    """
    Test the FoodLabel preset.
    """
    try:
        preset = FoodLabel(
            label_width_mm=COMMON_LABEL_WIDTH,
            label_height_mm=COMMON_LABEL_HEIGHT,
            bbf_date="2025-04-12",
            food="Example Food Info"
        )
        zpl = preset.create_zpl()
        print("FoodLabel ZPL:")
        print(zpl)
        display_label(zpl, COMMON_LABEL_WIDTH, COMMON_LABEL_HEIGHT, "FoodLabel")
    except Exception as e:
        print("Error testing FoodLabel:", e)


def test_pcb_label() -> None:
    """
    Test the PcbLabel preset.
    """
    try:
        preset = PcbLabel(
            label_width_mm=COMMON_LABEL_WIDTH,
            label_height_mm=COMMON_LABEL_HEIGHT,
            project="Projekt XYZ",
            info="Additional PCB Info"
        )
        zpl = preset.create_zpl()
        print("PcbLabel ZPL:")
        print(zpl)
        display_label(zpl, COMMON_LABEL_WIDTH, COMMON_LABEL_HEIGHT, "PcbLabel")
    except Exception as e:
        print("Error testing PcbLabel:", e)


def test_power_supply_label() -> None:
    """
    Test the PowerSupplyLabel preset.
    """
    try:
        preset = PowerSupplyLabel(
            label_width_mm=COMMON_LABEL_WIDTH,
            label_height_mm=COMMON_LABEL_HEIGHT,
            volt="5V",
            acdc="DC",
            amps="2A",
            plug="USB-C"
        )
        zpl = preset.create_zpl()
        print("PowerSupplyLabel ZPL:")
        print(zpl)
        display_label(zpl, COMMON_LABEL_WIDTH, COMMON_LABEL_HEIGHT, "PowerSupplyLabel")
    except Exception as e:
        print("Error testing PowerSupplyLabel:", e)


def test_storage_device_label() -> None:
    """
    Test the StorageDeviceLabel preset.
    """
    try:
        preset = StorageDeviceLabel(
            label_width_mm=COMMON_LABEL_WIDTH,
            label_height_mm=COMMON_LABEL_HEIGHT,
            size="500GB",
            info="SSD Storage Device"
        )
        zpl = preset.create_zpl()
        print("StorageDeviceLabel ZPL:")
        print(zpl)
        display_label(zpl, COMMON_LABEL_WIDTH, COMMON_LABEL_HEIGHT, "StorageDeviceLabel")
    except Exception as e:
        print("Error testing StorageDeviceLabel:", e)


def test_text_header_label():
    try:
        preset = TextHeaderLabel(
            header="Überschrift",
            body="Dies ist der Haupttext des Labels.",
            label_width_mm=COMMON_LABEL_WIDTH,
            label_height_mm=COMMON_LABEL_HEIGHT
        )
        zpl = preset.create_zpl()
        print("TextHeaderLabel ZPL:")
        print(zpl)
        display_label(zpl, COMMON_LABEL_WIDTH, COMMON_LABEL_HEIGHT, "TextHeaderLabel")
    except Exception as e:
        print("Error testing TextHeaderLabel:", e)


def main() -> None:
    """
    Main function to test selected preset label types.
    """
    # test_cable_type_label()
    # test_cable_usage_label()
    # test_image_label()
    # test_lan_cable_label()
    # test_micro_controller_label()
    # test_network_device_label()
    # test_qr_label()
    # test_text_label()

    # test_device_label()
    # test_food_label()
    # test_text_header_label()  # wip
    # test_pcb_label()
    # test_power_supply_label()
    # test_storage_device_label()


if __name__ == "__main__":
    main()
