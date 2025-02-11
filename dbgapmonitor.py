#!/usr/bin/env python

"""
File: dbgapmonitor.py
Author: Adam J. Taylor
Date: 2024-05-05
Description: A Python script to monitor dbGaP Authorized Requestors and send a message to Slack.
"""

from datetime import datetime, timedelta
import io
import json
import os

import pandas as pd
import polars as pl
import requests


def get_dbgap_requestors(phs_id):
    """
    Retrieves the list of dbGaP Authorized Requestors for a given study ID.

    Args:
        phs_id (str): The study ID for which the requestors are to be retrieved.

    Returns:
        pandas.DataFrame: A DataFrame containing the dbGaP Authorized Requestors.
    """
    # Download the tab-separated text file
    url = f"https://www.ncbi.nlm.nih.gov/projects/gap/cgi-bin/GetAuthorizedRequestDownload.cgi?study_id={phs_id}"
    response = requests.get(url)

    # Read the CSV file without header and with arbitrary column names
    # Polars is used here as it simplified loading a rather non-standard TSV file
    df = (
        pl.read_csv(
            io.StringIO(response.text),
            separator="\t",
            truncate_ragged_lines=True,
            try_parse_dates=True,
        )
        .rename({"Cloud Service AdministratorData stewardRequestor": "Requestor"})
        .with_columns(pl.col("Date of approval").str.to_date("%b%d, %Y"))
        .sort("Date of approval", descending=True)
    )

    # Strip extra whitespace from the columns
    df = df.with_columns(
        pl.col("Requestor").str.strip_chars(),
        pl.col("Affiliation").str.strip_chars(),
        pl.col("Project").str.strip_chars(),
    )

    return df


def dataframe_to_slack_block_with_md_links(df):
    """
    Converts a pandas DataFrame to a Slack message block with markdown links.

    Args:
        df (pandas.DataFrame): The DataFrame containing the data to be converted.

    Returns:
        dict: A dictionary representing the Slack message block with markdown links.
    """
    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "@channel New dbGaP Authorized Requestors added in the last 7 days!",
            },
        }
    ]
    for index, row in df.iterrows():
        line = f"{row['Requestor']} from {row['Affiliation']} {row['Request status']} on {row['Date of approval'].strftime('%a %d %B')}\n> {row['Project']}"
        block = {"type": "section", "text": {"type": "mrkdwn", "text": f"{line}"}}
        blocks.append(block)
    return {"blocks": blocks}


def send_message_to_slack_blocks(webhook_url, blocks):
    """
    Sends a message to Slack using the provided webhook URL and blocks.

    Args:
        webhook_url (str): The URL of the Slack webhook.
        blocks (list): The blocks to be sent as part of the message.

    Raises:
        ValueError: If the request to Slack returns an error.

    Returns:
        None
    """
    headers = {"Content-Type": "application/json"}
    data = json.dumps(blocks)
    response = requests.post(webhook_url, headers=headers, data=data)
    if response.status_code != 200:
        raise ValueError(
            f"Request to slack returned an error {response.status_code}, the response is:\n{response.text}"
        )


def main():

    # Get the webhook URL from a env variable called SLACK_WEBHOOK_URL
    webhook_url = os.getenv("SLACK_WEBHOOK_URL")

    # Get the study ID from an environment variable
    phs_id = os.getenv("DBGAP_STUDY_ID")

    # Declare the number of days to look back
    lookback_days = 210

    # Get the dbGaP Authorized Requestors for the study ID
    df = get_dbgap_requestors(phs_id)

    # Filter for those approved in the n days
    today = datetime.today()
    start_date = today - timedelta(days=lookback_days)
    df_recent = df.filter(pl.col("Date of approval") > start_date)

    # Perpeare the slack message blocks
    if df_recent.to_pandas().empty:
        # If no modified entities are found, prepare a simple message for Slack
        slack_message_blocks = {
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"No new dbGaP Authorized Requestors added in the last {lookback_days} days",
                    },
                }
            ]
        }
    else:
        # If there are modified entities, format the message as before
        slack_message_blocks = dataframe_to_slack_block_with_md_links(
            df_recent.to_pandas()
        )

    # Send the message to Slack
    send_message_to_slack_blocks(webhook_url, slack_message_blocks)


if __name__ == "__main__":
    main()
