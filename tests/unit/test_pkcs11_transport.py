"""Tests for PKCS#11 transport and PKCS#11-based consulta."""

from __future__ import annotations

import pathlib

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


class TestTokenURIBuilding:
    """Test PKCS#11 URI construction from token material (no token needed)."""

    def test_percent_encode_bytes(self) -> None:
        from juris.mni.token import _percent_encode_bytes

        assert _percent_encode_bytes(b"\x79\x70") == "%79%70"
        assert _percent_encode_bytes(b"") == ""

    def test_build_pkcs11_config_uri(self) -> None:
        from juris.mni.token import TokenMaterial, build_pkcs11_config

        material = TokenMaterial(
            token_label="TOKEN CERTDATA",  # noqa: S106 — label, not a secret
            subject="CN=FULANO:00000000000",
            cpf="00000000000",
            not_valid_after="2027-06-04",
            cert_pem_path="fake-dir/cert.pem",
            chain_pem_path="fake-dir/chain.pem",
            key_id_hex="7970445a",
        )
        cfg = build_pkcs11_config(material, pin="1234")
        assert cfg.key_uri == "pkcs11:token=TOKEN%20CERTDATA;id=%79%70%44%5a;type=private"
        assert cfg.pin == "1234"
        assert cfg.cert_pem_path == "fake-dir/cert.pem"

    def test_cpf_from_subject(self) -> None:
        from juris.mni.token import _cpf_from_subject

        assert _cpf_from_subject("CN=FULANO DE TAL:07671039632,OU=x") == "07671039632"
        assert _cpf_from_subject("CN=SEM CPF") is None


class TestEngineConf:
    """Test the OpenSSL engine config writer (PIN delivery mechanism)."""

    def test_write_engine_conf_contains_pin_and_module(self) -> None:
        import os

        from juris.mni.pkcs11_transport import PKCS11Config, _write_engine_conf

        cfg = PKCS11Config(pkcs11_module="/path/to/mod.dylib", pin="secret123")
        path = _write_engine_conf(cfg)
        try:
            content = pathlib.Path(path).read_text()
            assert "engine_id = pkcs11" in content
            assert "MODULE_PATH = /path/to/mod.dylib" in content
            assert "PIN = secret123" in content
            # file must be private (contains the PIN)
            assert oct(os.stat(path).st_mode)[-3:] == "600"
        finally:
            os.unlink(path)


class TestConsultaResultRealResponse:
    """Parse the real (sanitized) TJMG consultarProcesso response."""

    def _load(self):
        from pathlib import Path

        from juris.mni.operations.consulta_pkcs11 import _parse_response
        from juris.mni.pkcs11_transport import SOAPResponse

        xml = Path("tests/fixtures/mni_responses/tjmg_consulta_real.xml").read_bytes()
        return _parse_response(SOAPResponse(status_code=200, body=xml), "50823514020178130024")

    def test_sucesso(self) -> None:
        result = self._load()
        assert result.sucesso
        assert "sucesso" in result.mensagem.lower()

    def test_dados_basicos(self) -> None:
        result = self._load()
        assert result.numero == "50823514020178130024"
        assert result.classe == "7"

    def test_movimentos_parsed(self) -> None:
        result = self._load()
        assert len(result.movimentos) == 44
        assert all("data" in m for m in result.movimentos)

    def test_partes_parsed(self) -> None:
        result = self._load()
        assert len(result.partes) >= 1
        nomes = " ".join(p["nome"] for p in result.partes)
        assert "FULANO" in nomes

    def test_documentos_excludes_party_id_docs(self) -> None:
        # incluirDocumentos=false → no process documents. Party identity
        # <documento> elements (OAB/CPF/…) must not leak in as case docs.
        result = self._load()
        assert len(result.documentos) == 0

    def test_movimentos_have_tpu_descriptions(self) -> None:
        result = self._load()
        described = [m for m in result.movimentos if m["descricao"]]
        assert described, "expected at least some movimentos enriched via TPU"
        codes = {m["codigo"]: m["descricao"] for m in described}
        assert codes.get("85") == "Prazo concedido"
        assert codes.get("60") == "Despacho"


class TestProcessoDomainBridge:
    """Convert a PKCS#11 ConsultaResult into the diff-pipeline ProcessoDomain."""

    def _result(self):
        from pathlib import Path

        from juris.mni.operations.consulta_pkcs11 import _parse_response
        from juris.mni.pkcs11_transport import SOAPResponse

        xml = Path("tests/fixtures/mni_responses/tjmg_consulta_real.xml").read_bytes()
        return _parse_response(SOAPResponse(status_code=200, body=xml), "50823514020178130024")

    def test_parse_mni_datetime(self) -> None:
        from datetime import datetime

        from juris.mni.operations.consulta_pkcs11 import _parse_mni_datetime

        assert _parse_mni_datetime("20180322155100042") == datetime(2018, 3, 22, 15, 51, 0)
        assert _parse_mni_datetime("20170619") == datetime(2017, 6, 19, 0, 0, 0)
        assert _parse_mni_datetime("") is None  # malformed → None (routed to manual review)
        assert _parse_mni_datetime("garbage") is None

    def test_to_processo_domain_movimentos(self) -> None:
        pd = self._result().to_processo_domain(tribunal_id="tjmg", numero_cnj="x")
        assert pd.numero_cnj == "50823514020178130024"
        assert pd.tribunal == "tjmg"
        assert len(pd.movimentos) == 44
        # movimentos sorted ascending; last is the most recent
        assert pd.ultimo_movimento is not None
        assert pd.ultimo_movimento.codigo_nacional == 1051

    def test_dedup_keys_unique(self) -> None:
        pd = self._result().to_processo_domain(tribunal_id="tjmg")
        keys = {(m.data_hora, m.codigo_nacional, m.id_movimento) for m in pd.movimentos}
        assert len(keys) == len(pd.movimentos)  # every movement has a distinct key

    def test_numero_fallback_when_missing(self) -> None:
        from juris.mni.operations.consulta_pkcs11 import ConsultaResult

        empty = ConsultaResult(sucesso=True, mensagem="ok")
        pd = empty.to_processo_domain(tribunal_id="tjmg", numero_cnj="0001-02.2024.8.13.0024")
        assert pd.numero_cnj == "0001-02.2024.8.13.0024"


class TestAvisosPkcs11:
    """Parse consultarAvisosPendentes responses over the mTLS path."""

    def _call(self, body_xml: bytes):
        from unittest.mock import patch

        from juris.mni.operations.intimacoes import consultar_avisos_pendentes_pkcs11
        from juris.mni.pkcs11_transport import PKCS11Config, SOAPResponse

        resp = SOAPResponse(status_code=200, body=body_xml)
        with patch("juris.mni.pkcs11_transport.pkcs11_soap_call", return_value=resp):
            return consultar_avisos_pendentes_pkcs11(
                host="pje-consulta-publica.tjmg.jus.br",
                path="/pje/intercomunicacao",
                pkcs11_config=PKCS11Config(),
                id_consultante="00000000000",
                senha_consultante="x",
            )

    def test_parses_pending_avisos(self) -> None:
        xml = (
            b"<soap:Envelope xmlns:soap='http://schemas.xmlsoap.org/soap/envelope/'>"
            b"<soap:Body><ns:consultarAvisosPendentesResposta xmlns:ns='x'>"
            b"<sucesso>true</sucesso><mensagem>ok</mensagem>"
            b"<aviso idAviso='A1' tipoComunicacao='intimacao' "
            b"numeroProcesso='5000001-11.2025.8.13.0024' orgaoJulgador='1a Vara'/>"
            b"<aviso idAviso='A2' tipoComunicacao='citacao' "
            b"numeroProcesso='5000002-22.2025.8.13.0024'/>"
            b"</ns:consultarAvisosPendentesResposta></soap:Body></soap:Envelope>"
        )
        result = self._call(xml)
        assert result.sucesso
        assert len(result.avisos) == 2
        assert result.avisos[0].numero_processo == "5000001-11.2025.8.13.0024"
        assert result.avisos[0].tipo_comunicacao == "intimacao"
        assert result.avisos[1].id_aviso == "A2"

    def test_empty_avisos_success(self) -> None:
        xml = (
            b"<soap:Envelope xmlns:soap='http://schemas.xmlsoap.org/soap/envelope/'>"
            b"<soap:Body><resposta><sucesso>true</sucesso>"
            b"<mensagem>sem avisos</mensagem></resposta></soap:Body></soap:Envelope>"
        )
        result = self._call(xml)
        assert result.sucesso
        assert result.avisos == []

    def test_failure_reported(self) -> None:
        xml = (
            b"<soap:Envelope xmlns:soap='http://schemas.xmlsoap.org/soap/envelope/'>"
            b"<soap:Body><resposta><sucesso>false</sucesso>"
            b"<mensagem>Erro de login</mensagem></resposta></soap:Body></soap:Envelope>"
        )
        result = self._call(xml)
        assert not result.sucesso
        assert "login" in result.mensagem.lower()


def test_parse_mni_datetime_returns_none_on_malformed_not_datetime_min() -> None:
    """A malformed/missing MNI timestamp must yield None (routed to manual review),
    never datetime.min — which crashed the prazo engine and silently dropped the
    whole process's deadlines (pkcs11 path, the primary A3 production path)."""
    from juris.mni.operations.consulta_pkcs11 import _parse_mni_datetime

    assert _parse_mni_datetime("") is None
    assert _parse_mni_datetime("garbage") is None
    assert _parse_mni_datetime("00000000") is None  # ValueError → None
    # a valid timestamp still parses
    assert _parse_mni_datetime("20260701093000") is not None
