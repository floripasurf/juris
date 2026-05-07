"""Tests for PKCS#11 transport and PKCS#11-based consulta."""

from __future__ import annotations

from juris.mni.pkcs11_transport import (
    SOAPResponse,
    _decode_chunked,
    _parse_http_response,
    extract_soap_body,
)


class TestParseHTTPResponse:
    """Test HTTP response parsing."""

    def test_basic_200(self) -> None:
        raw = b"HTTP/1.1 200 OK\r\nContent-Type: text/xml\r\n\r\n<soap>body</soap>"
        resp = _parse_http_response(raw)
        assert resp.status_code == 200
        assert resp.body == b"<soap>body</soap>"
        assert resp.ok

    def test_404(self) -> None:
        raw = b"HTTP/1.1 404 Not Found\r\n\r\nNot found"
        resp = _parse_http_response(raw)
        assert resp.status_code == 404
        assert not resp.ok

    def test_empty_response(self) -> None:
        resp = _parse_http_response(b"")
        assert resp.status_code == 0
        assert resp.body == b""

    def test_multipart_detected(self) -> None:
        raw = (
            b"HTTP/1.1 200 OK\r\n"
            b'Content-Type: multipart/related; boundary="abc"\r\n'
            b"\r\n"
            b"multipart body"
        )
        resp = _parse_http_response(raw)
        assert resp.is_multipart

    def test_headers_parsed(self) -> None:
        raw = b"HTTP/1.1 200 OK\r\nX-Custom: value\r\nContent-Length: 5\r\n\r\nhello"
        resp = _parse_http_response(raw)
        assert resp.headers["x-custom"] == "value"
        assert resp.headers["content-length"] == "5"


class TestDecodeChunked:
    """Test chunked transfer encoding."""

    def test_single_chunk(self) -> None:
        data = b"5\r\nhello\r\n0\r\n\r\n"
        assert _decode_chunked(data) == b"hello"

    def test_multiple_chunks(self) -> None:
        data = b"5\r\nhello\r\n6\r\n world\r\n0\r\n\r\n"
        assert _decode_chunked(data) == b"hello world"

    def test_empty(self) -> None:
        data = b"0\r\n\r\n"
        assert _decode_chunked(data) == b""


class TestExtractSOAPBody:
    """Test SOAP body extraction."""

    def test_plain_xml(self) -> None:
        resp = SOAPResponse(status_code=200, body=b"<soap:Envelope>data</soap:Envelope>")
        assert extract_soap_body(resp) == b"<soap:Envelope>data</soap:Envelope>"

    def test_multipart_mtom(self) -> None:
        body = (
            b"--boundary123\r\n"
            b"Content-Type: application/xop+xml\r\n\r\n"
            b'<?xml version="1.0"?><soap:Envelope>data</soap:Envelope>\r\n'
            b"--boundary123--"
        )
        resp = SOAPResponse(
            status_code=200,
            headers={"content-type": 'multipart/related; boundary="boundary123"'},
            body=body,
            is_multipart=True,
        )
        result = extract_soap_body(resp)
        assert b"<soap:Envelope>" in result


class TestConsultaResult:
    """Test ConsultaResult parsing."""

    def test_parse_success_xml(self) -> None:
        from juris.mni.operations.consulta_pkcs11 import _parse_response

        xml = (
            b'<?xml version="1.0"?>'
            b"<soap:Envelope xmlns:soap='http://schemas.xmlsoap.org/soap/envelope/'>"
            b"<soap:Body>"
            b"<consultarProcessoResposta>"
            b"<sucesso>true</sucesso>"
            b"<mensagem/>"
            b'<processo><dadosBasicos numero="5082351-40.2017.8.13.0024" '
            b'classeProcessual="1116">'
            b'<orgaoJulgador nomeOrgao="1a Vara Civel"/>'
            b"</dadosBasicos></processo>"
            b"</consultarProcessoResposta>"
            b"</soap:Body></soap:Envelope>"
        )
        resp = SOAPResponse(status_code=200, body=xml)
        result = _parse_response(resp, "5082351-40.2017.8.13.0024")
        assert result.sucesso
        assert result.numero == "5082351-40.2017.8.13.0024"
        assert result.classe == "1116"
        assert result.orgao_julgador == "1a Vara Civel"

    def test_parse_failure(self) -> None:
        from juris.mni.operations.consulta_pkcs11 import _parse_response

        xml = (
            b'<?xml version="1.0"?>'
            b"<soap:Envelope xmlns:soap='http://schemas.xmlsoap.org/soap/envelope/'>"
            b"<soap:Body>"
            b"<consultarProcessoResposta>"
            b"<sucesso>false</sucesso>"
            b"<mensagem>Acesso nao Autorizado</mensagem>"
            b"</consultarProcessoResposta>"
            b"</soap:Body></soap:Envelope>"
        )
        resp = SOAPResponse(status_code=200, body=xml)
        result = _parse_response(resp, "5082351-40.2017.8.13.0024")
        assert not result.sucesso
        assert "Autorizado" in result.mensagem

    def test_parse_soap_fault(self) -> None:
        from juris.mni.operations.consulta_pkcs11 import _parse_response

        xml = (
            b'<?xml version="1.0"?>'
            b"<soap:Envelope xmlns:soap='http://schemas.xmlsoap.org/soap/envelope/'>"
            b"<soap:Body>"
            b"<soap:Fault>"
            b"<faultstring>Server error</faultstring>"
            b"</soap:Fault>"
            b"</soap:Body></soap:Envelope>"
        )
        resp = SOAPResponse(status_code=200, body=xml)
        result = _parse_response(resp, "test")
        assert not result.sucesso
        assert "Server error" in result.mensagem

    def test_http_error(self) -> None:
        from juris.mni.operations.consulta_pkcs11 import _parse_response

        resp = SOAPResponse(status_code=500, body=b"Internal Server Error")
        result = _parse_response(resp, "test")
        assert not result.sucesso
        assert "500" in result.mensagem
