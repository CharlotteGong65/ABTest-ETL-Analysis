"""
A/B Test Statistical Analysis

This module provides statistical hypothesis testing for A/B test experiments.
It can analyze data from CSV files or directly from BigQuery.

Statistical Methods:
- Chi-square test for conversion rate differences
- Z-test for proportion comparison with confidence intervals
- Mann-Whitney U test for revenue per visitor (non-parametric)
- Sample size calculator for experiment planning

Author: Charlotte Gong
"""

import os
import glob
import pandas as pd
import numpy as np
from scipy.stats import chi2_contingency, mannwhitneyu
from statsmodels.stats.proportion import proportions_ztest, proportion_confint
from statsmodels.stats.power import NormalIndPower
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


class ABTestAnalyzer:
    """
    Statistical analyzer for A/B test experiments.

    Supports:
    - Loading data from CSV or BigQuery
    - Conversion rate analysis (Chi-square, Z-test)
    - Revenue per visitor analysis (Mann-Whitney U)
    - Sample size calculations
    - Automated reporting
    """

    def __init__(self, alpha=0.05):
        """
        Initialize the analyzer.

        Args:
            alpha: Significance level (default 0.05 for 95% confidence)
        """
        self.alpha = alpha
        self.data = None
        self.experiment_results = {}

    def load_csv(self, filepath):
        """Load A/B test data from a CSV file."""
        self.data = pd.read_csv(filepath)
        print(f"✅ Loaded {len(self.data):,} records from CSV")
        print(f"   Columns: {', '.join(self.data.columns)}")
        return self

    def load_from_bigquery(self, days_back=30):
        """Load A/B test data directly from BigQuery."""
        try:
            from google.cloud import bigquery
            from google.oauth2 import service_account

            credentials_path = os.environ.get('BQ_CREDENTIALS_PATH')
            project_id = os.environ.get('BQ_PROJECT_ID')
            dataset_id = os.environ.get('BQ_DATASET_ID')
            table_id = os.environ.get('BQ_TABLE_ID', 'Matomo_ABTest_Data')

            if not all([credentials_path, project_id, dataset_id]):
                raise ValueError("Missing BigQuery environment variables")

            credentials = service_account.Credentials.from_service_account_file(credentials_path)
            client = bigquery.Client(credentials=credentials, project=project_id)

            query = f"""
                SELECT *
                FROM `{project_id}.{dataset_id}.{table_id}`
                WHERE extraction_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days_back} DAY)
            """

            print(f"🔍 Querying BigQuery for last {days_back} days...")
            self.data = client.query(query).to_dataframe()
            print(f"✅ Loaded {len(self.data):,} records from BigQuery")
            return self

        except Exception as e:
            print(f"❌ BigQuery load failed: {e}")
            print("   Falling back to CSV files...")
            return self.load_latest_csv()

    def load_latest_csv(self, directory=None):
        """Load the most recent CSV file from a directory."""
        if directory is None:
            directory = os.path.dirname(os.path.abspath(__file__))

        csv_files = glob.glob(os.path.join(directory, 'matomo_ab_test_data_*.csv'))

        if not csv_files:
            raise FileNotFoundError(f"No CSV files found in {directory}")

        latest = max(csv_files, key=os.path.getctime)
        print(f"📁 Found latest CSV: {os.path.basename(latest)}")
        return self.load_csv(latest)

    def load_dataframe(self, df):
        """Load data from an existing DataFrame."""
        self.data = df.copy()
        print(f"✅ Loaded {len(self.data):,} records from DataFrame")
        return self

    def list_experiments(self):
        """List all available experiments in the data."""
        if self.data is None:
            raise ValueError("No data loaded. Call load_csv() or load_from_bigquery() first.")

        experiments = self.data.groupby('experiment_name').agg({
            'visitor_id': 'nunique',
            'converted': 'sum',
            'variation_name': lambda x: list(x.unique())
        }).reset_index()

        experiments.columns = ['experiment', 'visitors', 'conversions', 'variations']
        return experiments

    def get_summary(self, experiment_name=None):
        """
        Get summary statistics for an experiment.

        Args:
            experiment_name: Filter to specific experiment (optional)

        Returns:
            DataFrame with visitors, conversions, revenue by variation
        """
        df = self.data
        if experiment_name:
            df = df[df['experiment_name'] == experiment_name]

        summary = df.groupby('variation_name').agg({
            'visitor_id': 'nunique',
            'converted': 'sum',
            'order_revenue': 'sum'
        }).reset_index()

        summary.columns = ['variation', 'visitors', 'conversions', 'revenue']
        summary['conv_rate'] = summary['conversions'] / summary['visitors']
        summary['rpv'] = summary['revenue'] / summary['visitors']
        summary['aov'] = summary['revenue'] / summary['conversions'].replace(0, np.nan)

        return summary

    def test_conversion_rate(self, control, treatment, experiment_name=None):
        """
        Test for significant difference in conversion rates.

        Uses Chi-square test and Z-test for proportions.

        Args:
            control: Name of control variation
            treatment: Name of treatment variation
            experiment_name: Filter to specific experiment

        Returns:
            dict with test results, confidence intervals, and recommendation
        """
        df = self.data
        if experiment_name:
            df = df[df['experiment_name'] == experiment_name]

        # Get counts per variation
        ctrl = df[df['variation_name'] == control]
        treat = df[df['variation_name'] == treatment]

        n1 = ctrl['visitor_id'].nunique()
        n2 = treat['visitor_id'].nunique()
        conv1 = int(ctrl['converted'].sum())
        conv2 = int(treat['converted'].sum())

        rate1 = conv1 / n1 if n1 > 0 else 0
        rate2 = conv2 / n2 if n2 > 0 else 0

        # Chi-square test
        table = [[conv1, n1 - conv1], [conv2, n2 - conv2]]
        chi2, p_chi, dof, expected = chi2_contingency(table)

        # Z-test for proportions
        z_stat, p_z = proportions_ztest([conv1, conv2], [n1, n2])

        # Wilson confidence intervals (more accurate for proportions)
        ci1 = proportion_confint(conv1, n1, alpha=self.alpha, method='wilson')
        ci2 = proportion_confint(conv2, n2, alpha=self.alpha, method='wilson')

        # Relative lift
        lift = (rate2 - rate1) / rate1 if rate1 > 0 else 0

        # Determine winner
        if p_z < self.alpha:
            winner = treatment if rate2 > rate1 else control
        else:
            winner = 'Inconclusive'

        return {
            'metric': 'conversion_rate',
            'control': {
                'name': control,
                'n': n1,
                'conversions': conv1,
                'rate': rate1,
                'ci_lower': ci1[0],
                'ci_upper': ci1[1]
            },
            'treatment': {
                'name': treatment,
                'n': n2,
                'conversions': conv2,
                'rate': rate2,
                'ci_lower': ci2[0],
                'ci_upper': ci2[1]
            },
            'z_statistic': z_stat,
            'chi2_statistic': chi2,
            'p_value': p_z,
            'lift': lift,
            'lift_pct': f"{lift:+.1%}",
            'significant': p_z < self.alpha,
            'confidence_level': 1 - self.alpha,
            'winner': winner
        }

    def test_revenue(self, control, treatment, experiment_name=None):
        """
        Test for significant difference in revenue per visitor.

        Uses Mann-Whitney U test (non-parametric, robust to outliers).

        Args:
            control: Name of control variation
            treatment: Name of treatment variation
            experiment_name: Filter to specific experiment

        Returns:
            dict with test results and recommendation
        """
        df = self.data
        if experiment_name:
            df = df[df['experiment_name'] == experiment_name]

        # Aggregate revenue per visitor (including zeros for non-converters)
        ctrl_visitors = df[df['variation_name'] == control]['visitor_id'].unique()
        treat_visitors = df[df['variation_name'] == treatment]['visitor_id'].unique()

        ctrl_rev = df[df['variation_name'] == control].groupby('visitor_id')['order_revenue'].sum()
        treat_rev = df[df['variation_name'] == treatment].groupby('visitor_id')['order_revenue'].sum()

        # Fill missing visitors with 0 revenue
        ctrl_rev = ctrl_rev.reindex(ctrl_visitors, fill_value=0)
        treat_rev = treat_rev.reindex(treat_visitors, fill_value=0)

        mean1, mean2 = ctrl_rev.mean(), treat_rev.mean()
        median1, median2 = ctrl_rev.median(), treat_rev.median()

        # Mann-Whitney U test (non-parametric alternative to t-test)
        stat, p_value = mannwhitneyu(treat_rev, ctrl_rev, alternative='two-sided')

        # Lift calculation
        lift = (mean2 - mean1) / mean1 if mean1 > 0 else 0

        # Determine winner
        if p_value < self.alpha:
            winner = treatment if mean2 > mean1 else control
        else:
            winner = 'Inconclusive'

        return {
            'metric': 'revenue_per_visitor',
            'control': {
                'name': control,
                'n': len(ctrl_rev),
                'mean_rpv': mean1,
                'median_rpv': median1,
                'total_revenue': ctrl_rev.sum(),
                'std': ctrl_rev.std()
            },
            'treatment': {
                'name': treatment,
                'n': len(treat_rev),
                'mean_rpv': mean2,
                'median_rpv': median2,
                'total_revenue': treat_rev.sum(),
                'std': treat_rev.std()
            },
            'u_statistic': stat,
            'p_value': p_value,
            'lift': lift,
            'lift_pct': f"{lift:+.1%}",
            'significant': p_value < self.alpha,
            'confidence_level': 1 - self.alpha,
            'winner': winner
        }

    def sample_size_needed(self, baseline_rate=0.03, mde=0.10, power=0.8):
        """
        Calculate required sample size to detect a given effect.

        Args:
            baseline_rate: Current conversion rate (e.g., 0.03 for 3%)
            mde: Minimum detectable effect as relative change (e.g., 0.10 for 10%)
            power: Statistical power (default 0.8 = 80%)

        Returns:
            dict with sample size per variation and total
        """
        p1 = baseline_rate
        p2 = baseline_rate * (1 + mde)

        # Cohen's h effect size for proportions
        effect = 2 * (np.arcsin(np.sqrt(p2)) - np.arcsin(np.sqrt(p1)))

        analysis = NormalIndPower()
        n = analysis.solve_power(effect_size=effect, alpha=self.alpha, power=power)

        return {
            'baseline_rate': baseline_rate,
            'target_rate': p2,
            'mde': mde,
            'power': power,
            'alpha': self.alpha,
            'per_variation': int(np.ceil(n)),
            'total': int(np.ceil(n * 2)),
            'effect_size': effect
        }

    def analyze(self, experiment_name=None, control='Original', treatment=None):
        """
        Run full statistical analysis and generate report.

        Args:
            experiment_name: Name of experiment to analyze
            control: Name of control variation (default 'Original')
            treatment: Name of treatment variation (auto-detected if None)

        Returns:
            dict with conversion and revenue test results
        """
        summary = self.get_summary(experiment_name)

        print(f"\n{'='*70}")
        print(f"📊 EXPERIMENT: {experiment_name or 'All Data'}")
        print(f"{'='*70}")
        print(f"\n{summary.to_string(index=False)}")

        # Auto-detect treatment if not specified
        if treatment is None:
            variations = summary['variation'].tolist()
            treatment_candidates = [v for v in variations if v != control]
            if not treatment_candidates:
                print(f"⚠️  Only one variation found. Cannot run comparison.")
                return None
            treatment = treatment_candidates[0]

        # Run statistical tests
        conv = self.test_conversion_rate(control, treatment, experiment_name)
        rev = self.test_revenue(control, treatment, experiment_name)

        # Print conversion rate results
        print(f"\n{'─'*70}")
        print(f"📈 CONVERSION RATE ANALYSIS")
        print(f"{'─'*70}")
        print(f"  {control}: {conv['control']['rate']:.2%} "
              f"({conv['control']['conversions']:,}/{conv['control']['n']:,})")
        print(f"  95% CI: [{conv['control']['ci_lower']:.2%}, {conv['control']['ci_upper']:.2%}]")
        print()
        print(f"  {treatment}: {conv['treatment']['rate']:.2%} "
              f"({conv['treatment']['conversions']:,}/{conv['treatment']['n']:,})")
        print(f"  95% CI: [{conv['treatment']['ci_lower']:.2%}, {conv['treatment']['ci_upper']:.2%}]")
        print()
        print(f"  Relative Lift: {conv['lift_pct']}")
        print(f"  P-value: {conv['p_value']:.4f}")
        print(f"  Result: {'✅ SIGNIFICANT' if conv['significant'] else '❌ Not significant'}")
        if conv['significant']:
            print(f"  Winner: 🏆 {conv['winner']}")

        # Print revenue results
        print(f"\n{'─'*70}")
        print(f"💰 REVENUE PER VISITOR ANALYSIS")
        print(f"{'─'*70}")
        print(f"  {control}: ${rev['control']['mean_rpv']:.2f} "
              f"(median: ${rev['control']['median_rpv']:.2f})")
        print(f"  Total Revenue: ${rev['control']['total_revenue']:,.2f}")
        print()
        print(f"  {treatment}: ${rev['treatment']['mean_rpv']:.2f} "
              f"(median: ${rev['treatment']['median_rpv']:.2f})")
        print(f"  Total Revenue: ${rev['treatment']['total_revenue']:,.2f}")
        print()
        print(f"  Relative Lift: {rev['lift_pct']}")
        print(f"  P-value: {rev['p_value']:.4f}")
        print(f"  Result: {'✅ SIGNIFICANT' if rev['significant'] else '❌ Not significant'}")
        if rev['significant']:
            print(f"  Winner: 🏆 {rev['winner']}")

        # Final recommendation
        print(f"\n{'='*70}")
        print(f"📋 RECOMMENDATION")
        print(f"{'='*70}")

        if conv['significant'] and rev['significant']:
            if conv['winner'] == rev['winner']:
                print(f"✅ Both metrics significantly favor '{conv['winner']}'.")
                print(f"   RECOMMENDATION: Implement {conv['winner']}.")
            else:
                print(f"⚠️  Conflicting results:")
                print(f"   - Conversion favors: {conv['winner']}")
                print(f"   - Revenue favors: {rev['winner']}")
                print(f"   RECOMMENDATION: Prioritize based on business goals.")
        elif conv['significant']:
            print(f"📊 Conversion rate is significantly different.")
            print(f"   Winner: {conv['winner']} ({conv['lift_pct']} lift)")
            print(f"   Revenue not significant (p={rev['p_value']:.3f})")
            print(f"   RECOMMENDATION: Consider implementing, monitor revenue closely.")
        elif rev['significant']:
            print(f"💰 Revenue per visitor is significantly different.")
            print(f"   Winner: {rev['winner']} ({rev['lift_pct']} lift)")
            print(f"   Conversion not significant (p={conv['p_value']:.3f})")
            print(f"   RECOMMENDATION: Consider implementing for revenue gains.")
        else:
            print(f"❌ No statistically significant differences detected.")
            print(f"   Conversion p-value: {conv['p_value']:.3f}")
            print(f"   Revenue p-value: {rev['p_value']:.3f}")

            # Check if sample size might be the issue
            total_visitors = conv['control']['n'] + conv['treatment']['n']
            needed = self.sample_size_needed(
                baseline_rate=conv['control']['rate'],
                mde=0.10
            )

            if total_visitors < needed['total']:
                print(f"\n   ℹ️  Current sample: {total_visitors:,} visitors")
                print(f"   ℹ️  Needed for 10% MDE: {needed['total']:,} visitors")
                print(f"   RECOMMENDATION: Continue running the test.")
            else:
                print(f"   RECOMMENDATION: Effect size may be too small to matter.")

        # Store results
        self.experiment_results[experiment_name] = {
            'summary': summary,
            'conversion': conv,
            'revenue': rev,
            'timestamp': datetime.now().isoformat()
        }

        return {'conversion': conv, 'revenue': rev}

    def export_results(self, filepath=None):
        """Export analysis results to JSON."""
        import json

        if not self.experiment_results:
            print("No results to export. Run analyze() first.")
            return

        if filepath is None:
            filepath = f"ab_test_analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

        # Convert to JSON-serializable format
        export_data = {}
        for exp_name, results in self.experiment_results.items():
            export_data[exp_name] = {
                'summary': results['summary'].to_dict('records'),
                'conversion': results['conversion'],
                'revenue': results['revenue'],
                'timestamp': results['timestamp']
            }

        with open(filepath, 'w') as f:
            json.dump(export_data, f, indent=2, default=str)

        print(f"✅ Results exported to: {filepath}")


def main():
    """Main entry point for command-line usage."""
    print("="*70)
    print("A/B TEST STATISTICAL ANALYSIS")
    print("="*70)

    analyzer = ABTestAnalyzer(alpha=0.05)

    # Try to load data
    try:
        # First try BigQuery
        analyzer.load_from_bigquery(days_back=30)
    except Exception as e:
        print(f"BigQuery unavailable: {e}")
        try:
            # Fall back to CSV
            analyzer.load_latest_csv()
        except FileNotFoundError as e:
            print(f"\n❌ {e}")
            print("\nTo use this analyzer:")
            print("  1. Run matomoABTestDataExtract.py to generate data")
            print("  2. Or configure BigQuery credentials in .env")
            return

    # List experiments
    print("\n📋 Available Experiments:")
    experiments = analyzer.list_experiments()
    print(experiments.to_string(index=False))

    # Analyze each experiment
    exp_names = analyzer.data['experiment_name'].dropna().unique()

    for exp in exp_names:
        variations = analyzer.data[
            analyzer.data['experiment_name'] == exp
        ]['variation_name'].unique()

        if len(variations) >= 2:
            # Use first variation as control, second as treatment
            analyzer.analyze(
                experiment_name=exp,
                control=variations[0],
                treatment=variations[1]
            )

    # Sample size calculator
    print(f"\n{'='*70}")
    print("📐 SAMPLE SIZE CALCULATOR")
    print(f"{'='*70}")

    scenarios = [
        (0.02, 0.10),  # 2% baseline, 10% MDE
        (0.03, 0.10),  # 3% baseline, 10% MDE
        (0.03, 0.05),  # 3% baseline, 5% MDE
        (0.05, 0.10),  # 5% baseline, 10% MDE
    ]

    print(f"\n{'Baseline':<12} {'MDE':<8} {'Per Variation':<15} {'Total':<10}")
    print("-" * 50)

    for baseline, mde in scenarios:
        ss = analyzer.sample_size_needed(baseline_rate=baseline, mde=mde)
        print(f"{baseline:.1%}        {mde:.0%}      {ss['per_variation']:>10,}      {ss['total']:>10,}")

    # Export results
    analyzer.export_results()

    print(f"\n{'='*70}")
    print("✅ ANALYSIS COMPLETE")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
