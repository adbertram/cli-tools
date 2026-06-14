from unittest.mock import MagicMock
import pytest
from bricklink_cli.commands.order import order_get

def test_order_get_non_nss(monkeypatch):
    mock_client = MagicMock()
    mock_client.get_order.return_value = {
        "order_id": "12345",
        "status": "PAID"
    }
    
    printed = []
    def mock_print_detail(order, table):
        printed.append(order)
        
    monkeypatch.setattr("bricklink_cli.commands.order.get_client", lambda: mock_client)
    monkeypatch.setattr("bricklink_cli.commands.order.print_detail", mock_print_detail)
    
    order_get("12345")
    
    assert len(printed) == 1
    assert printed[0]["order_id"] == "12345"
    assert printed[0]["status"] == "PAID"
    assert printed[0]["nss_alert"] is None


def test_order_get_nss(monkeypatch):
    mock_client = MagicMock()
    mock_client.get_order.return_value = {
        "order_id": "12345",
        "status": "NSS"
    }
    
    mock_browser = MagicMock()
    mock_browser.get_nss_alert.return_value = {
        "reason": "Seller shipped order but order was incomplete",
        "details": "Missing parts"
    }
    
    printed = []
    def mock_print_detail(order, table):
        printed.append(order)
        
    monkeypatch.setattr("bricklink_cli.commands.order.get_client", lambda: mock_client)
    monkeypatch.setattr("bricklink_cli.commands.order.print_detail", mock_print_detail)
    monkeypatch.setattr("bricklink_cli.commands.order.run_browser", lambda action: action(mock_browser))
    
    order_get("12345")
    
    assert len(printed) == 1
    assert printed[0]["order_id"] == "12345"
    assert printed[0]["status"] == "NSS"
    assert printed[0]["nss_alert"] is not None
    assert printed[0]["nss_alert"]["details"] == "Missing parts"
