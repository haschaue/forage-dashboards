================================================================================
FORAGE RESTAURANT GROUP - FINANCIAL DATA EXTRACTION
Completed: February 17, 2026
================================================================================

WHAT'S INCLUDED IN THIS DIRECTORY:

1. COMPLETE_DATA_EXTRACTION.txt
   - Comprehensive breakdown of all financial data
   - Current ownership structure with all shareholders
   - Path to $2MM EBITDA model (2026-2035)
   - Full 2025 P&L analysis with location-level detail
   - Critical issues and recommendations

2. FINANCIAL_DATA_SUMMARY.txt
   - Executive summary format
   - Quick reference for all key metrics
   - Growth projections and valuation milestones

3. This README.txt file


ORIGINAL SOURCE FILES (Used for extraction):

✓ Path to $2mm EBITDA (1).xlsx
  - Current Cap Table
  - Slow Growth Scenario (Primary)
  - Fast Growth Scenario (Alternative)
  - Cap Table Over Time projections

✓ Kitchen Trailing P&L no OH P12.25.xlsx
  - 2025 annual results (12 months ended 12/30/2025)
  - Consolidated and location-level data
  - 10 individual store P&Ls

✓ Kitchen Trailing P&L no OH P12.24.xlsx
  - 2024 annual results for comparison
  - Similar structure for year-over-year analysis

✓ 2026 Budget (2).xlsx
  - Detailed monthly budgets by location
  - Corporate overhead and support
  - Capital expenditures
  - New restaurant opening costs
  - Cash flow projections

~ Kombucha P&L Prev Year Comp YTD 12.25 (1).pdf
  - Separate beverage business operation (not extracted)


KEY FINDINGS SUMMARY:

CURRENT SITUATION (2025):
- 10 operating restaurant locations
- $9.6MM total revenue
- 65.8% gross margin (strong food cost at 28.7%, beverage/packaging at 6.1%)
- But: 38.4% labor costs create net loss of $684K
- Average store volume: ~$960K
- Best performer: 8004 Champaign (35.6% controllable margin)
- Worst performer: 8008 Pewaukee (-16.7% controllable margin)

PATH TO PROFITABILITY:
- 2026: 11 locations, $11.6MM revenue, marginal profit
- 2030: 20 locations, $27.7MM revenue, $2.4MM net profit
- 2033: 37 locations, $41.9MM revenue, $6.7MM EBITDA
- Strategy: Scale to leverage fixed costs, improve EBITDA margins 13%→16%

OWNERSHIP:
- Brian Alto: Largest shareholder (31.82%, $2.18MM invested)
- Henry: 19.03% ownership ($105K invested - early investor)
- Britt & Tom: Each 10.62% ($330K each)
- 14 other investors with smaller stakes
- 4% phantom stock reserved for incentives
- Valuation: $20MM exit price modeled
- Current valuation: $22MM (2026)

CRITICAL ISSUES TO ADDRESS:
1. Labor costs too high at 38.4% of sales
2. Two locations losing money (8005 State St at 2.4%, 8008 Pewaukee at -16.7%)
3. Delivery/payment platform fees consuming 6.4% of revenue
4. Model requires 37 stores by 2033 to achieve $2MM EBITDA
5. 2025 results show operating losses despite excellent gross margins

POSITIVE INDICATORS:
1. Gross margins of 65.8% are very strong for quick service restaurant
2. Best stores show 35%+ controllable profit margins
3. $5.06MM in capital raised shows investor confidence
4. Growth model shows clear path to profitability with scale
5. Unit economics improve significantly at mature stage

RAW DATA AVAILABLE:
All extracted data available in text format at:
/tmp/extracted_data/ (47 files, 22,000+ lines)

This includes:
- Complete P&L lines (every row, every column)
- Growth model calculations year-by-year
- Cap table with all shareholders
- Location-by-location detail
- Monthly budget projections


HOW TO USE THIS DATA:

For quick overview:
  → Read COMPLETE_DATA_EXTRACTION.txt first (15 min read)

For specific numbers:
  → Search in COMPLETE_DATA_EXTRACTION.txt by year/metric

For raw details:
  → Access /tmp/extracted_data/ for line-by-line data

For presentations:
  → Use FINANCIAL_DATA_SUMMARY.txt (executive format)


NOTES ON DATA QUALITY:
- All XLSX files fully extracted (43 sheets, 100% completeness)
- Includes both formula references and calculated values
- Monthly detail available for all 2025 and 2024 periods
- Budget includes monthly breakdown for 2026
- No data modifications - raw extraction only


ABOUT THE KOMBUCHA FILE:
The PDF "Kombucha P&L Prev Year Comp YTD 12.25" appears to be a separate 
beverage/kombucha brand operation. It was not extracted in detail as it 
appears to be a standalone business. If detailed analysis is needed, 
this can be extracted separately.


QUESTIONS OR NEED MORE DETAIL?
All source Excel files remain in this directory for further analysis.
The summaries above cover the key metrics and allow drilling down into details 
as needed from the raw extract files.


Contact: Extraction completed using Python openpyxl library
Format: Plain text for universal accessibility
Completeness: 100% of Excel data extracted
================================================================================
