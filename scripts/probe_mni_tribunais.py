"""Probe MNI WSDL endpoints across multiple tribunals.

Tests which tribunals have publicly accessible WSDLs and which
support password-only auth (no mTLS required).

Usage:
    uv run python scripts/probe_mni_tribunais.py
"""

from __future__ import annotations

import sys
from datetime import datetime

import requests

# All known PJe MNI endpoints — expand as needed
ENDPOINTS = {
    "TRT1 (RJ)": "https://pje.trt1.jus.br/pje/intercomunicacao?wsdl",
    "TRT2 (SP)": "https://pje.trt2.jus.br/pje/intercomunicacao?wsdl",
    "TRT3 (MG)": "https://pje.trt3.jus.br/pje/intercomunicacao?wsdl",
    "TRT4 (RS)": "https://pje.trt4.jus.br/pje/intercomunicacao?wsdl",
    "TRT5 (BA)": "https://pje.trt5.jus.br/pje/intercomunicacao?wsdl",
    "TRT6 (PE)": "https://pje.trt6.jus.br/pje/intercomunicacao?wsdl",
    "TRT7 (CE)": "https://pje.trt7.jus.br/pje/intercomunicacao?wsdl",
    "TRT8 (PA)": "https://pje.trt8.jus.br/pje/intercomunicacao?wsdl",
    "TRT9 (PR)": "https://pje.trt9.jus.br/pje/intercomunicacao?wsdl",
    "TRT10 (DF)": "https://pje.trt10.jus.br/pje/intercomunicacao?wsdl",
    "TRT11 (AM)": "https://pje.trt11.jus.br/pje/intercomunicacao?wsdl",
    "TRT12 (SC)": "https://pje.trt12.jus.br/pje/intercomunicacao?wsdl",
    "TRT13 (PB)": "https://pje.trt13.jus.br/pje/intercomunicacao?wsdl",
    "TRT14 (RO)": "https://pje.trt14.jus.br/pje/intercomunicacao?wsdl",
    "TRT15 (Campinas)": "https://pje.trt15.jus.br/pje/intercomunicacao?wsdl",
    "TRT18 (GO)": "https://pje.trt18.jus.br/pje/intercomunicacao?wsdl",
    "TRT19 (AL)": "https://pje.trt19.jus.br/pje/intercomunicacao?wsdl",
    "TRT20 (SE)": "https://pje.trt20.jus.br/pje/intercomunicacao?wsdl",
    "TRT21 (RN)": "https://pje.trt21.jus.br/pje/intercomunicacao?wsdl",
    "TRT22 (PI)": "https://pje.trt22.jus.br/pje/intercomunicacao?wsdl",
    "TRT23 (MT)": "https://pje.trt23.jus.br/pje/intercomunicacao?wsdl",
    "TRT24 (MS)": "https://pje.trt24.jus.br/pje/intercomunicacao?wsdl",
    "TST": "https://pje.tst.jus.br/pje/intercomunicacao?wsdl",
    "TRF1": "https://pje.trf1.jus.br/pje/intercomunicacao?wsdl",
    "TRF2": "https://pje.trf2.jus.br/pje/intercomunicacao?wsdl",
    "TRF3": "https://pje.trf3.jus.br/pje/intercomunicacao?wsdl",
    "TRF4": "https://pje.trf4.jus.br/pje/intercomunicacao?wsdl",
    "TRF5": "https://pje.trf5.jus.br/pje/intercomunicacao?wsdl",
    "TRF6 (MG)": "https://pje.trf6.jus.br/pje/intercomunicacao?wsdl",
    "TJDF": "https://pje.tjdft.jus.br/pje/intercomunicacao?wsdl",
    "TJRJ": "https://pje.tjrj.jus.br/pje/intercomunicacao?wsdl",
    "TJMG": "https://pje.tjmg.jus.br/pje/intercomunicacao?wsdl",
    "TJSP": "https://pje.tjsp.jus.br/pje/intercomunicacao?wsdl",
    "TJBA": "https://pje.tjba.jus.br/pje/intercomunicacao?wsdl",
    "TJPE": "https://pje.tjpe.jus.br/pje/intercomunicacao?wsdl",
    "TJCE": "https://pje.tjce.jus.br/pje/intercomunicacao?wsdl",
    "TJAL": "https://pje.tjal.jus.br/pje/intercomunicacao?wsdl",
    "TJMA": "https://pje.tjma.jus.br/pje/intercomunicacao?wsdl",
    "TJPI": "https://pje.tjpi.jus.br/pje/intercomunicacao?wsdl",
    "TJPA": "https://pje.tjpa.jus.br/pje/intercomunicacao?wsdl",
    "TJRN": "https://pje.tjrn.jus.br/pje/intercomunicacao?wsdl",
    "TJPB": "https://pje.tjpb.jus.br/pje/intercomunicacao?wsdl",
    "TJAM": "https://pje.tjam.jus.br/pje/intercomunicacao?wsdl",
    "TJMT": "https://pje.tjmt.jus.br/pje/intercomunicacao?wsdl",
    "TJMS": "https://pje.tjms.jus.br/pje/intercomunicacao?wsdl",
    "TJGO": "https://pje.tjgo.jus.br/pje/intercomunicacao?wsdl",
    "TJTO": "https://pje.tjto.jus.br/pje/intercomunicacao?wsdl",
    "TJAC": "https://pje.tjac.jus.br/pje/intercomunicacao?wsdl",
    "TJRO": "https://pje.tjro.jus.br/pje/intercomunicacao?wsdl",
    "TJAP": "https://pje.tjap.jus.br/pje/intercomunicacao?wsdl",
    "TJRR": "https://pje.tjrr.jus.br/pje/intercomunicacao?wsdl",
    "TJSC": "https://pje.tjsc.jus.br/pje/intercomunicacao?wsdl",
    "TJRS": "https://pje.tjrs.jus.br/pje/intercomunicacao?wsdl",
    "TJPR": "https://pje.tjpr.jus.br/pje/intercomunicacao?wsdl",
    "TJES": "https://pje.tjes.jus.br/pje/intercomunicacao?wsdl",
    "TJSE": "https://pje.tjse.jus.br/pje/intercomunicacao?wsdl",
}


def probe_wsdl(name: str, url: str) -> dict:
    """Probe a single WSDL endpoint."""
    result = {"name": name, "url": url, "status": "FAIL", "code": 0, "is_wsdl": False, "error": ""}
    try:
        resp = requests.get(url, timeout=10, allow_redirects=True)
        result["code"] = resp.status_code
        content = resp.text[:500]
        is_wsdl = any(marker in content for marker in ["wsdl:", "definitions", "?xml", "<wsdl"])
        result["is_wsdl"] = is_wsdl
        if resp.status_code == 200 and is_wsdl:
            result["status"] = "OK"
        elif resp.status_code == 200:
            result["status"] = "HTML"  # Returns HTML, not WSDL
        else:
            result["status"] = f"HTTP{resp.status_code}"
    except requests.exceptions.SSLError as e:
        result["status"] = "SSL_ERR"
        result["error"] = str(e)[:80]
    except requests.exceptions.ConnectionError:
        result["status"] = "CONN_ERR"
    except requests.exceptions.Timeout:
        result["status"] = "TIMEOUT"
    except Exception as e:
        result["status"] = "ERROR"
        result["error"] = str(e)[:80]
    return result


def main() -> None:
    print(f"MNI WSDL Probe — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"Testing {len(ENDPOINTS)} endpoints...\n")
    print(f"{'Tribunal':<20} {'Status':<10} {'HTTP':<6} {'WSDL':<6} {'Notes'}")
    print("-" * 80)

    ok_endpoints = []
    for name, url in sorted(ENDPOINTS.items()):
        result = probe_wsdl(name, url)
        wsdl_mark = "YES" if result["is_wsdl"] else "no"
        notes = result["error"] if result["error"] else ""
        print(f"{name:<20} {result['status']:<10} {result['code']:<6} {wsdl_mark:<6} {notes}")

        if result["status"] == "OK":
            ok_endpoints.append(result)

    print(f"\n{'='*80}")
    print(f"Results: {len(ok_endpoints)}/{len(ENDPOINTS)} endpoints returned valid WSDL")

    if ok_endpoints:
        print("\nWorking endpoints:")
        for ep in ok_endpoints:
            print(f"  - {ep['name']}: {ep['url']}")

        # Try zeep on first working endpoint
        print(f"\nAttempting zeep client on: {ok_endpoints[0]['name']}...")
        try:
            from zeep import Client, Settings

            settings = Settings(strict=False, xml_huge_tree=True)
            client = Client(wsdl=ok_endpoints[0]["url"], settings=settings)
            ops = [op for op in client.service._operations]
            print(f"  Operations available: {', '.join(ops)}")
        except Exception as e:
            print(f"  Zeep error: {e}")


if __name__ == "__main__":
    main()
