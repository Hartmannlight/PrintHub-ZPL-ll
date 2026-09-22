from zplgrid.printer_services.http import HttpPrintServiceAdapter
from zplgrid.printer_services.ports import DeliveryState


def test_v2_transmitting_is_in_progress_not_an_unknown_outcome():
    receipt = HttpPrintServiceAdapter._delivery_receipt({"id": "b1-job", "state": "transmitting"})
    assert receipt.state == DeliveryState.TRANSMITTING
    assert receipt.delivery_id == "b1-job"
