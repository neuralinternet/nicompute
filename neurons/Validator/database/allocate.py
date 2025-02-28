# The MIT License (MIT)
# Copyright © 2023 Rapiiidooo
#
# Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
# documentation files (the “Software”), to deal in the Software without restriction, including without limitation
# the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software,
# and to permit persons to whom the Software is furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all copies or substantial portions of
# the Software.
#
# THE SOFTWARE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO
# THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
# THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
# DEALINGS IN THE SOFTWARE.

import json
from datetime import datetime
from typing import Optional, Tuple, Any

import bittensor as bt

from compute.utils.db import ComputeDb


def select_has_docker_miners_hotkey(db: ComputeDb):
    cursor = db.get_cursor()
    try:
        # Fetch all records from miner_details table
        cursor.execute("SELECT * FROM miner_details")
        rows = cursor.fetchall()

        hotkey_list = []
        for row in rows:
            if row[2]:
                details = json.loads(row[2])
                if details.get("has_docker", False) is True:
                    hotkey_list.append(row[1])
        return hotkey_list
    except Exception as e:
        bt.logging.error(f"Error while getting has_docker hotkeys from miner_details : {e}")
        return []
    finally:
        cursor.close()


# Fetch hotkeys from database that meets device_requirement
def select_allocate_miners_hotkey(db: ComputeDb, device_requirement):
    cursor = db.get_cursor()
    try:
        # Fetch all records from miner_details table
        cursor.execute("SELECT * FROM miner_details")
        rows = cursor.fetchall()

        # Check if the miner meets device_requirement
        hotkey_list = []
        for row in rows:
            details = json.loads(row[2])
            if allocate_check_if_miner_meet(details, device_requirement) is True:
                hotkey_list.append(row[1])
        return hotkey_list
    except Exception as e:
        bt.logging.error(f"Error while getting meet device_req. hotkeys from miner_details : {e}")
        return []
    finally:
        cursor.close()


#  Update the miner_details with specs
"""
This function is temporarily replaced by the hotfix.

def update_miner_details(db: ComputeDb, hotkey_list, benchmark_responses: Tuple[str, Any]):
    cursor = db.get_cursor()
    try:
        cursor.execute(f"DELETE FROM miner_details")
        for index, (hotkey, response) in enumerate(benchmark_responses):
            if json.dumps(response):
                cursor.execute("INSERT INTO miner_details (id, hotkey, details) VALUES (?, ?, ?)", (hotkey_list[index], hotkey, json.dumps(response)))
            else:
                cursor.execute("UPDATE miner SET unresponsive_count = unresponsive_count + 1 WHERE hotkey = ?", (hotkey))
                cursor.execute("DELETE FROM challenge_details WHERE uid IN (SELECT uid FROM miner WHERE unresponsive_count >= 10);")
        db.conn.commit()
    except Exception as e:
        db.conn.rollback()
        bt.logging.error(f"Error while updating miner_details : {e}")
    finally:
        cursor.close()
"""


#  Update the miner_details with specs (hotfix for 1.3.11!)
def update_miner_details(db: ComputeDb, hotkey_list, benchmark_responses: Tuple[str, Any]):
    cursor = db.get_cursor()
    try:
        # Update th database structure while keeping the data
        # Check the number of columns in the miner_details table
        cursor.execute("PRAGMA table_info(miner_details);")
        table_info = cursor.fetchall()
        column_count = len(table_info)

        # Check if there is a UNIQUE index on the hotkey column
        cursor.execute("PRAGMA index_list('miner_details')")
        indices = cursor.fetchall()
        hotkey_unique = False
        for index in indices:
            cursor.execute(f"PRAGMA index_info('{index[1]}')")
            index_info = cursor.fetchall()
            if any(column[2] == 'hotkey' for column in index_info) and index[3] == 0:
                hotkey_unique = True
                break

        # If there are 3 columns or hotkey lacks a UNIQUE constraint, alter the table
        if column_count == 3 or not hotkey_unique:
            # Create a new table with the UNIQUE constraint and no_specs_count column
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS new_miner_details (
                    id INTEGER PRIMARY KEY,
                    hotkey TEXT UNIQUE,
                    details TEXT,
                    no_specs_count INTEGER DEFAULT 0
                );
            """)
            # Copy data from the old table to the new table
            cursor.execute("""
                INSERT INTO new_miner_details (id, hotkey, details)
                SELECT id, hotkey, details FROM miner_details;
            """)
            # Drop the old table
            cursor.execute("DROP TABLE miner_details;")
            # Rename the new table to the old table's name
            cursor.execute("ALTER TABLE new_miner_details RENAME TO miner_details;")
            db.conn.commit()

        # Update miner_details
        for hotkey, response in benchmark_responses:
            # Print current values in the row before updating
            cursor.execute("""
                SELECT * FROM miner_details WHERE hotkey = ?;
            """, (hotkey,))
            current_values = cursor.fetchone()
            # print("Current values in row before updating (hotkey:", hotkey, "):", current_values) # debugging

            if response:  # Check if the response is not empty
                # Update the existing record with the new details or insert a new one
                cursor.execute("""
                    INSERT INTO miner_details (hotkey, details, no_specs_count)
                    VALUES (?, ?, 0)
                    ON CONFLICT(hotkey) DO UPDATE SET
                        details = excluded.details,
                        no_specs_count = 0;
                """, (hotkey, json.dumps(response)))
            else:
                # Increment no_specs_count for the existing record or insert a new one
                cursor.execute("""
                    INSERT INTO miner_details (hotkey, details, no_specs_count)
                    VALUES (?, '{}', 1)
                    ON CONFLICT(hotkey) DO UPDATE SET
                        no_specs_count =
                            CASE
                                WHEN miner_details.no_specs_count >= 5 THEN 5
                                ELSE miner_details.no_specs_count + 1
                            END,
                        details =
                            CASE
                                WHEN miner_details.no_specs_count >= 5 THEN '{}'
                                ELSE excluded.details
                            END;
                """, (hotkey, '{}'))
        db.conn.commit()
    except Exception as e:
        db.conn.rollback()
        bt.logging.error(f"Error while updating miner_details: {e}")
    finally:
        cursor.close()


def get_miner_details(db):
    """
    Retrieves the specifications details for all miners from the database.

    :param db: An instance of ComputeDb to interact with the database.
    :return: A dictionary with hotkeys as keys and their details as values.
    """
    miner_specs_details = {}
    cursor = db.get_cursor()
    try:
        # Fetch all records from miner_details table
        cursor.execute("SELECT hotkey, details FROM miner_details")
        rows = cursor.fetchall()

        # Create a dictionary from the fetched rows
        for row in rows:
            hotkey = row[0]
            details = row[1]
            if details:  # If details are not empty, parse the JSON
                miner_specs_details[hotkey] = json.loads(details)
            else:  # If details are empty, set the value to an empty dictionary
                miner_specs_details[hotkey] = {}
    except Exception as e:
        bt.logging.error(f"Error while retrieving miner details: {e}")
    finally:
        cursor.close()

    return miner_specs_details


#  Update the allocation db
def update_allocation_db(hotkey: str, info: str, flag: bool):
    db = ComputeDb()
    cursor = db.get_cursor()
    try:
        if flag:
            # Insert or update the allocation details
            cursor.execute("""
                INSERT INTO allocation (hotkey, details)
                VALUES (?, ?) ON CONFLICT(hotkey) DO UPDATE SET
                details=excluded.details
            """, (hotkey, json.dumps(info)))
        else:
            # Remove the allocation details based on hotkey
            cursor.execute("DELETE FROM allocation WHERE hotkey = ?", (hotkey,))
        db.conn.commit()
    except Exception as e:
        db.conn.rollback()
        bt.logging.error(f"Error while updating allocation details: {e}")
    finally:
        cursor.close()
        db.close()

#  Update the blacklist db
def update_blacklist_db(hotkeys: list, flag: bool):
    db = ComputeDb()
    cursor = db.get_cursor()
    try:
        if flag:
            # Insert the penalized hotkeys to the blacklist
            cursor.executemany("""
                INSERT INTO blacklist (hotkey)
                VALUES (?) ON CONFLICT(hotkey) DO NOTHING
            """, [(hotkey,) for hotkey in hotkeys])
        else:
            # Remove the hotkeys from the blacklist
            cursor.executemany("DELETE FROM blacklist WHERE hotkey = ?", [(hotkey,) for hotkey in hotkeys])
        db.conn.commit()
    except Exception as e:
        db.conn.rollback()
        bt.logging.error(f"Error while updating blacklist: {e}")
    finally:
        cursor.close()
        db.close()

# Check if the miner meets required details
def allocate_check_if_miner_meet(details, required_details):
    if not details:
        return False
    try:
        # CPU side
        cpu_miner = details["cpu"]
        required_cpu = required_details["cpu"]
        if required_cpu and (not cpu_miner or cpu_miner["count"] < required_cpu["count"]):
            return False

        # GPU side
        gpu_miner = details["gpu"]
        required_gpu = required_details["gpu"]
        if required_gpu:
            if not gpu_miner or gpu_miner["capacity"] <= required_gpu["capacity"] or gpu_miner["count"] < required_gpu["count"]:
                return False
            else:
                gpu_name = str(gpu_miner["details"][0]["name"]).lower()
                required_type = str(required_gpu["type"]).lower()
                if required_type not in gpu_name:
                    return False

        # Hard disk side
        hard_disk_miner = details["hard_disk"]
        required_hard_disk = required_details["hard_disk"]
        if required_hard_disk and (not hard_disk_miner or hard_disk_miner["free"] < required_hard_disk["capacity"]):
            return False

        # Ram side
        ram_miner = details["ram"]
        required_ram = required_details["ram"]
        if required_ram and (not ram_miner or ram_miner["available"] < required_ram["capacity"]):
            return False
    except Exception as e:
        bt.logging.error("The format is wrong, please check it again.")
        return False
    return True

#  Update the hotkey_reliability_report db
def update_hotkey_reliability_report_db(reports: list):
    db = ComputeDb()
    cursor = db.get_cursor()
    try:

        # Prepare data for bulk insert
        report_details_to_insert = [
            (
                datetime.strptime(report.timestamp, '%Y-%m-%dT%H:%M:%S.%fZ'),
                report.hotkey,
                report.rentals,
                report.failed,
                report.rentals_14d,
                report.failed_14d,
                report.aborted,
                report.rental_best,
                report.blacklisted
            )
            for report in reports
        ]
        # Perform bulk insert using executemany
        cursor.executemany(
            "INSERT INTO hotkey_reliability_report"
            "(timestamp, hotkey, rentals, failed, rentals_14d, failed_14d, aborted, rental_best, blacklisted)"
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            report_details_to_insert,
        )
        db.conn.commit()
    except Exception as e:
        db.conn.rollback()
        bt.logging.error(f"Error while updating hotkey_reliability_report: {e}")
    finally:
        cursor.close()
        db.close()


def get_hotkey_reliability_reports_db(db: ComputeDb, hotkey: Optional[str] = None) -> list[dict]:
    """
    Retrieves the hotkey reliability reports for all hotkeys or given hotkey from the database.

    :param db: An instance of ComputeDb to interact with the database.
    :param hotkey: Optional filter to query database for specific hotkey.
    :return: A list with data from each row of the table.
    """
    hotkey_reliability_reports = []
    cursor = db.get_cursor()
    try:
        query = """
            SELECT
                timestamp,
                hotkey,
                rentals,
                failed,
                rentals_14d,
                failed_14d,
                aborted,
                rental_best,
                blacklisted
            FROM hotkey_reliability_report
            {hotkey}
            ORDER BY timestamp
        """.format(
            hotkey = ' WHERE hotkey = ?' if hotkey else ''
        )
        if hotkey:
            cursor.execute(query, (hotkey,))
        else:
            # Fetch all records from hotkey_reliability_report table
            cursor.execute(query)
        rows = cursor.fetchall()

        # Create a dictionary from the fetched rows
        hotkey_reliability_reports = [
            {
                # format to the right datetime format as input: %Y-%m-%dT%H:%M:%S.%fZ
                'timestamp': datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S.%f').strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
                'hotkey': hotkey,
                'rentals': rentals,
                'failed': failed,
                'rentals_14d': rentals_14d,
                'failed_14d': failed_14d,
                'aborted': aborted,
                'rental_best': rental_best,
                'blacklisted': bool(blacklisted),
            }
            for timestamp,
                hotkey,
                rentals,
                failed,
                rentals_14d,
                failed_14d,
                aborted,
                rental_best,
                blacklisted in rows
        ]
    except Exception as e:
        bt.logging.error(f"Error while retrieving hotkey reliability reports: {e}")
    finally:
        cursor.close()

    return hotkey_reliability_reports
