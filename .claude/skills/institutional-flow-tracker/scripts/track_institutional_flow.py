#!/usr/bin/env python3
"""
Institutional Flow Tracker — SEC EDGAR Edition

Fetches 13F-HR filings from major institutional investors via SEC EDGAR public API.
No API key required. Uses only Python standard library.

Usage:
    python3 track_institutional_flow.py
    python3 track_institutional_flow.py --tickers NVDA,MSFT,AMZN,META
    python3 track_institutional_flow.py --watchlist watchlists/main.json
    python3 track_institutional_flow.py --output-dir reports/
    python3 track_institutional_flow.py --days 90
"""

import argparse
import json
import os
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import Optional
import urllib.request
import urllib.parse
import urllib.error


# Required by SEC EDGAR fair access policy
_EDGAR_UA = "AnalizyGieldowe mpcian2006@wp.pl"

# Major institutional investors with verified CIKs (checked 2026-05)
MAJOR_INSTITUTIONS = {
    "BlackRock, Inc.": "2012383",       # CIK verified 2026-05, latest 13F: 2026-05-13
    "Vanguard Group": "102909",         # latest 13F: 2026-01-29
    "State Street Corp": "93751",       # latest 13F: 2026-02-13
    "Fidelity (FMR)": "315066",
    "JPMorgan Chase": "19617",
    "Goldman Sachs": "886982",
    "T. Rowe Price": "1113169",
    "Morgan Stanley": "895421",
    "Citadel Advisors": "1423298",
    "Millennium Management": "1273931",
    "Two Sigma Investments": "1598552",
    "Renaissance Technologies": "1037389",
    "Berkshire Hathaway": "1067983",
    "D.E. Shaw": "1168164",
}

# Company name fragments used in 13F filings (nameOfIssuer field)
TICKER_TO_EDGAR_NAME = {
    "NVDA": "NVIDIA",
    "MSFT": "MICROSOFT",
    "AMZN": "AMAZON",
    "META": "META PLATFORMS",
    "AAPL": "APPLE",
    "GOOGL": "ALPHABET",
    "GOOG": "ALPHABET",
    "TSLA": "TESLA",
    "VWO": "VANGUARD FTSE EMERGING",
    "VXUS": "VANGUARD TOTAL INTL",
    "CSPX": "ISHARES CORE S&P 500",
}

_RATE_LIMIT_DELAY = 0.15  # SEC allows ~10 req/s; use conservative 0.15s


def _fetch_json(url: str, host_header: Optional[str] = None) -> Optional[dict]:
    time.sleep(_RATE_LIMIT_DELAY)
    headers = {
        "User-Agent": _EDGAR_UA,
        "Accept": "application/json",
    }
    if host_header:
        headers["Host"] = host_header
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            return json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"  HTTP {e.code}: {url}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"  Error fetching {url}: {e}", file=sys.stderr)
        return None


def _fetch_xml_root(url: str) -> Optional[ET.Element]:
    time.sleep(_RATE_LIMIT_DELAY)
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": _EDGAR_UA,
            "Accept": "application/xml, text/xml, */*",
        })
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
        return ET.fromstring(raw.decode("utf-8", errors="replace"))
    except Exception as e:
        print(f"  Error fetching XML {url}: {e}", file=sys.stderr)
        return None


# ── EDGAR submissions API ─────────────────────────────────────────────────────

def get_institution_filings(cik: str, max_filings: int = 2) -> list[dict]:
    """Return the N most recent 13F-HR filings for an institution."""
    cik_padded = cik.zfill(10)
    url = f"https://data.sec.gov/submissions/CIK{cik_padded}.json"
    data = _fetch_json(url, host_header="data.sec.gov")
    if not data:
        return []

    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    accessions = recent.get("accessionNumber", [])
    periods = recent.get("reportDate", [])

    results = []
    for i, form in enumerate(forms):
        if form in ("13F-HR", "13F-HR/A"):
            results.append({
                "form": form,
                "filing_date": dates[i] if i < len(dates) else "",
                "period": periods[i] if i < len(periods) else "",
                "accession_no": accessions[i] if i < len(accessions) else "",
                "cik": cik,
            })
        if len(results) >= max_filings:
            break
    return results


# ── EDGAR EFTS full-text search ───────────────────────────────────────────────

def search_13f_for_company(company_fragment: str, start_date: str, end_date: str,
                            max_hits: int = 20) -> list[dict]:
    """Search EDGAR full text for 13F-HR filings mentioning a company name."""
    # EFTS requires + for spaces (not %20) to avoid HTTP 500
    q = urllib.parse.quote_plus(f'"{company_fragment}"')
    url = (
        f"https://efts.sec.gov/LATEST/search-index?"
        f"q={q}&forms=13F-HR"
        f"&dateRange=custom&startdt={start_date}&enddt={end_date}"
    )
    data = _fetch_json(url)
    if not data:
        return [], 0

    total = data.get("hits", {}).get("total", {})
    total_count = total.get("value", 0) if isinstance(total, dict) else 0

    hits = data.get("hits", {}).get("hits", [])[:max_hits]
    results = []
    for h in hits:
        src = h.get("_source", {})
        # EFTS search-index uses different field names than documented API
        display_names = src.get("display_names", [])
        entity = display_names[0].split("(CIK")[0].strip() if display_names else ""
        results.append({
            "entity": entity,
            "filing_date": src.get("file_date", ""),
            "period": src.get("period_ending", ""),
            "accession_no": src.get("adsh", ""),
        })
    return results, total_count


# ── 13F InfoTable XML parser ──────────────────────────────────────────────────

def _find_infotable_filename(cik: str, accession_no: str) -> Optional[str]:
    """Find the InfoTable XML filename inside a 13F filing."""
    cik_num = cik.lstrip("0")
    acc_nodash = accession_no.replace("-", "")
    idx_url = f"https://www.sec.gov/Archives/edgar/{cik_num}/{acc_nodash}/{accession_no}-index.json"
    data = _fetch_json(idx_url)
    if not data:
        return None
    items = data.get("directory", {}).get("item", [])
    for item in items:
        name = item.get("name", "").lower()
        if "infotable" in name and name.endswith(".xml"):
            return item["name"]
        if name.endswith(".xml") and "13f" not in name and "primary" not in name:
            return item["name"]
    # Fallback: any .xml that's not the primary
    for item in items:
        name = item.get("name", "").lower()
        if name.endswith(".xml"):
            return item["name"]
    return None


def parse_13f_holdings(cik: str, accession_no: str,
                        ticker_name_map: dict) -> list[dict]:
    """Parse 13F InfoTable XML, return holdings matching ticker_name_map."""
    filename = _find_infotable_filename(cik, accession_no)
    if not filename:
        return []

    cik_num = cik.lstrip("0")
    acc_nodash = accession_no.replace("-", "")
    url = f"https://www.sec.gov/Archives/edgar/{cik_num}/{acc_nodash}/{filename}"
    root = _fetch_xml_root(url)
    if root is None:
        return []

    # Detect namespace
    tag = root.tag
    ns = tag[: tag.index("}") + 1] if "{" in tag else ""

    holdings = []
    for node in root.iter(f"{ns}infoTable"):
        issuer = (node.findtext(f"{ns}nameOfIssuer") or "").upper().strip()
        cusip = node.findtext(f"{ns}cusip") or ""
        value_str = node.findtext(f"{ns}value") or "0"
        try:
            value = int(value_str.replace(",", "")) * 1000  # thousands → dollars
        except ValueError:
            value = 0

        shrs_node = node.find(f"{ns}shrsOrPrnAmt")
        shares = 0
        if shrs_node is not None:
            s = shrs_node.findtext(f"{ns}sshPrnamt") or "0"
            try:
                shares = int(s.replace(",", ""))
            except ValueError:
                shares = 0

        # Match against our tickers
        matched_ticker = None
        for ticker, frag in ticker_name_map.items():
            if frag.upper() in issuer:
                matched_ticker = ticker
                break

        if matched_ticker and value > 0:
            holdings.append({
                "ticker": matched_ticker,
                "issuer": issuer,
                "cusip": cusip,
                "value_usd": value,
                "shares": shares,
            })

    return holdings


# ── Load watchlist ────────────────────────────────────────────────────────────

def load_tickers_from_watchlist(path: str) -> list[str]:
    """Read USA tickers from watchlists/main.json (ignores GPW/ETF)."""
    try:
        with open(path) as f:
            data = json.load(f)
        tickers = []
        for key in ("USA", "usa"):
            tickers.extend(data.get(key, []))
        return tickers
    except Exception as e:
        print(f"Error reading watchlist {path}: {e}", file=sys.stderr)
        return []


# ── Report generation ─────────────────────────────────────────────────────────

def generate_report(
    ticker_search_results: dict,   # ticker → (hits, total_count)
    institution_filings: dict,     # name → [filing, ...]
    institution_holdings: dict,    # (name, period) → [holding, ...]
    date_range: tuple[str, str],
    output_dir: Optional[str] = None,
    output_file: Optional[str] = None,
) -> str:
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    start, end = date_range

    lines = [
        f"# Institutional Flow Report — SEC EDGAR 13F",
        f"**Wygenerowano:** {now_str}  ",
        f"**Zakres dat (filings):** {start} – {end}  ",
        f"**Źródło:** SEC EDGAR (data.sec.gov) — dane publiczne, bez klucza API",
        "",
    ]

    # 1. Recent 13F filing schedule for major institutions
    lines += [
        "## 📅 Ostatnie złożenia 13F — Duże Instytucje",
        "",
        "| Instytucja | Ostatni Filing | Okres Raportowania | Forma |",
        "|-----------|----------------|-------------------|-------|",
    ]
    for name, filings in sorted(institution_filings.items()):
        if filings:
            f = filings[0]
            lines.append(
                f"| {name} | {f['filing_date']} | {f['period']} | {f['form']} |"
            )
        else:
            lines.append(f"| {name} | n/d | n/d | — |")
    lines.append("")

    # 2. Ticker presence in recent 13F filings
    if ticker_search_results:
        lines += [
            "## 🔍 Spółki z Watchlisty w Najnowszych 13F",
            "",
            "| Ticker | Liczba Instytucji (nowe filingi) | Przykładowe Instytucje |",
            "|--------|----------------------------------|------------------------|",
        ]
        for ticker, (hits, total) in sorted(ticker_search_results.items()):
            if total == 0:
                lines.append(f"| **{ticker}** | 0 | brak danych |")
                continue
            sample_institutions = ", ".join(
                h["entity"] for h in hits[:3] if h["entity"]
            ) or "n/d"
            lines.append(
                f"| **{ticker}** | {total} | {sample_institutions} |"
            )
        lines.append("")

    # 3. Holdings detail for institutions where we parsed XML
    if institution_holdings:
        lines += [
            "## 📊 Pozycje Instytucji (z InfoTable XML)",
            "",
        ]
        for (inst_name, period), holdings in institution_holdings.items():
            if not holdings:
                continue
            lines += [
                f"### {inst_name} — okres: {period}",
                "",
                "| Ticker | Spółka | Wartość (USD) | Akcje |",
                "|--------|--------|--------------|-------|",
            ]
            for h in sorted(holdings, key=lambda x: x["value_usd"], reverse=True):
                val_str = f"${h['value_usd']:,.0f}"
                shares_str = f"{h['shares']:,}"
                lines.append(
                    f"| **{h['ticker']}** | {h['issuer']} | {val_str} | {shares_str} |"
                )
            lines.append("")

    lines += [
        "---",
        "",
        "*Dane 13F mają opóźnienie ~45 dni od końca kwartału.*  ",
        "*Nie stanowią rekomendacji inwestycyjnych.*",
    ]

    report = "\n".join(lines)

    # Save
    if output_file:
        path = output_file if output_file.endswith(".md") else f"{output_file}.md"
    else:
        fname = f"institutional_flow_{datetime.now().strftime('%Y%m%d')}.md"
        path = os.path.join(output_dir, fname) if output_dir else fname

    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"\nRaport zapisany: {path}")
    return report


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Institutional Flow Tracker — SEC EDGAR (bez API key)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Przykłady:
  python3 track_institutional_flow.py
  python3 track_institutional_flow.py --tickers NVDA,MSFT,META
  python3 track_institutional_flow.py --watchlist watchlists/main.json
  python3 track_institutional_flow.py --days 90 --output-dir reports/
  python3 track_institutional_flow.py --parse-holdings --tickers NVDA,MSFT
        """,
    )
    parser.add_argument("--tickers", type=str,
                        help="Przecinkowa lista tickerów USA (np. NVDA,MSFT,META)")
    parser.add_argument("--watchlist", type=str,
                        help="Ścieżka do pliku watchlist JSON (pobiera sekcję USA)")
    parser.add_argument("--days", type=int, default=90,
                        help="Zakres dni wstecz do szukania filingów (domyślnie: 90)")
    parser.add_argument("--parse-holdings", action="store_true",
                        help="Parsuj pełne InfoTable XML dla top 3 instytucji (wolniejsze)")
    parser.add_argument("--institutions", type=int, default=5,
                        help="Ile instytucji sprawdzić szczegółowo (domyślnie: 5)")
    parser.add_argument("--output", type=str, help="Plik wyjściowy .md")
    parser.add_argument("--output-dir", type=str, default="reports/",
                        help="Katalog wyjściowy (domyślnie: reports/)")
    args = parser.parse_args()

    # Resolve tickers
    tickers = []
    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    elif args.watchlist:
        tickers = load_tickers_from_watchlist(args.watchlist)
    # Default to common large-cap tickers if nothing specified
    if not tickers:
        tickers = ["NVDA", "MSFT", "AMZN", "META"]

    print(f"Tickery do analizy: {', '.join(tickers)}")

    # Date range
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=args.days)).strftime("%Y-%m-%d")
    print(f"Zakres dat: {start_date} – {end_date}")

    # Build ticker→name map (only tickers we have a mapping for)
    ticker_name_map = {
        t: TICKER_TO_EDGAR_NAME[t]
        for t in tickers
        if t in TICKER_TO_EDGAR_NAME
    }
    unknown = [t for t in tickers if t not in TICKER_TO_EDGAR_NAME]
    if unknown:
        print(f"Uwaga: brak mapowania nazw dla: {', '.join(unknown)} — pomijam w EFTS search")

    # ── Step 1: Check recent filings for major institutions ───────────────────
    print(f"\n[1/3] Sprawdzam ostatnie 13F filingi dla {args.institutions} instytucji...")
    institution_filings = {}
    inst_items = list(MAJOR_INSTITUTIONS.items())[: args.institutions]
    for name, cik in inst_items:
        print(f"  {name}...", end=" ", flush=True)
        filings = get_institution_filings(cik, max_filings=2)
        institution_filings[name] = filings
        if filings:
            print(f"✓ ostatni: {filings[0]['filing_date']} (okres: {filings[0]['period']})")
        else:
            print("brak danych")

    # ── Step 2: EFTS full-text search per ticker ──────────────────────────────
    print(f"\n[2/3] Szukam wzmianek o spółkach w 13F (EDGAR EFTS)...")
    ticker_search_results = {}
    for ticker, company_frag in ticker_name_map.items():
        print(f"  {ticker} ({company_frag})...", end=" ", flush=True)
        hits, total = search_13f_for_company(company_frag, start_date, end_date)
        ticker_search_results[ticker] = (hits, total)
        print(f"✓ {total} filingów")

    # ── Step 3: Optionally parse InfoTable XML for top institutions ───────────
    institution_holdings = {}
    if args.parse_holdings:
        print(f"\n[3/3] Parsuję InfoTable XML dla instytucji z filingami...")
        for name, filings in list(institution_filings.items())[:3]:
            if not filings:
                continue
            filing = filings[0]
            acc = filing["accession_no"]
            cik = filing["cik"]
            period = filing["period"]
            print(f"  {name} ({period})...", end=" ", flush=True)
            holdings = parse_13f_holdings(cik, acc, ticker_name_map)
            institution_holdings[(name, period)] = holdings
            watchlist_found = [h["ticker"] for h in holdings]
            if watchlist_found:
                print(f"✓ znalazłem: {', '.join(watchlist_found)}")
            else:
                print("✓ (brak pozycji z watchlisty)")
    else:
        print("\n[3/3] Pomijam parsowanie XML (użyj --parse-holdings aby włączyć)")

    # ── Generate report ───────────────────────────────────────────────────────
    print("\n📝 Generuję raport...")
    report = generate_report(
        ticker_search_results=ticker_search_results,
        institution_filings=institution_filings,
        institution_holdings=institution_holdings,
        date_range=(start_date, end_date),
        output_dir=args.output_dir,
        output_file=args.output,
    )

    # Quick summary to stdout
    print("\n" + "=" * 70)
    print("PODSUMOWANIE INSTITUTIONAL FLOWS")
    print("=" * 70)
    for ticker, (hits, total) in ticker_search_results.items():
        bar = "█" * min(total // 10, 20)
        print(f"  {ticker:<6} {total:>4} instytucji  {bar}")
    print()
    for name, filings in institution_filings.items():
        if filings:
            f = filings[0]
            print(f"  {name:<30} 13F złożony: {f['filing_date']} (Q: {f['period']})")


if __name__ == "__main__":
    main()
