# The MIT License (MIT)
# Copyright © 2023 Crazydevlegend
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

import ast
import asyncio
import base64
import json
import os
import random
import threading
import traceback
import hashlib
import numpy as np
import yaml
import multiprocessing
from asyncio import AbstractEventLoop
from typing import Dict, Tuple, List

import bittensor as bt
import math
import time
import paramiko

import cryptography
import torch
from cryptography.fernet import Fernet
from torch._C._te import Tensor # type: ignore
import RSAEncryption as rsa
import concurrent.futures
from collections import defaultdict

import Validator.app_generator as ag
from compute import (
    SUSPECTED_EXPLOITERS_HOTKEYS,
    SUSPECTED_EXPLOITERS_COLDKEYS,
    __version_as_int__,
    validator_permit_stake,
    weights_rate_limit
    )
from compute.axon import ComputeSubnetSubtensor
from compute.protocol import Allocate, Challenge, Specs
from compute.utils.db import ComputeDb
from compute.utils.math import percent, force_to_float_or_default
from compute.utils.parser import ComputeArgPaser
from compute.utils.subtensor import is_registered, get_current_block, calculate_next_block_time
from compute.utils.version import try_update, get_local_version, version2number, get_remote_version
from compute.wandb.wandb import ComputeWandb
from neurons.Validator.calculate_pow_score import calc_score_pog
from neurons.Validator.database.allocate import update_miner_details, select_has_docker_miners_hotkey, get_miner_details
from neurons.Validator.database.challenge import select_challenge_stats, update_challenge_details
from neurons.Validator.database.miner import select_miners, purge_miner_entries, update_miners
from neurons.Validator.pog import adjust_matrix_size, compute_script_hash, execute_script_on_miner, get_random_seeds, load_yaml_config, parse_merkle_output, receive_responses, send_challenge_indices, send_script_and_request_hash, parse_benchmark_output, identify_gpu, send_seeds, verify_merkle_proof_row, get_remote_gpu_info, verify_responses
from neurons.Validator.database.pog import get_pog_specs, retrieve_stats, update_pog_stats, write_stats

class Validator:
    blocks_done: set = set()

    pow_requests: dict = {}
    pow_responses: dict = {}
    pow_benchmark: dict = {}
    new_pow_benchmark: dict = {}
    pow_benchmark_success: dict = {}

    queryable_for_specs: dict = {}
    finalized_specs_once: bool = False

    total_current_miners: int = 0

    scores: Tensor
    stats: dict

    validator_subnet_uid: int

    _queryable_uids: Dict[int, bt.AxonInfo]

    loop: AbstractEventLoop

    @property
    def wallet(self) -> bt.wallet:
        return self._wallet

    @property
    def subtensor(self) -> ComputeSubnetSubtensor:
        return self._subtensor


    @property
    def metagraph(self) -> bt.metagraph: # type: ignore
        return self._metagraph

    @property
    def queryable(self):
        return self._queryable_uids

    @property
    def queryable_uids(self):
        return [uid for uid in self._queryable_uids.keys()]

    @property
    def queryable_axons(self):
        return [axon for axon in self._queryable_uids.values()]

    @property
    def queryable_hotkeys(self):
        return [axon.hotkey for axon in self._queryable_uids.values()]

    @property
    def current_block(self):
        return get_current_block(subtensor=self.subtensor)

    @property
    def miners_items_to_set(self):
        return set((uid, hotkey) for uid, hotkey in self.miners.items()) if self.miners else None

    def __init__(self):
        # Step 1: Parse the bittensor and compute subnet config
        self.config = self.init_config()

        # Setup extra args
        self.blacklist_hotkeys = {hotkey for hotkey in self.config.blacklist_hotkeys}
        self.blacklist_coldkeys = {coldkey for coldkey in self.config.blacklist_coldkeys}
        self.whitelist_hotkeys = {hotkey for hotkey in self.config.whitelist_hotkeys}
        self.whitelist_coldkeys = {coldkey for coldkey in self.config.whitelist_coldkeys}
        self.exploiters_hotkeys = {hotkey for hotkey in SUSPECTED_EXPLOITERS_HOTKEYS} if self.config.blacklist_exploiters else {}
        self.exploiters_coldkeys = {coldkey for coldkey in SUSPECTED_EXPLOITERS_COLDKEYS} if self.config.blacklist_exploiters else {}

        # Set custom validator arguments
        self.validator_specs_batch_size = self.config.validator_specs_batch_size
        self.validator_challenge_batch_size = self.config.validator_challenge_batch_size
        self.validator_perform_hardware_query = self.config.validator_perform_hardware_query
        self.validator_whitelist_updated_threshold = self.config.validator_whitelist_updated_threshold

        # Set up logging with the provided configuration and directory.
        bt.logging(config=self.config, logging_dir=self.config.full_path)
        bt.logging.info(f"Running validator for subnet: {self.config.netuid} on network: {self.config.subtensor.chain_endpoint} with config:")
        # Log the configuration for reference.
        bt.logging.info(self.config)

        # Step 2: Build Bittensor validator objects
        # These are core Bittensor classes to interact with the network.
        bt.logging.info("Setting up bittensor objects.")

        # The wallet holds the cryptographic key pairs for the validator.
        self._wallet = bt.wallet(config=self.config)
        bt.logging.info(f"Wallet: {self.wallet}")

        # The subtensor is our connection to the Bittensor blockchain.
        self._subtensor = ComputeSubnetSubtensor(config=self.config)
        bt.logging.info(f"Subtensor: {self.subtensor}")

        # The metagraph holds the state of the network, letting us know about other miners.
        self._metagraph = self.subtensor.metagraph(self.config.netuid)
        bt.logging.info(f"Metagraph: {self.metagraph}")

        # Initialize the local db
        self.db = ComputeDb()
        self.miners: dict = select_miners(self.db)

        # Initialize wandb
        self.wandb = ComputeWandb(self.config, self.wallet, os.path.basename(__file__))

        # STEP 2B: Init Proof of GPU
        # Load configuration from YAML
        config_file = "config.yaml"
        self.config_data = load_yaml_config(config_file)
        cpu_cores = os.cpu_count() or 1
        configured_max_workers = self.config_data["merkle_proof"].get("max_workers", 32)
        safe_max_workers = min((cpu_cores + 4)*4, configured_max_workers)
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=safe_max_workers)
        self.results = {}
        self.gpu_task = None  # Track the GPU task

        # Step 3: Set up initial scoring weights for validation
        bt.logging.info("Building validation weights.")
        self.uids: list = self.metagraph.uids.tolist()
        self.last_uids: list = self.uids.copy()
        self.init_scores()
        self.sync_status()

        self.last_updated_block = self.current_block - (self.current_block % 100)

        # Initialize allocated_hotkeys as an empty list
        self.allocated_hotkeys = []

        # Initialize penalized_hotkeys as an empty list
        self.penalized_hotkeys = []

        # Initialize penalized_hotkeys_checklist as an empty list
        self.penalized_hotkeys_checklist = []

        # Init the thread.
        self.lock = threading.Lock()
        self.threads: List[threading.Thread] = []

        self.dendrite = bt.dendrite(wallet=self.wallet)

    @staticmethod
    def init_config():
        """
        This function is responsible for setting up and parsing command-line arguments.
        :return: config
        """
        parser = ComputeArgPaser(description="This script aims to help validators with the compute subnet.")
        config = parser.config

        # Step 3: Set up logging directory
        # Logging is crucial for monitoring and debugging purposes.
        config.full_path = os.path.expanduser(
            "{}/{}/{}/netuid{}/{}".format(
                config.logging.logging_dir,
                config.wallet.name,
                config.wallet.hotkey,
                config.netuid,
                "validator",
            )
        )
        # Ensure the logging directory exists.
        if not os.path.exists(config.full_path):
            os.makedirs(config.full_path, exist_ok=True)

        # Return the parsed config.
        return config

    def init_prometheus(self):
        """
        Register the prometheus information on metagraph.
        :return: bool
        """
        # extrinsic prometheus is removed at 8.2.1

        bt.logging.info("Extrinsic prometheus information on metagraph.")

        success = self._subtensor.serve_prometheus(
            wallet=self.wallet,
            port=bt.core.settings.DEFAULTS.axon.port,
            netuid=self.config.netuid
        )
        if success:
            bt.logging.success(
                prefix="Prometheus served",
                suffix=f"<blue>Current version: {get_local_version()}</blue>"  # Corrected keyword
            )
        else:
            bt.logging.error("Prometheus initialization failed")
        return success

    def init_local(self):
        bt.logging.info(f"🔄 Syncing metagraph with subtensor.")
        self._metagraph = self.subtensor.metagraph(self.config.netuid)
        self.uids = self.metagraph.uids.tolist()

    def init_scores(self):
        self.scores = torch.zeros(len(self.uids), dtype=torch.float32)
        # Set the weights of validators to zero.
        self.scores = self.scores * (self.metagraph.total_stake < 1.024e3)
        # Set the weight to zero for all nodes without assigned IP addresses.
        self.scores = self.scores * torch.Tensor(self.get_valid_tensors(metagraph=self.metagraph))
        bt.logging.info(f"🔢 Initialized scores : {self.scores.tolist()}")
        self.sync_scores()

    @staticmethod
    def pretty_print_dict_values(items: dict):
        for key, values in items.items():
            log = f"uid: {key}"

            for values_key, values_values in values.items():
                if values_key == "ss58_address":
                    values_values = values_values[:8] + (values_values[8:] and "...")
                try:
                    values_values = f"{float(values_values):.2f}"
                except Exception:
                    pass
                log += f" | {values_key}: {values_values}"

            bt.logging.trace(log)

    def update_allocation_wandb(self):
        hotkey_list = []
        # Instantiate the connection to the db
        cursor = self.db.get_cursor()
        try:
            # Retrieve all records from the allocation table
            cursor.execute("SELECT id, hotkey, details FROM allocation")
            rows = cursor.fetchall()
            for row in rows:
                id, hotkey, details = row
                hotkey_list.append(hotkey)
        except Exception as e:
            bt.logging.info(f"An error occurred while retrieving allocation details: {e}")
        finally:
            cursor.close()

        # Update wandb
        try:
            self.wandb.update_allocated_hotkeys(hotkey_list)
        except Exception as e:
            bt.logging.info(f"Error updating wandb : {e}")

    def sync_scores(self):
        # Fetch scoring stats
        self.stats = retrieve_stats(self.db)

        valid_validator_hotkeys = self.get_valid_validator_hotkeys()

        self.update_allocation_wandb()

        # Fetch allocated hotkeys and stats
        self.allocated_hotkeys = self.wandb.get_allocated_hotkeys(valid_validator_hotkeys, True)
        self.stats_allocated = self.wandb.get_stats_allocated(valid_validator_hotkeys, True)
        self.penalized_hotkeys = self.wandb.get_penalized_hotkeys_checklist_bak(valid_validator_hotkeys, True)
        self._queryable_uids = self.get_queryable()

        # Calculate score
        for uid in self.uids:
            try:
                axon = self._queryable_uids[uid]
                hotkey = axon.hotkey

                if uid not in self.stats:
                    self.stats[uid] = {}

                self.stats[uid]["hotkey"] = hotkey

                # Mark whether this hotkey is in the allocated list
                self.stats[uid]["allocated"] = hotkey in self.allocated_hotkeys

                # Check GPU specs in our PoG DB
                gpu_specs = get_pog_specs(self.db, hotkey)

                # If found in our local database
                if gpu_specs is not None:
                    score = calc_score_pog(gpu_specs, hotkey, self.allocated_hotkeys, self.config_data)
                    self.stats[uid]["own_score"] = True  # or "yes" if you prefer a string
                else:
                    # If not found locally, try fallback from stats_allocated
                    if uid in self.stats_allocated:
                        score = self.stats_allocated[uid].get("score", 0)/100
                        gpu_specs = self.stats_allocated[uid].get("gpu_specs", None)
                        self.stats[uid]["own_score"] = False  # or "no"
                    else:
                        score = 0
                        self.stats[uid]["own_score"] = True  # or "no"
                
                if hotkey in self.penalized_hotkeys:
                    score = 0
                self.stats[uid]["score"] = score*100
                self.stats[uid]["gpu_specs"] = gpu_specs
                # Keep or override reliability_score if you want
                if "reliability_score" not in self.stats[uid]:
                    self.stats[uid]["reliability_score"] = 0

            except KeyError as e:
                bt.logging.trace(f"KeyError occurred for UID {uid}: {str(e)}")
                score = 0
            except Exception as e:
                bt.logging.trace(f"An unexpected exception occurred for UID {uid}: {str(e)}")
                score = 0

            # Keep a simple reference of scores
            self.scores[uid] = score

        write_stats(self.db, self.stats)

        self.update_allocation_wandb()

        bt.logging.info("-" * 190)
        bt.logging.info("MINER STATS SUMMARY".center(190))
        bt.logging.info("-" * 190)

        for uid, data in self.stats.items():
            hotkey_str = str(data.get("hotkey", "unknown"))

            # Parse GPU specs into a human-readable format
            gpu_specs = data.get("gpu_specs")
            if isinstance(gpu_specs, dict):
                gpu_name = gpu_specs.get("gpu_name", "Unknown GPU")
                num_gpus = gpu_specs.get("num_gpus", 0)
                gpu_str = f"{num_gpus} x {gpu_name}" if num_gpus > 0 else "No GPUs"
            else:
                gpu_str = "N/A"  # Fallback if gpu_specs is not a dict

            # Format score as a float with 2 decimal digits
            raw_score = float(data.get("score", 0))
            score_str = f"{raw_score:.2f}"

            # Retrieve additional fields
            allocated = "yes" if data.get("allocated", False) else "no"
            reliability_score = data.get("reliability_score", 0)
            source = "Local" if data.get("own_score", False) else "External"

            # Format the log with fixed-width fields
            log_entry = (
                f"| UID: {uid:<4} | Hotkey: {hotkey_str:<45} | GPU: {gpu_str:<36} | "
                f"Score: {score_str:7} | Allocated: {allocated:<5} | "
                f"RelScore: {reliability_score:<5} | Source: {source:<9} |"
            )
            bt.logging.info(log_entry)

        # Add a closing dashed line
        bt.logging.info("-" * 190)

        bt.logging.info(f"🔢 Synced scores : {self.scores.tolist()}")

    def sync_local(self):
        """
        Resync our local state with the latest state from the blockchain.
        Sync scores with metagraph.
        Get the current uids of all miners in the network.
        """
        self.metagraph.sync(subtensor=self.subtensor)
        self.uids = self.metagraph.uids.tolist()

    def sync_status(self):
        # Check if the validator is still registered
        self.validator_subnet_uid = is_registered(
            wallet=self.wallet,
            metagraph=self.metagraph,
            subtensor=self.subtensor,
            entity="validator",
        )

        # Check for auto update
        if self.config.auto_update:
            try_update()

        # Check if the validator has the prometheus info updated
        subnet_prometheus_version = self.metagraph.neurons[self.validator_subnet_uid].prometheus_info.version
        current_version = __version_as_int__
        if subnet_prometheus_version != current_version:
            self.init_prometheus()

    def sync_miners_info(self, queryable_tuple_uids_axons: List[Tuple[int, bt.AxonInfo]]):
        if queryable_tuple_uids_axons:
            for uid, axon in queryable_tuple_uids_axons:
                if self.miners_items_to_set and (uid, axon.hotkey) not in self.miners_items_to_set:
                    try:
                        bt.logging.info(f"❌ Miner {uid}-{self.miners[uid]} has been deregistered. Clean up old entries.")
                        purge_miner_entries(self.db, uid, self.miners[uid])
                    except KeyError:
                        pass
                    bt.logging.info(f"✅ Setting up new miner {uid}-{axon.hotkey}.")
                    update_miners(self.db, [(uid, axon.hotkey)]),
                    self.miners[uid] = axon.hotkey
        else:
            bt.logging.warning(f"❌ No queryable miners.")

    @staticmethod
    def filter_axons(queryable_tuple_uids_axons: List[Tuple[int, bt.AxonInfo]]):
        """Filter the axons with uids_list, remove those with the same IP address."""
        # Set to keep track of unique identifiers
        valid_ip_addresses = set()

        # List to store filtered axons
        dict_filtered_axons = {}
        for uid, axon in queryable_tuple_uids_axons:
            ip_address = axon.ip

            if ip_address not in valid_ip_addresses:
                valid_ip_addresses.add(ip_address)
                dict_filtered_axons[uid] = axon

        return dict_filtered_axons

    def filter_axon_version(self, dict_filtered_axons: dict):
        # Get the minimal miner version
        latest_version = version2number(get_remote_version(pattern="__minimal_miner_version__"))
        if percent(len(dict_filtered_axons), self.total_current_miners) <= self.validator_whitelist_updated_threshold:
            bt.logging.info(f"Less than {self.validator_whitelist_updated_threshold}% miners are currently using the last version. Allowing all.")
            return dict_filtered_axons

        dict_filtered_axons_version = {}
        for uid, axon in dict_filtered_axons.items():
            if latest_version and latest_version <= axon.version:
                dict_filtered_axons_version[uid] = axon
        return dict_filtered_axons_version

    def is_blacklisted(self, neuron: bt.NeuronInfoLite):
        coldkey = neuron.coldkey
        hotkey = neuron.hotkey

        # Blacklist coldkeys that are blacklisted by user
        if coldkey in self.blacklist_coldkeys:
            bt.logging.trace(f"Blacklisted recognized coldkey {coldkey} - with hotkey: {hotkey}")
            return True

        # Blacklist coldkeys that are blacklisted by user or by set of hotkeys
        if hotkey in self.blacklist_hotkeys:
            bt.logging.trace(f"Blacklisted recognized hotkey {hotkey}")
            # Add the coldkey attached to this hotkey in the blacklisted coldkeys
            self.blacklist_hotkeys.add(coldkey)
            return True

        # Blacklist coldkeys that are exploiters
        if coldkey in self.exploiters_coldkeys:
            bt.logging.trace(f"Blacklisted exploiter coldkey {coldkey} - with hotkey: {hotkey}")
            return True

        # Blacklist hotkeys that are exploiters
        if hotkey in self.exploiters_hotkeys:
            bt.logging.trace(f"Blacklisted exploiter hotkey {hotkey}")
            # Add the coldkey attached to this hotkey in the blacklisted coldkeys
            self.exploiters_hotkeys.add(coldkey)
            return True
        return False

    def get_valid_tensors(self, metagraph):
        tensors = []
        self.total_current_miners = 0
        for uid in metagraph.uids:
            neuron = metagraph.neurons[uid]

            if neuron.axon_info.ip != "0.0.0.0" and not self.is_blacklisted(neuron=neuron):
                self.total_current_miners += 1
                tensors.append(True)
            else:
                tensors.append(False)

        return tensors

    def get_valid_queryable(self):
        valid_queryable = []
        for uid in self.uids:
            neuron: bt.NeuronInfoLite = self.metagraph.neurons[uid]
            axon = self.metagraph.axons[uid]

            if neuron.axon_info.ip != "0.0.0.0" and not self.is_blacklisted(neuron=neuron):
                valid_queryable.append((uid, axon))

        return valid_queryable

    def get_queryable(self):
        queryable = self.get_valid_queryable()

        # Execute a cleanup of the stats and miner information if the miner has been dereg
        self.sync_miners_info(queryable)

        dict_filtered_axons = self.filter_axons(queryable_tuple_uids_axons=queryable)
        dict_filtered_axons = self.filter_axon_version(dict_filtered_axons=dict_filtered_axons)
        return dict_filtered_axons

    def get_valid_validator_hotkeys(self):
        valid_uids = []
        uids = self.metagraph.uids.tolist()
        for index, uid in enumerate(uids):
            if self.metagraph.total_stake[index] > validator_permit_stake:
                valid_uids.append(uid)
        valid_hotkeys = []
        for uid in valid_uids:
            neuron = self.subtensor.neuron_for_uid(uid, self.config.netuid)
            hotkey = neuron.hotkey
            valid_hotkeys.append(hotkey)
        return valid_hotkeys

    async def get_specs_wandb(self):
        """
        Retrieves hardware specifications from Wandb, updates the miner_details table,
        and checks for differences in GPU specs, logging changes only for allocated hotkeys.
        """
        bt.logging.info(f"💻 Hardware list of uids queried (Wandb): {list(self._queryable_uids.keys())}")

        # Retrieve specs from Wandb
        specs_dict = self.wandb.get_miner_specs(self._queryable_uids)

        # Fetch current specs from miner_details using the existing function
        current_miner_details = get_miner_details(self.db)

        # Compare and detect GPU spec changes for allocated hotkeys
        for hotkey, new_specs in specs_dict.values():
            if hotkey in self.allocated_hotkeys:  # Check if hotkey is allocated
                current_specs = current_miner_details.get(hotkey, {})
                current_gpu_specs = current_specs.get("gpu", {})
                new_gpu_specs = new_specs.get("gpu", {})

                # Extract the count values
                current_count = current_gpu_specs.get("count", 0)
                new_count = new_gpu_specs.get("count", 0)

                # Initialize names to None by default
                current_name = None
                new_name = None

                # Retrieve the current name if details are present and non-empty
                current_details = current_gpu_specs.get("details", [])
                if isinstance(current_details, list) and len(current_details) > 0:
                    current_name = current_details[0].get("name")

                # Retrieve the new name if details are present and non-empty
                new_details = new_gpu_specs.get("details", [])
                if isinstance(new_details, list) and len(new_details) > 0:
                    new_name = new_details[0].get("name")

                # Compare only count and name
                if current_count != new_count or current_name != new_name:
                    axon = None
                    for uid, axon_info in self._queryable_uids.items():
                        if axon_info.hotkey == hotkey:
                            axon = axon_info
                            break

                    if axon:
                        bt.logging.info(f"GPU specs changed for allocated hotkey {hotkey}:")
                        bt.logging.info(f"Old count: {current_count}, Old name: {current_name}")
                        bt.logging.info(f"New count: {new_count}, New name: {new_name}")
                        await self.deallocate_miner(axon, None)

        # Update the local db with the new data from Wandb
        update_miner_details(self.db, list(specs_dict.keys()), list(specs_dict.values()))

        # Log the hotkey and specs
        # bt.logging.info(f"✅ GPU specs per hotkey (Wandb):")
        # for hotkey, specs in specs_dict.values():
        #     gpu_info = specs.get("gpu", {})
        #     gpu_details = gpu_info.get("details", [])
        #     if gpu_details:
        #         gpu_name = gpu_details[0].get("name", "Unknown GPU")
        #         gpu_count = gpu_info.get("count", 1)  # Assuming 'count' reflects the number of GPUs
        #         bt.logging.info(f"{hotkey}: {gpu_name} x {gpu_count}")
        #     else:
        #         bt.logging.info(f"{hotkey}: No GPU details available")

        self.finalized_specs_once = True

    async def proof_of_gpu(self):
        """
        Perform Proof-of-GPU benchmarking on allocated miners without overlapping tests.
        Uses asyncio with ThreadPoolExecutor to test miners in parallel.
        """
        try:
            # Init miners to be tested
            self._queryable_uids = self.get_queryable()
            valid_validator_hotkeys = self.get_valid_validator_hotkeys()
            self.allocated_hotkeys = self.wandb.get_allocated_hotkeys(valid_validator_hotkeys, True)

            # Settings
            merkle_proof = self.config_data["merkle_proof"]
            retry_limit = merkle_proof.get("pog_retry_limit",30)
            retry_interval = merkle_proof.get("pog_retry_interval",75)
            num_workers = merkle_proof.get("max_workers",32)
            max_delay = merkle_proof.get("max_random_delay",1200)

            # Random delay for PoG
            delay = random.uniform(0, max_delay)  # Random delay
            bt.logging.info(f"💻⏳ Scheduled Proof-of-GPU task to start in {delay:.2f} seconds.")
            await asyncio.sleep(delay)

            bt.logging.info(f"💻 Starting Proof-of-GPU benchmarking for uids: {list(self._queryable_uids.keys())}")
            # Shared dictionary to store results
            self.results = {}
            # Dictionary to track retry counts
            retry_counts = defaultdict(int)
            # Queue of miners to process
            queue = asyncio.Queue()

            # Initialize the queue with initial miners
            for i in range(0, len(self.uids), self.validator_challenge_batch_size):
                for _uid in self.uids[i : i + self.validator_challenge_batch_size]:
                    try:
                        axon = self._queryable_uids[_uid]
                        if axon.hotkey in self.allocated_hotkeys:
                            bt.logging.info(f"Skipping allocated miner: {axon.hotkey}")
                            continue  # skip this miner since it's allocated
                        await queue.put(axon)
                    except KeyError:
                        continue

            # Initialize a single Lock for thread-safe updates to results
            results_lock = asyncio.Lock()

            async def worker():
                while True:
                    try:
                        axon = await queue.get()
                    except asyncio.CancelledError:
                        break
                    hotkey = axon.hotkey
                    try:
                        # Set a timeout for the GPU test
                        timeout = 300  # e.g., 5 minutes
                        # Define a synchronous helper function to run the asynchronous test_miner_gpu
                        # This is required because run_in_executor expects a synchronous callable.
                        def run_test_miner_gpu():
                            # Run the async test_miner_gpu function and wait for its result.
                            future = asyncio.run_coroutine_threadsafe(self.test_miner_gpu(axon, self.config_data), self.loop)
                            return future.result()

                        # Submit the run_test_miner_gpu function to a thread pool executor.
                        # The asyncio.wait_for is used to enforce a timeout for the overall operation.
                        result = await asyncio.wait_for(
                            asyncio.get_running_loop().run_in_executor(
                                self.executor, run_test_miner_gpu
                            ),
                            timeout=timeout
                        )
                        if result[1] is not None and result[2] > 0:
                            async with results_lock:
                                self.results[hotkey] = {
                                    "gpu_name": result[1],
                                    "num_gpus": result[2]
                                }
                            update_pog_stats(self.db, hotkey, result[1], result[2])
                        else:
                            raise RuntimeError("GPU test failed")
                    except asyncio.TimeoutError:
                        bt.logging.warning(f"⏳ Timeout while testing {hotkey}. Retrying...")
                        retry_counts[hotkey] += 1
                        if retry_counts[hotkey] < retry_limit:
                            bt.logging.info(f"🔄 {hotkey}: Retrying miner -> (Attempt {retry_counts[hotkey]})")
                            await asyncio.sleep(retry_interval)
                            await queue.put(axon)
                        else:
                            bt.logging.info(f"❌ {hotkey}: Miner failed after {retry_limit} attempts (Timeout).")
                            update_pog_stats(self.db, hotkey, None, None)
                    except Exception as e:
                        bt.logging.trace(f"Exception in worker for {hotkey}: {e}")
                        retry_counts[hotkey] += 1
                        if retry_counts[hotkey] < retry_limit:
                            bt.logging.info(f"🔄 {hotkey}: Retrying miner -> (Attempt {retry_counts[hotkey]})")
                            await asyncio.sleep(retry_interval)
                            await queue.put(axon)
                        else:
                            bt.logging.info(f"❌ {hotkey}: Miner failed after {retry_limit} attempts.")
                            update_pog_stats(self.db, hotkey, None, None)
                    finally:
                        queue.task_done()

            # Number of concurrent workers
            # Determine a safe default number of workers
            cpu_cores = os.cpu_count() or 1
            safe_max_workers = min((cpu_cores + 4)*4, num_workers)

            workers = [asyncio.create_task(worker()) for _ in range(safe_max_workers)]
            bt.logging.trace(f"Started {safe_max_workers} worker tasks for Proof-of-GPU benchmarking.")

            # Wait until the queue is fully processed
            await queue.join()

            # Cancel worker tasks
            for w in workers:
                w.cancel()
            # Wait until all worker tasks are cancelled
            await asyncio.gather(*workers, return_exceptions=True)

            bt.logging.success(f"✅ Proof-of-GPU benchmarking completed.")
            return self.results
        except Exception as e:
            bt.logging.info(f"❌ Exception in proof_of_gpu: {e}\n{traceback.format_exc()}")

    def on_gpu_task_done(self, task):
        try:
            results = task.result()
            bt.logging.trace(f"Proof-of-GPU Results: {results}")
            self.gpu_task = None  # Reset the task reference
            self.sync_scores()

        except Exception as e:
            bt.logging.error(f"Proof-of-GPU task failed: {e}")
            self.gpu_task = None

    async def test_miner_gpu(self, axon, config_data):
        """
        Allocate, test, and deallocate a single miner.

        :return: Tuple of (miner_hotkey, gpu_name, num_gpus)
        """
        allocation_status = False
        miner_info = None
        host = None  # Initialize host variable
        hotkey = axon.hotkey
        bt.logging.trace(f"{hotkey}: Starting miner test.")

        try:
            # Step 0: Init
            gpu_data = config_data["gpu_performance"]
            gpu_tolerance_pairs = gpu_data.get("gpu_tolerance_pairs", {})
            # Extract Merkle Proof Settings
            merkle_proof = config_data["merkle_proof"]
            time_tol = merkle_proof.get("time_tolerance",5)
            # Extract miner_script path
            miner_script_path = merkle_proof["miner_script_path"]

            # Step 1: Allocate Miner
            # Generate RSA key pair
            private_key, public_key = rsa.generate_key_pair()
            allocation_response = await self.allocate_miner(axon, private_key, public_key)
            if not allocation_response:
                bt.logging.info(f"🌀 {hotkey}: Busy or not allocatable.")
                return (hotkey, None, 0)
            allocation_status = True
            miner_info = allocation_response
            host = miner_info['host']
            bt.logging.trace(f"{hotkey}: Allocated Miner for testing.")

            # Step 2: Connect via SSH
            ssh_client = paramiko.SSHClient()
            ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            bt.logging.trace(f"{hotkey}: Connect to Miner via SSH.")
            ssh_client.connect(host, port=miner_info.get('port', 22), username=miner_info['username'], password=miner_info['password'], timeout=10)
            if not (ssh_client):
                ssh_client.close()
                bt.logging.info(f"{hotkey}: SSH connection failed.")
                return (hotkey, None, -1)
            bt.logging.trace(f"{hotkey}: Connected to Miner via SSH.")

            # Step 3: Hash Check
            local_hash = compute_script_hash(miner_script_path)
            bt.logging.trace(f"{hotkey}: [Step 1] Local script hash computed successfully.")
            bt.logging.trace(f"{hotkey}: Local Hash: {local_hash}")
            remote_hash = send_script_and_request_hash(ssh_client, miner_script_path)
            if local_hash != remote_hash:
                bt.logging.info(f"{hotkey}: [Integrity Check] FAILURE: Hash mismatch detected.")
                raise ValueError(f"{hotkey}: Script integrity verification failed.")

            # Step 4: Get GPU info NVIDIA from the remote miner
            bt.logging.trace(f"{hotkey}: [Step 4] Retrieving GPU information (NVIDIA driver) from miner...")
            gpu_info = get_remote_gpu_info(ssh_client)
            num_gpus_reported = gpu_info["num_gpus"]
            gpu_name_reported = gpu_info["gpu_names"][0] if num_gpus_reported > 0 else None
            bt.logging.trace(f"{hotkey}: [Step 4] Reported GPU Information:")
            if num_gpus_reported > 0:
                bt.logging.trace(f"{hotkey}: Number of GPUs: {num_gpus_reported}")
                bt.logging.trace(f"{hotkey}: GPU Type: {gpu_name_reported}")
            if num_gpus_reported <= 0:
                bt.logging.info(f"{hotkey}: No GPUs detected.")
                raise ValueError("No GPUs detected.")

            # Step 5: Run the benchmarking mode
            bt.logging.info(f"💻 {hotkey}: Executing benchmarking mode.")
            bt.logging.trace(f"{hotkey}: [Step 5] Executing benchmarking mode on the miner...")
            execution_output = execute_script_on_miner(ssh_client, mode='benchmark')
            bt.logging.trace(f"{hotkey}: [Step 5] Benchmarking completed.")
            # Parse the execution output
            num_gpus, vram, size_fp16, time_fp16, size_fp32, time_fp32 = parse_benchmark_output(execution_output)
            bt.logging.trace(f"{hotkey}: [Benchmark Results] Detected {num_gpus} GPU(s) with {vram} GB unfractured VRAM.")
            bt.logging.trace(f"{hotkey}: FP16 - Matrix Size: {size_fp16}, Execution Time: {time_fp16} s")
            bt.logging.trace(f"{hotkey}: FP32 - Matrix Size: {size_fp32}, Execution Time: {time_fp32} s")
            # Calculate performance metrics
            fp16_tflops = (2 * size_fp16 ** 3) / time_fp16 / 1e12
            fp32_tflops = (2 * size_fp32 ** 3) / time_fp32 / 1e12
            bt.logging.trace(f"{hotkey}: [Performance Metrics] Calculated TFLOPS:")
            bt.logging.trace(f"{hotkey}: FP16: {fp16_tflops:.2f} TFLOPS")
            bt.logging.trace(f"{hotkey}: FP32: {fp32_tflops:.2f} TFLOPS")
            gpu_name = identify_gpu(fp16_tflops, fp32_tflops, vram, gpu_data, gpu_name_reported, gpu_tolerance_pairs)
            bt.logging.trace(f"{hotkey}: [GPU Identification] Based on performance: {gpu_name}")

            # Step 6: Run the Merkle proof mode
            bt.logging.trace(f"{hotkey}: [Step 6] Initiating Merkle Proof Mode.")
            # Step 1: Send seeds and execute compute mode
            n = adjust_matrix_size(vram, element_size=4, buffer_factor=0.10)
            seeds = get_random_seeds(num_gpus)
            send_seeds(ssh_client, seeds, n)
            bt.logging.trace(f"{hotkey}: [Step 6] Compute mode executed on miner - Matrix Size: {n}")
            start_time = time.time()
            execution_output = execute_script_on_miner(ssh_client, mode='compute')
            end_time = time.time()
            elapsed_time = end_time - start_time
            bt.logging.trace(f"{hotkey}: Compute mode execution time: {elapsed_time:.2f} seconds.")
            # Parse the execution output
            root_hashes_list, gpu_timings_list = parse_merkle_output(execution_output)
            bt.logging.trace(f"{hotkey}: [Merkle Proof] Root hashes received from GPUs:")
            for gpu_id, root_hash in root_hashes_list:
                bt.logging.trace(f"{hotkey}: GPU {{gpu_id}}: {{root_hash}}")

            # Calculate total times
            total_multiplication_time = 0.0
            total_merkle_tree_time = 0.0
            num_gpus = len(gpu_timings_list)
            for _, timing in gpu_timings_list:
                total_multiplication_time += timing.get('multiplication_time', 0.0)
                total_merkle_tree_time += timing.get('merkle_tree_time', 0.0)
            average_multiplication_time = total_multiplication_time / num_gpus if num_gpus > 0 else 0.0
            average_merkle_tree_time = total_merkle_tree_time / num_gpus if num_gpus > 0 else 0.0
            bt.logging.trace(f"{hotkey}: Average Matrix Multiplication Time: {average_multiplication_time:.4f} seconds")
            bt.logging.trace(f"{hotkey}: Average Merkle Tree Time: {average_merkle_tree_time:.4f} seconds")

            timing_passed = False
            if elapsed_time < time_tol + num_gpus * time_fp32 and average_multiplication_time < time_fp32:
                timing_passed = True

            # Step 7: Verify merkle proof
            root_hashes = {gpu_id: root_hash for gpu_id, root_hash in root_hashes_list}
            gpu_timings = {gpu_id: timing for gpu_id, timing in gpu_timings_list}
            n = gpu_timings[0]['n']  # Assuming same n for all GPUs
            indices = {}
            num_indices = 1
            for gpu_id in range(num_gpus):
                indices[gpu_id] = [(np.random.randint(0, n), np.random.randint(0, n)) for _ in range(num_indices)]
            send_challenge_indices(ssh_client, indices)
            execution_output = execute_script_on_miner(ssh_client, mode='proof')
            bt.logging.trace(f"{hotkey}: [Merkle Proof] Proof mode executed on miner.")
            responses = receive_responses(ssh_client, num_gpus)
            bt.logging.trace(f"{hotkey}: [Merkle Proof] Responses received from miner.")

            verification_passed = verify_responses(seeds, root_hashes, responses, indices, n)
            if verification_passed and timing_passed:
                bt.logging.info(f"✅ {hotkey}: GPU Identification: Detected {num_gpus} x {gpu_name} GPU(s)")
                return (hotkey, gpu_name, num_gpus)
            else:
                bt.logging.info(f"⚠️  {hotkey}: GPU Identification: Aborted due to verification failure")
                return (hotkey, None, 0)

        except Exception as e:
            bt.logging.info(f"❌ {hotkey}: Error testing Miner: {e}")
            return (hotkey, None, 0)

        finally:
            if allocation_status and miner_info:
                await self.deallocate_miner(axon, public_key)

    async def allocate_miner(self, axon, private_key, public_key):
        """
        Allocate a miner by querying the allocator.

        :param uid: Unique identifier for the axon.
        :param axon: Axon object containing miner details.
        :return: Dictionary with miner details if successful, None otherwise.
        """
        try:

            # Define device requirements (customize as needed)
            device_requirement = {"cpu": {"count": 1}, "gpu": {}, "hard_disk": {"capacity": 1073741824}, "ram": {"capacity": 1073741824}, "testing": True}
            device_requirement["gpu"] = {"count": 1, "capacity": 0, "type": ""}

            docker_requirement = {
                "base_image": "pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime",
            }
            async with self.dendrite as dendrite:
                # Simulate an allocation query with Allocate
                check_allocation = await dendrite(
                    axon,
                    Allocate(timeline=1, device_requirement=device_requirement, checking=True),
                    timeout=30,
                    )
                if check_allocation and check_allocation ["status"] is True:
                    response = await dendrite(
                        axon,
                        Allocate(
                            timeline=1,
                            device_requirement=device_requirement,
                            checking=False,
                            public_key=public_key,
                            docker_requirement=docker_requirement,
                        ),
                        timeout=30,
                    )
                    if response and response.get("status") is True:
                        bt.logging.trace(f"Successfully allocated miner {axon.hotkey}")
                        decrypted_info_str = rsa.decrypt_data(
                            private_key.encode("utf-8"),
                            base64.b64decode(response["info"]),
                        )
                        info = json.loads(decrypted_info_str)

                        miner_info = {
                            'host': axon.ip,
                            'port': info['port'],
                            'username': info['username'],
                            'password': info['password'],
                        }
                        return miner_info
                    else:
                        bt.logging.trace(f"{axon.hotkey}: Miner allocation failed or no response received.")
                        return None
                else:
                    bt.logging.trace(f"{axon.hotkey}: Miner aready allocated or no response received.")
                    return None

        except ConnectionRefusedError as e:
            bt.logging.error(f"{axon.hotkey}: Connection refused during miner allocation: {e}")
            return None
        except Exception as e:
            bt.logging.trace(f"{axon.hotkey}: Exception during miner allocation for: {e}")
            return None

    async def deallocate_miner(self, axon, public_key):
        """
        Deallocate a miner by sending a deregistration query.

        :param axon: Axon object containing miner details.
        :param public_key: Public key of the miner; if None, it will be retrieved from the database.
        """
        if not public_key:
            try:
                # Instantiate the connection to the database and retrieve miner details
                db = ComputeDb()
                cursor = db.get_cursor()

                cursor.execute(
                    "SELECT details, hotkey FROM allocation WHERE hotkey = ?",
                    (axon.hotkey,)
                )
                row = cursor.fetchone()

                if row:
                    info = json.loads(row[0])  # Parse JSON string from the 'details' column
                    public_key = info.get("regkey")
            except Exception as e:
                bt.logging.trace(f"{axon.hotkey}: Missing public key: {e}")

        try:
            retry_count = 0
            max_retries = 3
            allocation_status = True

            while allocation_status and retry_count < max_retries:
                try:
                    async with self.dendrite as dendrite:
                        # Send deallocation query
                        deregister_response = await dendrite(
                            axon,
                            Allocate(
                                timeline=0,
                                checking=False,
                                public_key=public_key,
                            ),
                            timeout=60,
                        )

                        if deregister_response and deregister_response.get("status") is True:
                            allocation_status = False
                            bt.logging.trace(f"Deallocated miner {axon.hotkey}")
                        else:
                            retry_count += 1
                            bt.logging.trace(
                                f"{axon.hotkey}: Failed to deallocate miner. "
                                f"(attempt {retry_count}/{max_retries})"
                            )
                            if retry_count >= max_retries:
                                bt.logging.trace(f"{axon.hotkey}: Max retries reached for deallocating miner.")
                            await asyncio.sleep(5)
                except Exception as e:
                    retry_count += 1
                    bt.logging.trace(
                        f"{axon.hotkey}: Error while trying to deallocate miner. "
                        f"(attempt {retry_count}/{max_retries}): {e}"
                    )
                    if retry_count >= max_retries:
                        bt.logging.trace(f"{axon.hotkey}: Max retries reached for deallocating miner.")
                    await asyncio.sleep(5)
        except Exception as e:
            bt.logging.trace(f"{axon.hotkey}: Unexpected error during deallocation: {e}")

    def set_weights(self):
        # Remove all negative scores and attribute them 0.
        self.scores[self.scores < 0] = 0
        # Normalize the scores into weights
        weights: torch.FloatTensor = torch.nn.functional.normalize(self.scores, p=1.0, dim=0).float()
        bt.logging.info(f"🏋️ Weight of miners : {weights.tolist()}")
        # This is a crucial step that updates the incentive mechanism on the Bittensor blockchain.
        # Miners with higher scores (or weights) receive a larger share of TAO rewards on this subnet.
        result = self.subtensor.set_weights(
            netuid=self.config.netuid,  # Subnet to set weights on.
            wallet=self.wallet,  # Wallet to sign set weights using hotkey.
            uids=self.uids,  # Uids of the miners to set weights for.
            weights=weights,  # Weights to set for the miners.
            version_key=__version_as_int__,
            wait_for_inclusion=False,
        ) # return type: tuple[bool, str]
        if isinstance(result, tuple) and result and isinstance(result[0], bool) and result[0]:
            bt.logging.info(result)
            bt.logging.success("✅ Successfully set weights.")
        else:
            bt.logging.error(result)
            bt.logging.error("❌ Failed to set weights.")

    def next_info(self, cond, next_block):
        if cond:
            return calculate_next_block_time(self.current_block, next_block)
        else:
            return None

    async def start(self):
        """The Main Validation Loop"""
        self.loop = asyncio.get_running_loop()

        # Step 5: Perform queries to miners, scoring, and weight
        block_next_pog = 1
        block_next_sync_status = 1
        block_next_set_weights = self.current_block + weights_rate_limit
        block_next_hardware_info = 1
        block_next_miner_checking = 1

        time_next_pog = None
        time_next_sync_status = None
        time_next_set_weights = None
        time_next_hardware_info = None

        bt.logging.info("Starting validator loop.")
        while True:
            try:
                self.sync_local()

                if self.current_block not in self.blocks_done:
                    self.blocks_done.add(self.current_block)

                    time_next_pog = self.next_info(not block_next_pog == 1, block_next_pog)
                    time_next_sync_status = self.next_info(not block_next_sync_status == 1, block_next_sync_status)
                    time_next_set_weights = self.next_info(not block_next_set_weights == 1, block_next_set_weights)
                    time_next_hardware_info = self.next_info(
                        not block_next_hardware_info == 1 and self.validator_perform_hardware_query, block_next_hardware_info
                    )

                    # Perform proof of GPU (pog) queries
                    if self.current_block % block_next_pog == 0 or block_next_pog < self.current_block:
                        block_next_pog = self.current_block + 360

                        if self.gpu_task is None or self.gpu_task.done():
                            # Schedule proof_of_gpu as a background task
                            self.gpu_task = asyncio.create_task(self.proof_of_gpu())
                            self.gpu_task.add_done_callback(self.on_gpu_task_done)
                        else:
                            bt.logging.info("Proof-of-GPU task is already running.")

                    # Perform specs queries
                    if (self.current_block % block_next_hardware_info == 0 and self.validator_perform_hardware_query) or (
                        block_next_hardware_info < self.current_block and self.validator_perform_hardware_query
                    ):
                        block_next_hardware_info = self.current_block + 150  # 150 -> ~ every 30 minutes

                        if not hasattr(self, "_queryable_uids"):
                            self._queryable_uids = self.get_queryable()

                        # self.loop.run_in_executor(None, self.execute_specs_request) replaced by wandb query.
                        await self.get_specs_wandb()

                    # Perform miner checking
                    if self.current_block % block_next_miner_checking == 0 or block_next_miner_checking < self.current_block:
                        # Next block the validators will do port checking again.
                        block_next_miner_checking = self.current_block + 50  # 300 -> every 60 minutes

                        # Filter axons with stake and ip address.
                        self._queryable_uids = self.get_queryable()

                        # self.sync_checklist()

                    if self.current_block % block_next_sync_status == 0 or block_next_sync_status < self.current_block:
                        block_next_sync_status = self.current_block + 25  # ~ every 5 minutes
                        self.sync_status()

                        # Log chain data to wandb
                        chain_data = {
                            "Block": self.current_block,
                            "Stake": float(self.metagraph.S[self.validator_subnet_uid]),
                            "Rank": float(self.metagraph.R[self.validator_subnet_uid]),
                            "vTrust": float(self.metagraph.validator_trust[self.validator_subnet_uid]),
                            "Emission": float(self.metagraph.E[self.validator_subnet_uid]),
                        }
                        self.wandb.log_chain_data(chain_data)

                    # Periodically update the weights on the Bittensor blockchain, ~ every 20 minutes
                    if self.current_block - self.last_updated_block > weights_rate_limit:
                        block_next_set_weights = self.current_block + weights_rate_limit
                        self.sync_scores()
                        self.set_weights()
                        self.last_updated_block = self.current_block
                        self.blocks_done.clear()
                        self.blocks_done.add(self.current_block)

                bt.logging.info(
                    (
                        f"Block:{self.current_block} | "
                        f"Stake:{self.metagraph.S[self.validator_subnet_uid]} | "
                        f"Rank:{self.metagraph.R[self.validator_subnet_uid]} | "
                        f"vTrust:{self.metagraph.validator_trust[self.validator_subnet_uid]} | "
                        f"Emission:{self.metagraph.E[self.validator_subnet_uid]} | "
                        f"next_pog: #{block_next_pog} ~ {time_next_pog} | "
                        f"sync_status: #{block_next_sync_status} ~ {time_next_sync_status} | "
                        f"set_weights: #{block_next_set_weights} ~ {time_next_set_weights} | "
                        f"wandb_info: #{block_next_hardware_info} ~ {time_next_hardware_info} |"
                    )
                )
                await asyncio.sleep(1)

            # If we encounter an unexpected error, log it for debugging.
            except RuntimeError as e:
                bt.logging.error(e)
                traceback.print_exc()

            # If the user interrupts the program, gracefully exit.
            except KeyboardInterrupt:
                self.db.close()
                bt.logging.success("Keyboard interrupt detected. Exiting validator.")
                exit()


def main():
    """
    Main function to run the neuron.

    This function initializes and runs the neuron. It handles the main loop, state management, and interaction
    with the Bittensor network.
    """
    validator = Validator()
    asyncio.run(validator.start())


if __name__ == "__main__":
    main()
