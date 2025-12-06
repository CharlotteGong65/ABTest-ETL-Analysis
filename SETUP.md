# Matomo A/B Test Data Extraction - Server Setup

## ✅ Automated Daily Extraction

This script automatically extracts A/B test data from Matomo and pushes it to BigQuery **every day at 8:35 AM UTC**.

## Environment Setup

Before running, create a `.env` file with your credentials:
```bash
cp .env.example .env
# Edit .env with your actual credentials
```

## Cron Job Configuration

**Schedule:** Daily at 8:35 AM UTC
**Command:**
```bash
35 8 * * * flock -n /tmp/matomo_abtest.lock -c "/path/to/your/matomo_ABTest/run_daily.sh"
```

## What Happens Daily

1. **8:35 AM UTC** - Cron job triggers
2. Script extracts **yesterday's data** from all 9 regions:
   - UK (Site ID: 3)
   - US (Site ID: 6)
   - FR (Site ID: 15)
   - ES (Site ID: 12)
   - IT (Site ID: 18)
   - DE (Site ID: 9)
   - NL (Site ID: 21)
   - IN (Site ID: 38)
   - AE (Site ID: 35)
3. Data is automatically pushed to BigQuery table (configured in `.env`)
4. Backup CSV file is created with timestamp
5. Old CSV backups (>7 days) are automatically deleted

## File Locations

- **Main Script:** `matomoABTestDataExtract.py`
- **Daily Runner:** `run_daily.sh`
- **Environment Config:** `.env` (create from `.env.example`)
- **Logs:**
  - Main log: `matomoABTestDataExtract.log`
  - Daily run log: `daily_run.log`
- **Backup CSVs:** `matomo_ab_test_data_*.csv`

## BigQuery Output

**Table:** Configured via `BQ_PROJECT_ID`, `BQ_DATASET_ID`, `BQ_TABLE_ID` in `.env`

**Mode:** WRITE_APPEND (appends new data daily)

**Columns:**
- region, visit_id, visitor_id
- experiment_id, experiment_name
- variation_id, variation_name
- order_number, order_revenue
- first_action_time, last_action_time, actions, converted
- extraction_timestamp

## Manual Operations

### Run Immediately (Test)
```bash
cd /path/to/matomo_ABTest
./run_daily.sh
```

### Check Logs
```bash
# Check daily run log
tail -f daily_run.log

# Check detailed extraction log
tail -f matomoABTestDataExtract.log
```

### View Cron Jobs
```bash
crontab -l | grep matomo
```

### Edit Cron Job
```bash
crontab -e
```

### Check BigQuery Table
```bash
# From Python (ensure .env is configured)
source env/bin/activate
python -c "
import os
from dotenv import load_dotenv
load_dotenv()
from google.cloud import bigquery
from google.oauth2 import service_account
credentials = service_account.Credentials.from_service_account_file(os.environ['BQ_CREDENTIALS_PATH'])
client = bigquery.Client(credentials=credentials, project=os.environ['BQ_PROJECT_ID'])
table_ref = f\"{os.environ['BQ_PROJECT_ID']}.{os.environ['BQ_DATASET_ID']}.{os.environ['BQ_TABLE_ID']}\"
table = client.get_table(table_ref)
print(f'Total rows: {table.num_rows}')
"
```

## Modifying the Configuration

To change what data is extracted, edit [`matomoABTestDataExtract.py`](matomoABTestDataExtract.py):

### Change Date Range
```python
# Currently: extracts yesterday only (for daily runs)
end_date = datetime.now() - timedelta(days=1)
start_date = end_date - timedelta(days=0)

# To extract last 7 days:
start_date = end_date - timedelta(days=7)
```

### Change Regions
```python
# Currently: all regions
sites_to_process = SITE_COUNTRY_MAP

# To process specific regions only:
sites_to_process = {3: "UK", 18: "IT"}
```

### Change Visit Limit (Testing)
```python
# Currently: unlimited (production)
MAX_VISITS_PER_DAY = None

# For testing with limited data:
MAX_VISITS_PER_DAY = 500
```

## Troubleshooting

### Script Not Running
1. Check cron is enabled: `sudo systemctl status cron`
2. Check lock file: `ls -la /tmp/matomo_abtest.lock`
3. View cron logs: `grep CRON /var/log/syslog`

### No Data in BigQuery
1. Check logs for errors: `tail -100 daily_run.log`
2. Verify credentials file exists at path specified in `.env`
3. Test BigQuery connection manually

### High Memory/CPU Usage
The script processes all regions and all visits. If server resources are limited:
1. Reduce regions: Edit `sites_to_process` in the script
2. Add rate limiting or visit caps
3. Split into multiple smaller runs

## Dependencies

All dependencies are installed in the virtual environment:
- requests
- pandas
- tqdm
- google-cloud-bigquery
- google-auth
- pyarrow

To reinstall:
```bash
cd /home/avanish.meedimale/matomo_ABTest
source env/bin/activate
pip install -r requirements.txt
```

## Monitoring

### Success Indicators
- Daily run log shows "Successfully pushed X rows to BigQuery"
- BigQuery table row count increases daily
- No error messages in logs

### Check Last Run
```bash
tail -20 daily_run.log
```

### Expected Runtime
- Single region: ~1-2 minutes
- All 9 regions: ~10-20 minutes (depending on traffic)

## Support

For issues or questions:
1. Check the log files in the project directory
2. Review README.md for detailed documentation
3. Test manually with `./run_daily.sh`
