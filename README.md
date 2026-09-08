# Cisco Secure Access → Splunk Collector

A lightweight Python collector that retrieves activity data from the **Cisco Secure Access API** and forwards the events to **Splunk Enterprise using HTTP Event Collector (HEC)**.

The collector is designed for lab and small-scale deployments where Cisco Secure Access activity needs to be available in Splunk for monitoring, investigation, dashboards, and security analytics.

---

## Architecture

```text
Cisco Secure Access
        │
        │ REST API
        ▼
┌──────────────────────────┐
│ secure_access_collector  │
│        Python            │
└────────────┬─────────────┘
             │
             │ Splunk HEC
             ▼
┌──────────────────────────┐
│     Splunk Enterprise    │
│                          │
│ index=secure_access      │
└──────────────────────────┘
```

The collector:

1. Authenticates against the Cisco Secure Access API.
2. Retrieves activity events for the required time window.
3. Follows Cisco's regional API redirect when required.
4. Sends the retrieved events to Splunk HEC.
5. Stores the last successful collection timestamp.
6. Can be executed periodically using systemd.

---

## Features

* Cisco Secure Access API authentication
* OAuth/client-credentials token acquisition
* Regional API redirect handling
* Incremental activity collection
* Persistent collection checkpoint
* Splunk HTTP Event Collector integration
* JSON event forwarding
* Configurable through environment variables
* Python virtual environment support
* systemd service and timer support
* Logging for troubleshooting and operational visibility

---

## Requirements

### Operating system

The collector has been tested on:

* Ubuntu 22.04

Other Linux distributions should work with minor adjustments.

### Software

* Python 3.10+
* `python3-venv`
* `pip`
* systemd
* Cisco Secure Access API access
* Splunk Enterprise with HTTP Event Collector enabled

---

## Installation

Clone the repository:

```bash
git clone https://github.com/<YOUR-USERNAME>/secure-access-collector.git
cd secure-access-collector
```

Create the Python virtual environment:

```bash
python3 -m venv venv
```

Activate it:

```bash
source venv/bin/activate
```

Install the required Python packages:

```bash
pip install -r requirements.txt
```

---

## Configuration

Create the environment configuration file:

```bash
cp .env.example .env
```

Edit the configuration:

```bash
nano .env
```

The collector expects the following variables:

```env
SECURE_ACCESS_API_KEY=
SECURE_ACCESS_API_SECRET=
SPLUNK_HEC_URL=
SPLUNK_HEC_TOKEN=
SPLUNK_INDEX=
```

### Configuration variables

| Variable           | Description                          |
| ------------------ | ------------------------------------ |
| `SECURE_ACCESS_API_KEY`          | Cisco Secure Access API key          |
| `SECURE_ACCESS_API_SECRET`       | Cisco Secure Access API secret       |
| `SPLUNK_HEC_URL`   | Splunk HTTP Event Collector endpoint |
| `SPLUNK_HEC_TOKEN` | Splunk HEC token                     |
| `SPLUNK_INDEX`     | Splunk index receiving the events    |

Example:

```env
SECURE_ACCESS_API_KEY=your_api_key
SECURE_ACCESS_API_SECRET=your_api_secret
SPLUNK_HEC_URL=https://splunk.example.com:8088
SPLUNK_HEC_TOKEN=your_hec_token
SPLUNK_INDEX=secure_access
```

Use the actual values from your Cisco Secure Access and Splunk configuration.

---

## Splunk HTTP Event Collector

The collector sends events to Splunk using HTTP Event Collector.

A typical HEC endpoint is:

```text
https://<splunk-host>:8088
```

The HEC token must have permission to write to the target index.

The configured index should exist in Splunk:

```text
secure_access
```

You can verify incoming events in Splunk with:

```spl
index=secure_access
```

The current Cisco Secure Access events use the following sourcetype:

```text
cisco:secure_access:activity
```

Example Splunk search:

```spl
index=secure_access sourcetype="cisco:secure_access:activity"
```

---

## Running Manually

Activate the virtual environment:

```bash
source venv/bin/activate
```

Run the collector:

```bash
python secure_access_collector.py
```

The collector performs one collection cycle and then exits.

It is **not a continuously running process**.

For continuous periodic collection, use the systemd timer described below.

---

## Collection State

The collector maintains a checkpoint containing the timestamp of the last collection.

This allows subsequent executions to request only the activity occurring since the previous collection.

The state is represented as JSON:

```json
{
  "last_collection": 1788825203
}
```

The timestamp is stored as Unix epoch time.

On the first run, if no checkpoint exists, the collector starts with a short initial collection window.

After a successful collection, the checkpoint is updated.

---

## API Regional Redirect Handling

Cisco Secure Access activity APIs may redirect requests to a regional API endpoint.

The collector explicitly handles the redirect while preserving the authorization headers required by the API.

The activity request uses:

```text
from
to
limit
```

Example request parameters:

```python
params = {
    "from": start_time,
    "to": end_time,
    "limit": 100
}
```

This allows the collector to request activity for a specific time range rather than repeatedly retrieving the same historical data.

---

## Systemd Deployment

The repository includes systemd unit files for running the collector automatically.

Recommended installation directory:

```text
/home/<user>/secure-access-collector
```

Copy the unit files:

```bash
sudo cp systemd/secure-access-collector.service /etc/systemd/system/
sudo cp systemd/secure-access-collector.timer /etc/systemd/system/
```

Edit the service file if necessary so that the paths match the installation directory and username.

Reload systemd:

```bash
sudo systemctl daemon-reload
```

Enable the timer:

```bash
sudo systemctl enable --now secure-access-collector.timer
```

Start the collector manually for the first run:

```bash
sudo systemctl start secure-access-collector.service
```

---

## Check the Timer

Check the timer status:

```bash
systemctl status secure-access-collector.timer
```

List scheduled timers:

```bash
systemctl list-timers --all | grep secure-access
```

The timer periodically starts the collector service.

---

## Check the Service

Check the most recent execution:

```bash
systemctl status secure-access-collector.service
```

The service is designed as a `oneshot` service.

Therefore, it is normal for the service to show:

```text
Active: inactive (dead)
```

after a successful execution.

The **timer** is the component that remains active and starts the service on schedule.

A successful service execution should show:

```text
code=exited, status=0/SUCCESS
```

---

## View Logs

View the systemd journal:

```bash
journalctl -u secure-access-collector.service
```

Follow the logs in real time:

```bash
journalctl -u secure-access-collector.service -f
```

View recent executions:

```bash
journalctl -u secure-access-collector.service --since "1 hour ago"
```

The collector also writes operational logging according to its configured logging behavior.

---

## Example Successful Run

A successful execution looks similar to:

```text
Loaded collector state
Starting Secure Access collection
Collection window: 1788824651 -> 1788825203
Requesting a new Secure Access access token
New Secure Access token obtained. Lifetime: 3600 seconds
Querying Secure Access activity from 1788824651 to 1788825203
Following Secure Access regional redirect: https://api.umbrella.com/reports.eu/v2/activity?from=1788824651&to=1788825203&limit=100
Retrieved 0 events
Collector state saved
Collection completed successfully
```

When activity is available, the collector sends the events to Splunk before updating the collection checkpoint.

---

## Splunk Data

The collector sends Cisco Secure Access activity to:

```text
index=secure_access
```

The expected sourcetype is:

```text
cisco:secure_access:activity
```

Useful fields include:

```text
timestamp
date
type
eventtype
verdict
blockreason
sourceip
sourceport
destinationip
destinationport
protocol.label
rule.label
rule.traffictype
trafficsource
datacenter.label
rxbytes
txbytes
identities{}.label
applicationprotocols{}.category.label
```

Example event search:

```spl
index=secure_access sourcetype="cisco:secure_access:activity"
```

---

## Useful Splunk Searches

### Total Secure Access events

```spl
index=secure_access
| stats count
```

### Allowed vs blocked traffic

```spl
index=secure_access
| stats count by verdict
| sort -count
```

### Top source IPs

```spl
index=secure_access
| stats count by sourceip
| sort -count
```

### Top destination IPs

```spl
index=secure_access
| stats count by destinationip
| sort -count
```

### Top identities

```spl
index=secure_access
| eval identity=mvjoin('identities{}.label', ", ")
| stats count by identity
| sort -count
```

### Traffic by rule

```spl
index=secure_access
| stats count by 'rule.label'
| sort -count
```

### Traffic by protocol

```spl
index=secure_access
| stats count by 'protocol.label'
| sort -count
```

### Traffic by data center

```spl
index=secure_access
| stats count by 'datacenter.label'
| sort -count
```

---

## Troubleshooting

### Check Python

```bash
python3 --version
```

### Check the virtual environment

```bash
./venv/bin/python --version
```

### Verify dependencies

```bash
./venv/bin/pip list
```

### Run the collector directly

```bash
./venv/bin/python secure_access_collector.py
```

### Check systemd

```bash
systemctl status secure-access-collector.timer
systemctl status secure-access-collector.service
```

### Check recent logs

```bash
journalctl -u secure-access-collector.service --since "30 minutes ago"
```

### Verify Splunk ingestion

```spl
index=secure_access
| stats count
```

If no events are arriving, verify:

1. Cisco Secure Access API credentials.
2. API connectivity.
3. Splunk HEC URL.
4. Splunk HEC token.
5. HEC is enabled.
6. The HEC token can write to the configured index.
7. The `secure_access` index exists.
8. The collector service is executing successfully.

---

## Project Structure

```text
secure-access-collector/
├── README.md
├── secure_access_collector.py
├── requirements.txt
├── .env.example
├── .gitignore
└── systemd/
    ├── secure-access-collector.service
    └── secure-access-collector.timer
```

---

## Security

Configuration values are provided through environment variables rather than being embedded directly in the Python source.

The `.env` file should be protected with appropriate filesystem permissions.

For example:

```bash
chmod 600 .env
```

Do not hard-code API credentials or Splunk HEC credentials into the Python source.

---

## API Collection Model

The collector uses an incremental collection model:

```text
Previous checkpoint
        │
        ▼
   start_time
        │
        │
        ▼
   Cisco Secure Access
        │
        │ activity
        ▼
      events
        │
        ▼
    Splunk HEC
        │
        ▼
 New checkpoint
```

Each successful execution advances the checkpoint to the end of the collection window.

If a collection fails, the checkpoint is not advanced, allowing the next execution to retry the previous collection window.

---

## Pagination

The collector currently requests activity with a maximum result limit of:

```text
100
```

The Cisco Secure Access API supports pagination through `offset` and `limit`.

For environments where more than 100 activity events can occur during a single collection interval, pagination should be implemented so that all events in the requested window are retrieved.

For higher-volume production deployments, collection overlap and event deduplication should also be considered.

---

## Scheduling

The collector itself is a one-shot process.

For example:

```text
systemd timer
      │
      ▼
collector starts
      │
      ▼
authenticate
      │
      ▼
collect activity
      │
      ▼
send to Splunk
      │
      ▼
save checkpoint
      │
      ▼
collector exits
```

The systemd timer then starts the collector again at the configured interval.

