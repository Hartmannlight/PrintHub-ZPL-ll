import logging
from src.presets.lan_cable_label import LanCableLabel
from src.utils.labelary_client import LabelaryClient

logging.basicConfig(level=logging.DEBUG)


def main():
    """
    Main function to demonstrate label generation using the LanCableLabel preset.
    """
    label_width_mm = 74
    label_height_mm = 26
    source_id = "NET-ROUT-1742133760527"   # Example of a valid ID in the format CAT-TYP-TIMESTAMP
    source_location = "Server Room A"
    source_ip = "192.168.1.100"
    source_port = "8080"
    destination_id = "NET-SWCH-1742133760527"  # Example of a valid ID
    destination_location = "Switch B"
    destination_ip = "192.168.1.101"
    destination_port = "80"
    connection_id = "KAB-NTZW-174217654354527"  # Example of a valid connection ID

    try:
        # Create a LanCableLabel with the provided values.
        label = LanCableLabel(
            label_width_mm=label_width_mm,
            label_height_mm=label_height_mm,
            from_id=source_id,
            from_location=source_location,
            from_ip=source_ip,
            from_port=source_port,
            to_id=destination_id,
            to_location=destination_location,
            to_ip=destination_ip,
            to_port=destination_port,
            connection_id=connection_id
        )
        # Generate the ZPL code.
        zpl = label.create_zpl()
        print("Generated ZPL code for LanCableLabel:")
        print(zpl)

        # Generate a label preview using the Labelary API.
        client = LabelaryClient()
        preview = client.preview_label(zpl, width_mm=label_width_mm, height_mm=label_height_mm)
        if preview:
            preview.show()
        else:
            print("No preview available.")
    except Exception as e:
        print("Error while creating the label:", e)


if __name__ == "__main__":
    main()
