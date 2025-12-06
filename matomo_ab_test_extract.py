import requests
import json
import pandas as pd
from datetime import datetime, timedelta
from tqdm import tqdm
import logging
import os
from google.cloud import bigquery
from google.oauth2 import service_account
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Configure logging
log_file_path = "matomoABTestDataExtract.log"
logging.basicConfig(
    filename=log_file_path,
    level=logging.INFO,
    format="%(asctime)s - %(message)s"
)

# --- Matomo API Config ---
MATOMO_URL = os.environ.get('MATOMO_URL', 'https://your-matomo-instance.com/index.php')
AUTH_TOKEN = os.environ.get('MATOMO_AUTH_TOKEN')

if not AUTH_TOKEN:
    raise ValueError("MATOMO_AUTH_TOKEN environment variable is required")

# Regional site mapping
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

# --- BigQuery Config ---
BQ_CREDENTIALS_PATH = os.environ.get('BQ_CREDENTIALS_PATH')
BQ_PROJECT_ID = os.environ.get('BQ_PROJECT_ID', 'your-gcp-project')
BQ_DATASET_ID = os.environ.get('BQ_DATASET_ID', 'your_dataset')
BQ_TABLE_ID = os.environ.get('BQ_TABLE_ID', 'Matomo_ABTest_Data')

if not BQ_CREDENTIALS_PATH:
    raise ValueError("BQ_CREDENTIALS_PATH environment variable is required")

def get_all_experiments(site_id):
    """
    Fetches all A/B test experiments for a given site.
    Returns list of experiments with their IDs, names, and variations.
    """
    params = {
        "module": "API",
        "method": "AbTesting.getExperiments",
        "idSite": site_id,
        "format": "JSON",
        "token_auth": AUTH_TOKEN,
    }
    try:
        response = requests.get(MATOMO_URL, params=params)
        response.raise_for_status()
        experiments = response.json()
        return experiments
    except (requests.exceptions.RequestException, json.JSONDecodeError) as e:
        logging.error(f"Error fetching experiments for site {site_id}: {e}")
        return []

def get_experiment_details(site_id, experiment_name, date_string, period="day"):
    """
    Fetches detailed metrics for a specific A/B test experiment.
    Returns performance data for each variation.
    """
    params = {
        "module": "API",
        "method": "AbTesting.getMetricsOverview",
        "idSite": site_id,
        "period": period,
        "date": date_string,
        "experimentName": experiment_name,
        "format": "JSON",
        "token_auth": AUTH_TOKEN,
    }
    try:
        response = requests.get(MATOMO_URL, params=params)
        response.raise_for_status()
        return response.json()
    except (requests.exceptions.RequestException, json.JSONDecodeError) as e:
        logging.error(f"Error fetching experiment details for {experiment_name}: {e}")
        return None

def get_visits_with_ab_test_data(date_string, site_id, region, max_visits=500):
    """
    Fetches visit details including custom dimensions/variables that contain A/B test assignments.
    This retrieves which variation each visitor was assigned to.
    max_visits: limit total visits to fetch (for testing)
    """
    all_visits_data = []
    limit = 100
    offset = 0

    # First get total visits
    params_total = {
        "module": "API",
        "method": "VisitsSummary.get",
        "idSite": site_id,
        "period": "day",
        "date": date_string,
        "format": "JSON",
        "token_auth": AUTH_TOKEN,
    }

    try:
        response = requests.get(MATOMO_URL, params=params_total)
        response.raise_for_status()
        data = response.json()
        total_visits = data.get("nb_visits", 0)
    except:
        total_visits = 0

    if total_visits == 0:
        logging.info(f"No visits for {region} on {date_string}")
        return []

    # Limit total visits for testing
    total_visits = min(total_visits, max_visits)
    logging.info(f"Fetching {total_visits} visits for {region} on {date_string}")

    with tqdm(total=total_visits, desc=f"Fetching {region} AB test data") as pbar:
        while offset < total_visits:
            params = {
                "module": "API",
                "method": "Live.getLastVisitsDetails",
                "idSite": site_id,
                "period": "day",
                "date": date_string,
                "format": "JSON",
                "token_auth": AUTH_TOKEN,
                "filter_limit": limit,
                "filter_offset": offset,
                "showColumns": "idVisit,visitorId,experiments,actionDetails,goalConversions,firstActionTimestamp,lastActionTimestamp,actions"
            }

            try:
                response = requests.get(MATOMO_URL, params=params)
                response.raise_for_status()
                page_data = response.json()

                if not page_data or (isinstance(page_data, dict) and page_data.get('result') == 'error'):
                    break

                all_visits_data.extend(page_data)
                pbar.update(len(page_data))
                offset += limit

            except (requests.exceptions.RequestException, json.JSONDecodeError) as e:
                logging.error(f"Error fetching visits: {e}")
                break

    return all_visits_data

def extract_ab_test_info_from_visits(visits_data, region):
    """
    Processes visit data to extract A/B test variation assignments and order information.
    A/B test data is typically stored in custom variables or custom dimensions.
    """
    records = []

    for visit in visits_data:
        visit_id = visit.get('idVisit')
        visitor_id = visit.get('visitorId')

        # Extract A/B test info from the 'experiments' field
        ab_test_variation = None
        ab_test_name = None
        ab_test_id = None
        variation_id = None

        # Check the experiments field (this is where Matomo stores A/B test assignments)
        experiments = visit.get('experiments', [])
        if experiments and isinstance(experiments, list) and len(experiments) > 0:
            # Get the first experiment (visitors can be in multiple experiments)
            experiment = experiments[0]
            ab_test_id = experiment.get('idexperiment')
            ab_test_name = experiment.get('name')

            variation = experiment.get('variation', {})
            if variation:
                variation_id = variation.get('idvariation')
                ab_test_variation = variation.get('name')

        # Extract order information from goal conversions or action details
        order_number = None
        order_revenue = None

        # Check goal conversions for ecommerce orders
        goal_conversions = visit.get('goalConversions', [])
        if isinstance(goal_conversions, list):
            for conversion in goal_conversions:
                if isinstance(conversion, dict):
                    if conversion.get('goalName') == 'Ecommerce Order' or conversion.get('idGoal') == 0:
                        order_revenue = conversion.get('revenue', 0)
                        # Order ID might be in revenue details or custom tracking

        # Check action details for order information
        action_details = visit.get('actionDetails', [])
        for action in action_details:
            # Look for ecommerce order actions
            if action.get('type') == 'ecommerceOrder':
                order_number = action.get('orderId')
                order_revenue = action.get('revenue', 0)

            # Also check event actions for order tracking
            event_action = action.get('eventAction', '')
            event_name = action.get('eventName', '')

            if 'order' in event_action.lower() or 'order' in event_name.lower():
                # Try to extract order number from event name/value
                if event_name and event_name.isdigit():
                    order_number = event_name

        # Create record if we have relevant data
        if ab_test_variation or order_number:
            records.append({
                'region': region,
                'visit_id': visit_id,
                'visitor_id': visitor_id,
                'experiment_id': ab_test_id,
                'experiment_name': ab_test_name,
                'variation_id': variation_id,
                'variation_name': ab_test_variation,
                'order_number': order_number,
                'order_revenue': order_revenue,
                'first_action_time': visit.get('firstActionTimestamp'),
                'last_action_time': visit.get('lastActionTimestamp'),
                'actions': visit.get('actions'),
                'converted': 1 if order_number else 0
            })

    return pd.DataFrame(records) if records else None

def get_segment_for_experiment(experiment_name, variation_name):
    """
    Creates a Matomo segment to filter data by specific A/B test variation.
    This can be used to get orders for a specific variation.
    """
    # Matomo segments use custom variable or dimension matching
    # Format: customVariableName1==experiment_name;customVariableValue1==variation_name
    segment = f"dimension1=={variation_name}"  # Adjust based on your custom dimension setup
    return segment

def get_ecommerce_orders_by_segment(site_id, date_string, segment, period="day"):
    """
    Fetches ecommerce orders filtered by a segment (e.g., specific A/B test variation).
    """
    params = {
        "module": "API",
        "method": "Goals.get",
        "idSite": site_id,
        "period": period,
        "date": date_string,
        "idGoal": "ecommerceOrder",
        "segment": segment,
        "format": "JSON",
        "token_auth": AUTH_TOKEN,
    }

    try:
        response = requests.get(MATOMO_URL, params=params)
        response.raise_for_status()
        return response.json()
    except (requests.exceptions.RequestException, json.JSONDecodeError) as e:
        logging.error(f"Error fetching ecommerce orders: {e}")
        return None

def push_to_bigquery(df):
    """
    Pushes the dataframe to BigQuery.
    Uses WRITE_APPEND to add new data to existing table.
    """
    if df is None or df.empty:
        logging.info("DataFrame is empty. Nothing to upload to BigQuery.")
        return False

    logging.info(f"\n🚀 Pushing {len(df)} records to BigQuery...")
    logging.info(f"   Table: {BQ_PROJECT_ID}.{BQ_DATASET_ID}.{BQ_TABLE_ID}")

    try:
        # Load credentials
        credentials = service_account.Credentials.from_service_account_file(BQ_CREDENTIALS_PATH)
        client = bigquery.Client(credentials=credentials, project=BQ_PROJECT_ID)
        logging.info("✅ Authentication to Google Cloud successful.")

        # Prepare table reference
        table_ref = f"{BQ_PROJECT_ID}.{BQ_DATASET_ID}.{BQ_TABLE_ID}"

        # Configure job
        job_config = bigquery.LoadJobConfig(
            write_disposition="WRITE_APPEND",  # Append to existing table
            autodetect=True,  # Auto-detect schema
        )

        # Prepare dataframe
        df_bq = df.copy()

        # Convert timestamp columns to datetime (remove timezone if any)
        if 'first_action_time' in df_bq.columns:
            df_bq['first_action_time'] = pd.to_datetime(df_bq['first_action_time'], unit='s', errors='coerce')
        if 'last_action_time' in df_bq.columns:
            df_bq['last_action_time'] = pd.to_datetime(df_bq['last_action_time'], unit='s', errors='coerce')

        # Add extraction timestamp
        df_bq['extraction_timestamp'] = datetime.now()

        # Load to BigQuery
        job = client.load_table_from_dataframe(df_bq, table_ref, job_config=job_config)
        job.result()  # Wait for completion

        logging.info(f"✅ Successfully loaded {job.output_rows} rows into {BQ_DATASET_ID}.{BQ_TABLE_ID}")
        print(f"✅ Successfully pushed {job.output_rows} rows to BigQuery!")
        return True

    except Exception as e:
        logging.error(f"❌ Failed to load data into BigQuery. Error: {e}")
        print(f"❌ BigQuery upload failed: {e}")
        return False

# ------------------------------------------------------------------------------------
# Main Execution
# ------------------------------------------------------------------------------------
if __name__ == "__main__":
    # CONFIGURATION
    # Extract data for yesterday (daily run)
    end_date = datetime.now() - timedelta(days=1)
    start_date = end_date - timedelta(days=0)  # Just yesterday for daily runs

    # Production mode: no visit limit
    MAX_VISITS_PER_DAY = None  # None = unlimited (production)

    all_ab_test_data = []

    logging.info(f"🚀 Starting A/B test data extraction from {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")

    date_range = pd.date_range(start_date, end_date)

    # Process all regions in production
    sites_to_process = SITE_COUNTRY_MAP  # All regions for production
    # sites_to_process = {18: "IT"}  # Use this for testing specific regions

    # First, get all experiments for each site
    for site_id, region in sites_to_process.items():
        logging.info(f"\n🧪 Fetching A/B test experiments for {region} (Site ID: {site_id})")

        experiments = get_all_experiments(site_id)

        if experiments:
            logging.info(f"Found {len(experiments)} experiments for {region}")
            for exp in experiments:
                if isinstance(exp, dict):
                    logging.info(f"  - {exp.get('name', 'Unknown')}: {exp.get('status', 'N/A')}")
                else:
                    logging.info(f"  - {exp}")

        # Fetch visit data with A/B test assignments
        for current_date in date_range:
            date_str = current_date.strftime('%Y-%m-%d')

            max_visits = MAX_VISITS_PER_DAY if MAX_VISITS_PER_DAY else 999999
            visits_data = get_visits_with_ab_test_data(date_str, site_id, region, max_visits=max_visits)

            if visits_data:
                df = extract_ab_test_info_from_visits(visits_data, region)
                if df is not None and not df.empty:
                    all_ab_test_data.append(df)
                    logging.info(f"✅ Extracted {len(df)} records with A/B test data for {region} on {date_str}")

    # Combine all data
    if all_ab_test_data:
        final_df = pd.concat(all_ab_test_data, ignore_index=True)

        logging.info("\n\n✅✅✅ A/B Test Data Extraction Complete! ✅✅✅")
        logging.info(f"Total records: {len(final_df)}")
        logging.info(f"Total unique visitors: {final_df['visitor_id'].nunique()}")
        logging.info(f"Total orders tracked: {final_df[final_df['order_number'].notna()]['order_number'].nunique()}")

        # Summary by experiment and variation
        if 'variation_name' in final_df.columns:
            logging.info("\n📊 Orders by A/B Test Experiment & Variation:")
            variation_summary = final_df[final_df['order_number'].notna()].groupby(['experiment_name', 'variation_name']).agg({
                'order_number': 'count',
                'order_revenue': 'sum'
            })
            logging.info(variation_summary)
            print("\n📊 Orders by A/B Test Experiment & Variation:")
            print(variation_summary)

        # Display sample data
        print("\n📋 Sample data:")
        print(final_df[['region', 'visitor_id', 'experiment_name', 'variation_name', 'order_number', 'order_revenue']].head(10))

        # Push to BigQuery
        success = push_to_bigquery(final_df)

        # Also save to CSV as backup
        if success:
            output_file = f'matomo_ab_test_data_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
            final_df.to_csv(output_file, index=False)
            logging.info(f"\n💾 Backup CSV saved to: {output_file}")
            print(f"💾 Backup CSV saved to: {output_file}")

    else:
        logging.info("❌ No A/B test data found for the specified period.")
        print("No A/B test data found. Please check:")
        print("1. A/B tests are configured in Matomo")
        print("2. Custom variables/dimensions are set up to track experiment variations")
        print("3. The date range has active experiments")
