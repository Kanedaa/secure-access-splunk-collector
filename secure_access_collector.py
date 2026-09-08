#!/usr/bin/env python3

import os
import time
import json
import logging
from pathlib import Path

import requests
from dotenv import load_dotenv


# --------------------------------------------------
# Configuration
# --------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent

load_dotenv(BASE_DIR / ".env")

TOKEN_URL = "https://api.sse.cisco.com/auth/v2/token"

ACTIVITY_URL = (
    "https://api.sse.cisco.com/"
    "reports/v2/activity"
)

SECURE_ACCESS_API_KEY = os.getenv(
    "SECURE_ACCESS_API_KEY"
)

SECURE_ACCESS_API_SECRET = os.getenv(
    "SECURE_ACCESS_API_SECRET"
)

SPLUNK_HEC_TOKEN = os.getenv(
    "SPLUNK_HEC_TOKEN"
)

SPLUNK_HEC_URL = os.getenv(
    "SPLUNK_HEC_URL",
    "https://127.0.0.1:8088/services/collector"
)

SPLUNK_INDEX = os.getenv(
    "SPLUNK_INDEX",
    "secure_access"
)

STATE_FILE = BASE_DIR / "state.json"

LOG_FILE = BASE_DIR / "collector.log"


# --------------------------------------------------
# Logging
# --------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)


# --------------------------------------------------
# HTTP session
# --------------------------------------------------

session = requests.Session()

access_token = None
token_expiry = 0


# --------------------------------------------------
# Validate configuration
# --------------------------------------------------

def validate_configuration():

    required_variables = {
        "SECURE_ACCESS_API_KEY":
            SECURE_ACCESS_API_KEY,

        "SECURE_ACCESS_API_SECRET":
            SECURE_ACCESS_API_SECRET,

        "SPLUNK_HEC_TOKEN":
            SPLUNK_HEC_TOKEN
    }

    missing = [
        name
        for name, value in required_variables.items()
        if not value
    ]

    if missing:

        raise RuntimeError(
            "Missing environment variables: "
            + ", ".join(missing)
        )


# --------------------------------------------------
# Token management
# --------------------------------------------------

def get_access_token():

    global access_token
    global token_expiry

    # Reuse the token until it has less than
    # five minutes remaining.
    if (
        access_token
        and time.time() < token_expiry - 300
    ):

        logging.info(
            "Using existing Secure Access access token"
        )

        return access_token

    logging.info(
        "Requesting a new Secure Access access token"
    )

    response = session.post(
        TOKEN_URL,

        auth=(
            SECURE_ACCESS_API_KEY,
            SECURE_ACCESS_API_SECRET
        ),

        headers={
            "Content-Type":
                "application/x-www-form-urlencoded"
        },

        data={
            "grant_type":
                "client_credentials"
        },

        timeout=30
    )

    response.raise_for_status()

    token_data = response.json()

    access_token = token_data["access_token"]

    expires_in = token_data.get(
        "expires_in",
        3600
    )

    token_expiry = (
        time.time() + int(expires_in)
    )

    logging.info(
        "New Secure Access token obtained. "
        "Lifetime: %s seconds",
        expires_in
    )

    return access_token


# --------------------------------------------------
# State management
# --------------------------------------------------

def load_state():

    if STATE_FILE.exists():

        try:

            with open(
                STATE_FILE,
                "r",
                encoding="utf-8"
            ) as state_file:

                state = json.load(state_file)

                logging.info(
                    "Loaded collector state"
                )

                return state

        except Exception as error:

            logging.warning(
                "Unable to load state file: %s",
                error
            )

    # First execution:
    # Collect the previous two minutes.
    return {
        "last_collection":
            int(time.time()) - 120
    }


def save_state(state):

    temporary_file = (
        STATE_FILE.with_suffix(".tmp")
    )

    with open(
        temporary_file,
        "w",
        encoding="utf-8"
    ) as state_file:

        json.dump(
            state,
            state_file,
            indent=2
        )

    temporary_file.replace(
        STATE_FILE
    )

    logging.info(
        "Collector state saved"
    )


# --------------------------------------------------
# Retrieve Secure Access activity
# --------------------------------------------------

def get_activity(
    start_time,
    end_time
):

    global access_token
    global token_expiry

    token = get_access_token()

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    params = {
        "from": start_time,
        "to": end_time,
        "limit": 100
    }

    logging.info(
        "Querying Secure Access activity "
        "from %s to %s",
        start_time,
        end_time
    )

    # First request: do NOT automatically follow the regional
    # redirect. Cisco Secure Access may redirect the request to
    # api.umbrella.com, and we want to explicitly preserve the
    # Authorization header.
    response = session.get(
        ACTIVITY_URL,
        headers=headers,
        params=params,
        allow_redirects=False,
        timeout=60
    )

    # Secure Access reporting API may return HTTP 302 to a
    # regional endpoint such as reports.eu or reports.us.
    if response.status_code in (301, 302, 307, 308):

        redirect_url = response.headers.get("Location")

        if not redirect_url:
            raise RuntimeError(
                "Secure Access returned a redirect "
                "without a Location header"
            )

        logging.info(
            "Following Secure Access regional redirect: %s",
            redirect_url
        )

        # Explicitly send the Authorization header to the
        # redirected regional endpoint.
        response = session.get(
            redirect_url,
            headers=headers,
            allow_redirects=True,
            timeout=60
        )

    # Retry once with a newly obtained token if
    # authentication is rejected.
    if response.status_code in (401, 403):

        logging.warning(
            "Authentication rejected. "
            "Obtaining a new token and retrying."
        )

        access_token = None
        token_expiry = 0

        token = get_access_token()

        headers["Authorization"] = f"Bearer {token}"

        response = session.get(
            ACTIVITY_URL,
            headers=headers,
            params=params,
            allow_redirects=False,
            timeout=60
        )

        # Handle regional redirect again after token refresh.
        if response.status_code in (301, 302, 307, 308):

            redirect_url = response.headers.get("Location")

            if not redirect_url:
                raise RuntimeError(
                    "Secure Access returned a redirect "
                    "without a Location header"
                )

            logging.info(
                "Following Secure Access regional redirect "
                "after token refresh: %s",
                redirect_url
            )

            response = session.get(
                redirect_url,
                headers=headers,
                allow_redirects=True,
                timeout=60
            )

    response.raise_for_status()

    return response.json()
# --------------------------------------------------
# Extract events
# --------------------------------------------------

def extract_events(data):

    if isinstance(data, list):

        return data

    if isinstance(data, dict):

        # Common API response structures
        for field in (
            "data",
            "results",
            "events",
            "activity"
        ):

            if (
                field in data
                and isinstance(
                    data[field],
                    list
                )
            ):

                return data[field]

        # Log the top-level fields to help us
        # identify the response structure.
        logging.warning(
            "Unexpected API response structure. "
            "Top-level fields: %s",
            list(data.keys())
        )

    return []


# --------------------------------------------------
# Send events to Splunk HEC
# --------------------------------------------------

def send_to_splunk(events):

    successful_events = 0

    for event in events:

        payload = {
            "time":
                time.time(),

            "host":
                "cisco-secure-access",

            "source":
                "secure_access_api",

            "sourcetype":
                "cisco:secure_access:activity",

            "index":
                SPLUNK_INDEX,

            "event":
                event
        }

        response = session.post(
            SPLUNK_HEC_URL,

            headers={
                "Authorization":
                    f"Splunk {SPLUNK_HEC_TOKEN}"
            },

            json=payload,

            # Change to True if your Splunk
            # certificate is trusted.
            verify=False,

            timeout=30
        )

        response.raise_for_status()

        successful_events += 1

    logging.info(
        "Successfully sent %s events "
        "to Splunk",
        successful_events
    )

    return successful_events


# --------------------------------------------------
# Main collector
# --------------------------------------------------

def main():

    validate_configuration()

    state = load_state()

    start_time = state[
        "last_collection"
    ]

    end_time = int(
        time.time()
    )

    logging.info(
        "Starting Secure Access collection"
    )

    logging.info(
        "Collection window: %s -> %s",
        start_time,
        end_time
    )

    try:

        data = get_activity(
            start_time,
            end_time
        )

        events = extract_events(
            data
        )

        logging.info(
            "Retrieved %s events",
            len(events)
        )

        if events:

            send_to_splunk(events)

        # Only update the checkpoint after
        # successful processing.
        state["last_collection"] = (
            end_time
        )

        save_state(state)

        logging.info(
            "Collection completed successfully"
        )

    except Exception as error:

        logging.exception(
            "Collection failed: %s",
            error
        )

        raise


if __name__ == "__main__":

    main()
