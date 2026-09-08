from zplgrid.ipp_shares import list_shares, save_share, set_share_enabled


def test_ipp_shares_start_empty_and_keep_stable_ports(tmp_path, monkeypatch):
    monkeypatch.setenv("PRINTHUB_IPP_SHARES_PATH", str(tmp_path / "ipp-shares.json"))
    assert list_shares() == []

    first = save_share(
        "shipping", printer_id="zebra-1", display_name="Shipping labels"
    )
    second = save_share(
        "office", printer_id="zebra-2", display_name="Office labels"
    )
    changed = save_share(
        "shipping", printer_id="zebra-renamed", display_name="Shipping"
    )

    assert first["port"] == changed["port"] == 8631
    assert second["port"] == 8632
    assert changed["printer_id"] == "zebra-renamed"
    assert set_share_enabled("office", False)["enabled"] is False
    assert {item["queue_id"] for item in list_shares()} == {"shipping", "office"}
