# Projekt analizy giełdowej

## Profil inwestora

- **Styl:** długoterminowy (horyzont 3–5 lat)
- **Rynki:** GPW (WIG, WIG20, mWIG40), USA (S&P500, NASDAQ), Europa (DAX, CAC40), globalne ETF-y
- **Watchlista:** `watchlists/main.json`
- **Język raportów:** polski

## Cele projektu

- Codzienna analiza newsów rynkowych z ostatnich 24h
- Wykrywanie aspirujących spółek i nowych tematów inwestycyjnych
- Analiza fundamentalna spółek z watchlisty
- Śledzenie przepływów instytucjonalnych i insiderów
- Identyfikacja okazji inwestycyjnych przy korektach

## Struktura folderów

```
reports/         # codzienne raporty
reports/weekly/  # tygodniowe raporty makro
watchlists/      # listy obserwowanych spółek
memory/          # historia analiz
data/            # pobrane dane
scripts/         # skrypty Python
.claude/skills/  # zainstalowane skille
```

## Zainstalowane skille

| Skill | Opis | Wymagania |
|-------|------|-----------|
| `us-stock-analysis` | Głęboka analiza spółki | — |
| `market-news-analyst` | Newsy rynkowe | — |
| `sector-analyst` | Rotacja sektorowa | — |
| `theme-detector` | Emerging tematy inwestycyjne | — |
| `trader-memory-core` | Historia analiz | — |
| `scenario-analyzer` | Scenariusze what-if | — |
| `macro-regime-detector` | Analiza makro | `FMP_API_KEY` |
| `institutional-flow-tracker` | Smart money / przepływy instytucjonalne | `FMP_API_KEY` |
| `economic-calendar-fetcher` | Kalendarz makroekonomiczny | `FMP_API_KEY` |

Klucz API FMP jest przechowywany w pliku `.env` jako `FMP_API_KEY`.

## Zasady analizy

1. **Weryfikacja danych** — zawsze potwierdzaj informacje z minimum 2 źródeł.
2. **Brak rekomendacji** — nie wydawaj rekomendacji kupna/sprzedaży; przedstawiaj fakty i kontekst.
3. **Zapis raportów** — każdy raport zapisuj do właściwego folderu (`reports/` lub `reports/weekly/`).
4. **Pamięć analiz** — korzystaj z `trader-memory-core` do śledzenia historii analiz.
5. **Język** — wszystkie raporty i odpowiedzi pisz po polsku.
