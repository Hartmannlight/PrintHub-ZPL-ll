"""
Main file for testing all preset label types.
For each preset class (or function), an instance is created,
its ZPL code is generated and printed, and a preview is attempted via the Labelary API.
"""

import logging
import os

from src.presets.cable_type_label import CableTypeLabel
from src.presets.cable_usage_label import CableUsageLabel
from src.presets.container_label import ContainerLabel
from src.presets.food_label import FoodLabel
from src.presets.id_label import IdLabel
from src.presets.lan_cable_label import LanCableLabel
from src.presets.micro_controller_label import MicroControllerLabel
from src.presets.network_device_label import NetworkDeviceLabel
from src.presets.pcb_label import PcbLabel
from src.presets.power_supply_label import PowerSupplyLabel
from src.presets.qr import QRLabel
from src.presets.storage_device_label import StorageDeviceLabel
from src.presets.text import TextLabel
from src.presets.text_header_label import TextHeaderLabel
from src.presets import image
from src.utils.id_factory import IdFactory
from src.label import Label
from src.config import COMMON_LABEL_WIDTH, COMMON_LABEL_HEIGHT
from src.utils.labelary_client import LabelaryClient

logging.basicConfig(level=logging.DEBUG, format='[%(levelname)s] %(asctime)s - %(message)s')


def display_label(zpl_code: str, width_mm: float, height_mm: float, label_name: str) -> None:
    client = LabelaryClient()
    try:
        preview = client.preview_label(zpl_code, width_mm, height_mm)
        if preview:
            preview.show(title=label_name)
        else:
            print(f"No preview available for {label_name}.")
    except Exception as e:
        print(f"Error displaying {label_name}: {e}")


def test_text_label() -> None:
    try:
        preset = TextLabel(content="Sample Text", label_width_mm=COMMON_LABEL_WIDTH, label_height_mm=COMMON_LABEL_HEIGHT)
        zpl = preset.create_zpl()
        print("TextLabel ZPL:")
        print(zpl)
        display_label(zpl, COMMON_LABEL_WIDTH, COMMON_LABEL_HEIGHT, "TextLabel")
    except Exception as e:
        print("Error testing TextLabel:", e)


def test_qr_label() -> None:
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


def test_cable_type_label() -> None:
    try:
        preset = CableTypeLabel(
            label_width_mm=COMMON_LABEL_WIDTH,
            label_height_mm=COMMON_LABEL_HEIGHT,
            from_text="Port A",
            to_text="Port B",
            length=100,
            spec_text="Cat6",
            type_abbr="NTZW"
        )
        zpl = preset.create_zpl()
        print("CableTypeLabel ZPL:")
        print(zpl)
        display_label(zpl, COMMON_LABEL_WIDTH, COMMON_LABEL_HEIGHT, "CableTypeLabel")
    except Exception as e:
        print("Error testing CableTypeLabel:", e)


def test_cable_usage_label() -> None:
    try:
        preset = CableUsageLabel(
            label_width_mm=COMMON_LABEL_WIDTH,
            label_height_mm=COMMON_LABEL_HEIGHT,
            from_text="Left Side",
            to_text="Right Side"
        )
        zpl = preset.create_zpl()
        print("CableUsageLabel ZPL:")
        print(zpl)
        display_label(zpl, COMMON_LABEL_WIDTH, COMMON_LABEL_HEIGHT, "CableUsageLabel")
    except Exception as e:
        print("Error testing CableUsageLabel:", e)


def test_food_label() -> None:
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


def test_storage_device_label() -> None:
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


def test_pcb_label() -> None:
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


def test_container_label() -> None:
    try:
        preset = ContainerLabel(
            label_width_mm=COMMON_LABEL_WIDTH,
            label_height_mm=COMMON_LABEL_HEIGHT,
            content="Gemischtes",
            position="Ebene 3 - Position 1"
        )
        zpl = preset.create_zpl()
        print("ContainerLabel ZPL:")
        print(zpl)
        display_label(zpl, COMMON_LABEL_WIDTH, COMMON_LABEL_HEIGHT, "ContainerLabel")
    except Exception as e:
        print("Error testing ContainerLabel:", e)


def test_id_label() -> None:
    try:
        # auto‑date from ID
        auto_preset = IdLabel(
            label_width_mm=COMMON_LABEL_WIDTH,
            label_height_mm=COMMON_LABEL_HEIGHT,
            id_category="NET",
            id_type="SRV",
            module_ratio=4
        )
        auto_zpl = auto_preset.create_zpl()
        print("Auto‑date IdLabel ZPL:")
        print(auto_zpl)
        display_label(auto_zpl, COMMON_LABEL_WIDTH, COMMON_LABEL_HEIGHT, "IdLabel‑AutoDate")

        # explicit date
        custom_preset = IdLabel(
            label_width_mm=COMMON_LABEL_WIDTH,
            label_height_mm=COMMON_LABEL_HEIGHT,
            id_category="BTL",
            id_type="PCB",
            module_ratio=2,
            padding_x=8,
            padding_y=8,
            print_date=True,
            date="2025-12-31",
            date_font_size=8
        )
        custom_zpl = custom_preset.create_zpl()
        print("Explicit‑date IdLabel ZPL:")
        print(custom_zpl)
        display_label(custom_zpl, COMMON_LABEL_WIDTH, COMMON_LABEL_HEIGHT, "IdLabel‑CustomDate")
    except Exception as e:
        print("Error testing IdLabel:", e)


def test_lan_cable_label() -> None:
    try:
        factory = IdFactory()
        from_id = factory.generate_code("NET", "SWCH")
        to_id = factory.generate_code("NET", "ROUT")
        connection_id = factory.generate_code("NET", "SWCH")
        preset = LanCableLabel(
            label_width_mm=COMMON_LABEL_WIDTH,
            label_height_mm=COMMON_LABEL_HEIGHT,
            from_id=from_id,
            from_location="Desk 1",
            from_ip="192.168.0.1",
            from_port="1",
            to_id=to_id,
            to_location="Desk 2",
            to_ip="192.168.0.2",
            to_port="2",
            connection_id=connection_id
        )
        zpl = preset.create_zpl()
        print("LanCableLabel ZPL:")
        print(zpl)
        display_label(zpl, COMMON_LABEL_WIDTH, COMMON_LABEL_HEIGHT, "LanCableLabel")
    except Exception as e:
        print("Error testing LanCableLabel:", e)


def test_micro_controller_label() -> None:
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
    try:
        factory = IdFactory()
        device_id = factory.generate_code("NET", "SRV")
        preset = NetworkDeviceLabel(
            label_width_mm=COMMON_LABEL_WIDTH,
            label_height_mm=COMMON_LABEL_HEIGHT,
            device_id=device_id,
            name="Switch01",
            location="Rack A",
            ip="10.0.0.1",
            hostname="switch01",
            extras="Extra info"
        )
        zpl = preset.create_zpl()
        print("NetworkDeviceLabel ZPL:")
        print(zpl)
        display_label(zpl, COMMON_LABEL_WIDTH, COMMON_LABEL_HEIGHT, "NetworkDeviceLabel")
    except Exception as e:
        print("Error testing NetworkDeviceLabel:", e)


def test_text_header_label() -> None:
    try:
        preset = TextHeaderLabel(
            label_width_mm=COMMON_LABEL_WIDTH,
            label_height_mm=COMMON_LABEL_HEIGHT,
            header_text="Wichtiger Hinweis",
            content_text="Bitte nicht berühren",
            header_font_size=32,
            content_font_size=18,
            underline_thickness=3
        )
        zpl = preset.create_zpl()
        print("TextHeaderLabel ZPL:")
        print(zpl)
        display_label(zpl, COMMON_LABEL_WIDTH, COMMON_LABEL_HEIGHT, "TextHeaderLabel")
    except Exception as e:
        print("Error testing TextHeaderLabel:", e)


def test_image_label() -> None:
    try:
        file_path = os.path.join(os.path.dirname(__file__), "img.jpg")
        label_obj: Label = image.create(file_path, COMMON_LABEL_WIDTH, COMMON_LABEL_HEIGHT)
        zpl = label_obj.zpl
        print("ImageLabel ZPL:")
        print(zpl)
        display_label(zpl, COMMON_LABEL_WIDTH, COMMON_LABEL_HEIGHT, "ImageLabel")
    except Exception as e:
        print("Error testing ImageLabel:", e)


def main() -> None:
    test_text_label()
    test_qr_label()
    test_cable_type_label()
    test_cable_usage_label()
    test_food_label()
    test_storage_device_label()
    test_pcb_label()
    test_power_supply_label()
    test_container_label()
    test_id_label()
    test_lan_cable_label()
    test_micro_controller_label()
    test_network_device_label()
    test_text_header_label()
    test_image_label()


if __name__ == "__main__":
    main()
