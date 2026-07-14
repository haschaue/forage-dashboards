"""Google Search Console API client for Forage Kitchen.

Auth via service account key (gsc_credentials.json, gitignored).
The service account email must be added as a user on the Search Console
property: forage@skilled-cargo-368720.iam.gserviceaccount.com
"""
import os

from google.oauth2 import service_account
from googleapiclient.discovery import build

CREDENTIALS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gsc_credentials.json")
SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]


def get_service():
    creds = service_account.Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)
    return build("searchconsole", "v1", credentials=creds, cache_discovery=False)


def list_properties(service=None):
    service = service or get_service()
    resp = service.sites().list().execute()
    return resp.get("siteEntry", [])


def query_search_analytics(site_url, start_date, end_date, dimensions=None,
                           filters=None, row_limit=1000, service=None):
    """Query search analytics. Dates are YYYY-MM-DD strings.

    dimensions: list from query/page/country/device/date/searchAppearance
    filters: list of dicts like {"dimension": "page", "operator": "contains", "expression": "/madison"}
    """
    service = service or get_service()
    body = {
        "startDate": start_date,
        "endDate": end_date,
        "dimensions": dimensions or ["query"],
        "rowLimit": row_limit,
    }
    if filters:
        body["dimensionFilterGroups"] = [{"filters": filters}]
    resp = service.searchanalytics().query(siteUrl=site_url, body=body).execute()
    return resp.get("rows", [])


if __name__ == "__main__":
    sites = list_properties()
    if not sites:
        print("Connected OK, but no properties visible.")
        print("Add forage@skilled-cargo-368720.iam.gserviceaccount.com as a user in Search Console:")
        print("  https://search.google.com/search-console > Settings > Users and permissions")
    else:
        print(f"Connected. {len(sites)} propert{'y' if len(sites) == 1 else 'ies'}:")
        for s in sites:
            print(f"  {s['siteUrl']}  ({s['permissionLevel']})")
