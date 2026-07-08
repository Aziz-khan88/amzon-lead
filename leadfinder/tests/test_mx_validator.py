from __future__ import annotations

import dns.resolver
import socket
import pytest
from unittest.mock import MagicMock, patch

from leadfinder.services.pipeline.mx_validator import (
    get_mx_hosts,
    smtp_ping,
    is_catch_all,
    check_deliverability,
)

@patch("dns.resolver.Resolver.resolve")
def test_get_mx_hosts_dns_success(mock_resolve):
    # Mock DNS answers sorted by preference
    mock_mx_1 = MagicMock()
    mock_mx_1.preference = 10
    mock_mx_1.exchange = "mail-1.success.com."
    
    mock_mx_2 = MagicMock()
    mock_mx_2.preference = 5
    mock_mx_2.exchange = "mail-2.success.com."
    
    mock_resolve.return_value = [mock_mx_1, mock_mx_2]
    
    hosts = get_mx_hosts("success.com")
    assert hosts == ["mail-2.success.com", "mail-1.success.com"]
    mock_resolve.assert_called_with("success.com", "MX")

@patch("dns.resolver.Resolver.resolve")
def test_get_mx_hosts_dns_fallback_to_a(mock_resolve):
    # First call (MX record) raises NoAnswer
    # Second call (A record) succeeds
    mock_resolve.side_effect = [
        dns.resolver.NoAnswer(),
        ["mock_a_record"]
    ]
    
    hosts = get_mx_hosts("fallback.com")
    assert hosts == ["fallback.com"]
    assert mock_resolve.call_count == 2

@patch("smtplib.SMTP")
@patch("socket.gethostbyname")
def test_smtp_ping_success(mock_gethostbyname, mock_smtp):
    mock_gethostbyname.return_value = "127.0.0.1"
    
    # Mock SMTP client instance behavior
    smtp_instance = mock_smtp.return_value.__enter__.return_value
    smtp_instance.mail.return_value = (250, b"Sender OK")
    smtp_instance.rcpt.return_value = (250, b"Recipient OK")
    
    valid, msg = smtp_ping("mail.example.com", "user@example.com")
    
    assert valid is True
    assert "Deliverable (250)" in msg
    smtp_instance.helo.assert_called_once()
    smtp_instance.mail.assert_called_once_with("verify@leadfinder.com")
    smtp_instance.rcpt.assert_called_once_with("user@example.com")

@patch("smtplib.SMTP")
@patch("socket.gethostbyname")
def test_smtp_ping_mailbox_not_exists(mock_gethostbyname, mock_smtp):
    mock_gethostbyname.return_value = "127.0.0.1"
    
    smtp_instance = mock_smtp.return_value.__enter__.return_value
    smtp_instance.mail.return_value = (250, b"Sender OK")
    smtp_instance.rcpt.return_value = (550, b"User unknown")
    
    valid, msg = smtp_ping("mail.example.com", "invalid@example.com")
    
    assert valid is False
    assert "Undeliverable (550)" in msg

@patch("smtplib.SMTP")
@patch("socket.gethostbyname")
def test_smtp_ping_connection_failed(mock_gethostbyname, mock_smtp):
    mock_gethostbyname.return_value = "127.0.0.1"
    mock_smtp.side_effect = socket.timeout("Connection timed out")
    
    valid, msg = smtp_ping("mail.example.com", "user@example.com")
    
    assert valid is None
    assert "Network timeout/connection error" in msg

@patch("leadfinder.services.pipeline.mx_validator.smtp_ping")
def test_is_catch_all(mock_smtp_ping):
    mock_smtp_ping.return_value = (True, "Deliverable")
    
    assert is_catch_all("mail.example.com", "example.com") is True
    mock_smtp_ping.assert_called_once()

@patch("leadfinder.services.pipeline.mx_validator.get_mx_hosts")
@patch("leadfinder.services.pipeline.mx_validator.is_catch_all")
@patch("leadfinder.services.pipeline.mx_validator.smtp_ping")
def test_check_deliverability_workflow_deliverable(mock_ping, mock_catch_all, mock_get_mx):
    mock_get_mx.return_value = ["mail.example.com"]
    mock_catch_all.return_value = False
    mock_ping.return_value = (True, "Deliverable")
    
    result = check_deliverability("test@example.com")
    
    assert result["syntax_valid"] is True
    assert result["status"] == "deliverable"
    assert result["mx_hosts"] == ["mail.example.com"]

@patch("leadfinder.services.pipeline.mx_validator.get_mx_hosts")
@patch("leadfinder.services.pipeline.mx_validator.is_catch_all")
def test_check_deliverability_workflow_catch_all(mock_catch_all, mock_get_mx):
    mock_get_mx.return_value = ["mail.example.com"]
    mock_catch_all.return_value = True
    
    result = check_deliverability("test-catchall@example.com")
    
    assert result["syntax_valid"] is True
    assert result["status"] == "catch_all"
