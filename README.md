# Matomo A/B Test Analytics Pipeline

A complete A/B testing analytics solution that extracts experiment data from Matomo, stores it in BigQuery, and performs statistical hypothesis testing to determine winning variations.

## Overview

This project provides an end-to-end pipeline for A/B test analysis:

1. **Data Extraction** - Pull A/B test assignments and conversions from Matomo
2. **Data Storage** - Automatically push to BigQuery for centralized analysis
3. **Statistical Analysis** - Hypothesis testing with Chi-square, Z-test, and Mann-Whitney U

## Features

### Data Extraction (`matomo_ab_test_extract.py`)
- ✅ Extracts A/B test experiment assignments for all visitors
- ✅ Links order numbers to specific test variations
- ✅ **Automatically pushes data to BigQuery**
- ✅ Processes multiple regions/sites (UK, US, FR, ES, IT, DE, NL, IN, AE)
- ✅ Supports date range queries
- ✅ Creates backup CSV files
- ✅ Automated daily extraction via cron

### Statistical Analysis (`ab_test_statistical_analysis.py`)
- ✅ **Chi-square test** for conversion rate significance
- ✅ **Z-test** for proportion comparison with Wilson confidence intervals
- ✅ **Mann-Whitney U test** for revenue per visitor (non-parametric)
- ✅ **Sample size calculator** for experiment planning
- ✅ Automated winner detection and recommendations
- ✅ Export results to JSON

## BigQuery Configuration

Configure these via environment variables (see `.env.example`):
- `BQ_PROJECT_ID`: Your GCP project ID
- `BQ_DATASET_ID`: BigQuery dataset name
- `BQ_TABLE_ID`: Table name (default: `Matomo_ABTest_Data`)
- `BQ_CREDENTIALS_PATH`: Path to service account JSON file

## Output Schema

The BigQuery table contains the following columns:

| Column | Type | Description |
|--------|------|-------------|
| `region` | STRING | Region code (UK, US, IT, etc.) |
| `visit_id` | INTEGER | Matomo visit ID |
| `visitor_id` | STRING | Unique visitor identifier |
| `experiment_id` | STRING | A/B test experiment ID |
| `experiment_name` | STRING | Name of the A/B test (e.g., "Bundles-Upsell-50-50") |
| `variation_id` | INTEGER | Variation ID within the experiment |
| `variation_name` | STRING | Name of the variation (e.g., "Original", "Bundles") |
| `order_number` | STRING | Order number (if visitor made a purchase) |
| `order_revenue` | FLOAT | Order revenue |
| `first_action_time` | TIMESTAMP | Timestamp of first action in visit |
| `last_action_time` | TIMESTAMP | Timestamp of last action in visit |
| `actions` | INTEGER | Number of actions in the visit |
| `converted` | INTEGER | 1 if order was placed, 0 otherwise |
| `extraction_timestamp` | TIMESTAMP | When the data was extracted |

## Setup

1. Clone the repository and create virtual environment:
```bash
python -m venv env
source env/bin/activate  # Linux/Mac
# or: env\Scripts\activate  # Windows
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Configure environment variables:
```bash
cp .env.example .env
# Edit .env with your credentials
```

## Configuration

Edit [matomoABTestDataExtract.py](matomoABTestDataExtract.py) to configure:

### Date Range
```python
end_date = datetime.now() - timedelta(days=1)
start_date = end_date - timedelta(days=7)  # Last 7 days
```

### Regions to Process
```python
# All regions:
sites_to_process = SITE_COUNTRY_MAP

# Or specific regions:
sites_to_process = {18: "IT", 3: "UK"}
```

### Testing Mode
```python
# Limit visits per day for testing:
MAX_VISITS_PER_DAY = 500

# Production mode (no limit):
MAX_VISITS_PER_DAY = None
```

## Usage

Run the script:
```bash
source env/bin/activate
python matomoABTestDataExtract.py
```

The script will:
1. Fetch A/B test experiment data for each configured site
2. Extract visitor assignments to test variations
3. Link orders to their test variations
4. **Push data to BigQuery** (WRITE_APPEND mode)
5. Save backup CSV file

## Example Output

Console output shows summary statistics:
```
📊 Orders by A/B Test Experiment & Variation:
                                     order_number  order_revenue
experiment_name      variation_name
Bundles-Upsell-50-50 Bundles                   13         528.43
                     Original                  16         705.19

✅ Successfully pushed 459 rows to BigQuery!
```

## BigQuery Queries

### Get orders by variation:
```sql
SELECT
    region,
    experiment_name,
    variation_name,
    COUNT(DISTINCT visitor_id) as unique_visitors,
    COUNTIF(order_number IS NOT NULL) as orders,
    SUM(order_revenue) as total_revenue,
    SAFE_DIVIDE(SUM(order_revenue), COUNTIF(order_number IS NOT NULL)) as avg_order_value
FROM `your-project.your_dataset.Matomo_ABTest_Data`
WHERE experiment_name IS NOT NULL
GROUP BY region, experiment_name, variation_name
ORDER BY region, experiment_name, variation_name
```

### Get conversion rate by variation:
```sql
SELECT
    experiment_name,
    variation_name,
    COUNT(*) as total_visits,
    COUNTIF(converted = 1) as conversions,
    ROUND(SAFE_DIVIDE(COUNTIF(converted = 1), COUNT(*)) * 100, 2) as conversion_rate
FROM `your-project.your_dataset.Matomo_ABTest_Data`
WHERE experiment_name IS NOT NULL
GROUP BY experiment_name, variation_name
ORDER BY experiment_name, conversion_rate DESC
```

## Logs

Check `matomoABTestDataExtract.log` for detailed execution logs.

## Regional Site Mapping

```python
SITE_COUNTRY_MAP = {
    3: "UK",
    6: "US",
    15: "FR",
    12: "ES",
    18: "IT",
    9: "DE",
    21: "NL",
    38: "IN",
    35: "AE"
}
```

## Statistical Analysis

After extracting data, run the statistical analysis:

```bash
python ab_test_statistical_analysis.py
```

### Statistical Methods Used

| Method | Purpose | When Used |
|--------|---------|-----------|
| **Chi-square test** | Test independence of conversion rates | Primary conversion comparison |
| **Z-test for proportions** | Compare two conversion rates | With confidence intervals |
| **Mann-Whitney U** | Compare revenue distributions | Non-parametric, handles outliers |
| **Wilson score interval** | Confidence interval for proportions | More accurate than normal approx. |

### Example Output

```
======================================================================
📊 EXPERIMENT: Bundles-Upsell-50-50
======================================================================

variation    visitors  conversions   revenue  conv_rate    rpv
Original         1250           38   1543.21     0.0304  1.23
Bundles          1180           52   2105.89     0.0441  1.78

──────────────────────────────────────────────────────────────────────
📈 CONVERSION RATE ANALYSIS
──────────────────────────────────────────────────────────────────────
  Original: 3.04% (38/1,250)
  95% CI: [2.22%, 4.14%]

  Bundles: 4.41% (52/1,180)
  95% CI: [3.36%, 5.74%]

  Relative Lift: +45.1%
  P-value: 0.0312
  Result: ✅ SIGNIFICANT
  Winner: 🏆 Bundles

──────────────────────────────────────────────────────────────────────
💰 REVENUE PER VISITOR ANALYSIS
──────────────────────────────────────────────────────────────────────
  Original: $1.23 (median: $0.00)
  Bundles: $1.78 (median: $0.00)

  Relative Lift: +44.7%
  P-value: 0.0287
  Result: ✅ SIGNIFICANT
  Winner: 🏆 Bundles

======================================================================
📋 RECOMMENDATION
======================================================================
✅ Both metrics significantly favor 'Bundles'.
   RECOMMENDATION: Implement Bundles.
```

### Sample Size Calculator

Plan your experiments with confidence:

```python
from ab_test_statistical_analysis import ABTestAnalyzer

analyzer = ABTestAnalyzer(alpha=0.05)
result = analyzer.sample_size_needed(
    baseline_rate=0.03,  # Current 3% conversion rate
    mde=0.10,            # Detect 10% relative improvement
    power=0.8            # 80% power
)
print(f"Need {result['per_variation']:,} visitors per variation")
# Output: Need 14,752 visitors per variation
```

### Using the Analyzer Programmatically

```python
from ab_test_statistical_analysis import ABTestAnalyzer

# Initialize
analyzer = ABTestAnalyzer(alpha=0.05)

# Load data (multiple options)
analyzer.load_from_bigquery(days_back=30)  # From BigQuery
# OR
analyzer.load_csv('matomo_ab_test_data.csv')  # From CSV

# List available experiments
print(analyzer.list_experiments())

# Run full analysis
results = analyzer.analyze(
    experiment_name='Bundles-Upsell-50-50',
    control='Original',
    treatment='Bundles'
)

# Access results programmatically
if results['conversion']['significant']:
    print(f"Winner: {results['conversion']['winner']}")
    print(f"Lift: {results['conversion']['lift_pct']}")

# Export to JSON
analyzer.export_results('my_analysis.json')
```

## Project Structure

```
Matomo_abtest/
├── matomo_ab_test_extract.py       # Data extraction (Matomo → BigQuery)
├── ab_test_statistical_analysis.py # Statistical hypothesis testing
├── run_daily.sh                    # Cron job for automation
├── requirements.txt                # Python dependencies
├── .env.example                    # Environment template
├── .gitignore                      # Security exclusions
├── README.md                       # This file
├── SETUP.md                        # Server setup guide
└── LICENSE                         # MIT License
```

## Notes

- The extraction script uses `WRITE_APPEND` mode - new data is added to the existing table
- Backup CSV files are saved with timestamps for safety
- The `extraction_timestamp` field tracks when each batch was extracted
- Progress bars show real-time extraction status
- A/B test data is stored in the `experiments` field of each Matomo visit
- Statistical tests use α=0.05 (95% confidence) by default
