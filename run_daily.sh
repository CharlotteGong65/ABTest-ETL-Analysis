#!/bin/bash
# Daily Matomo A/B Test Data Extraction Script
# This script runs daily to extract A/B test data and push to BigQuery

# Change to script directory
cd /home/avanish.meedimale/matomo_ABTest

# Log start time
echo "========================================" >> daily_run.log
echo "Started at: $(date)" >> daily_run.log

# Activate virtual environment and run script
source env/bin/activate
python matomoABTestDataExtract.py >> daily_run.log 2>&1

# Log completion
echo "Completed at: $(date)" >> daily_run.log
echo "========================================" >> daily_run.log

# Clean up old CSV backups older than 7 days
find /home/avanish.meedimale/matomo_ABTest -name "matomo_ab_test_data_*.csv" -mtime +7 -delete

# Exit
exit 0
