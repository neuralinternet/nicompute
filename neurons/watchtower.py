import argparse
import os
import json
import asyncio
import threading
import time
import bittensor as bt
from compute import validator_permit_stake
from compute.axon import ComputeSubnetSubtensor
from compute.axon import ComputeSubnetAxon, ComputeSubnetSubtensor
from compute.wandb.wandb import ComputeWandb  # Importing ComputeWandb
from compute.protocol import POG, Allocate
class watchtower:
    def __init__(self, config):
        self.config = config
        self.metagraph = self.get_metagraph() # Retrieve metagraph state
        self.subtensor = ComputeSubnetSubtensor(config=self.config)
        self.validators = self.get_valid_validator_hotkeys()
        self.wallet = bt.wallet(config=self.config)
        self.wandb = ComputeWandb(self.config, self.wallet, os.path.basename(__file__))
    def get_metagraph(self):
        """Retrieves the metagraph from subtensor."""
        subtensor = bt.subtensor(config=self.config)
        return subtensor.metagraph(self.config.netuid)
    def get_metagraph_uids(self):
        return self.metagraph.uids.tolist()
    
    def get_valid_validator_hotkeys(self):
        valid_uids = []
        for index, uid in enumerate(self.get_metagraph_uids()):
            if self.metagraph.total_stake[index] > validator_permit_stake:
                valid_uids.append(uid)
        valid_hotkeys = []
        for uid in valid_uids:
            neuron = self.subtensor.neuron_for_uid(uid, self.config.netuid)
            hotkey = neuron.hotkey
            valid_hotkeys.append(hotkey)
        return valid_hotkeys
    
    def get_queryable(self):
        hotkeys = self.metagraph.hotkeys
        validators_hotkeys = self.get_valid_validator_hotkeys()
        miners = [hotkey for hotkey in hotkeys if hotkey not in validators_hotkeys]
        return miners
    
    async def exchange_miner_key_auth(self, miner_axon, auth_key):
        max_retries = 3
        for attempt in range(1, max_retries + 1):
            dendrite = bt.dendrite(wallet=self.wallet)
            try:
                authority_exchange = {"authority_exchange": auth_key}
                await dendrite(miner_axon, Allocate(authority_exchange=authority_exchange), timeout=30)
                return True
            except Exception as e:
                bt.logging.error(f"Attempt {attempt}: Failed to exchange miner key auth with {miner_axon.hotkey} - {e}")
                if attempt < max_retries:
                    await asyncio.sleep(3)
                else:
                    return False
            finally:
                await dendrite.aclose_session()
    
    async def exchange_miners_key_auth_exchange(self,miners_keys, auth_key):
        axons = self.metagraph.axons
        axons = [axons for axon in axons if axon.hotkey in miners_keys]
        for axon in axons:
            await self.exchange_miner_key_auth(axon, auth_key)

    async def give_validator_pog_access(self,validator_hotkey):
        max_retries = 3
        for attempt in range(1, max_retries + 1):
            dendrite = None
            try:
                validator_axon = self.metagraph.axon_for_hotkey(validator_hotkey)
                dendrite = bt.dendrite(wallet=self.wallet)
                await dendrite(validator_axon, POG(pog=True), timeout=30)
                return True
            except Exception as e:
                bt.logging.error(f"Attempt {attempt}: Failed to give validator pog access {validator_hotkey} {e}")
                if attempt < max_retries:
                    await asyncio.sleep(10)
                else:
                    bt.logging.error(f"All {max_retries} attempts failed for validator {validator_hotkey}")
                return False
            finally:
                if dendrite is not None:
                    await dendrite.aclose_session()

    async def pog_orchastractor(self):
        miners_hotkeys = self.get_queryable()
        validators_hotkeys = self.get_valid_validator_hotkeys()
        allocated_hotkeys = self.wandb.get_allocated_hotkeys(validators_hotkeys, True)
        miners_hotkeys = [hotkey for hotkey in miners_hotkeys if hotkey not in allocated_hotkeys and hotkey not in validators_hotkeys]
        # give 5 minutes for every validator to complete the proof of work
        for hotkey in validators_hotkeys:
            await self.exchange_miners_key_auth_exchange(miners_hotkeys, hotkey)
            res = await self.give_validator_pog_access(hotkey)
            if not res:
                bt.logging.error(f"Failed to give validator {hotkey} pog access after 3 attempts")
                # move to the next miner
                continue
            # wait for 5 minutes
            await asyncio.sleep(300)
def get_config():
    """Set up configuration using argparse."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--netuid", type=int, default=1, help="The chain subnet uid.")
    bt.subtensor.add_args(parser)
    bt.logging.add_args(parser)
    bt.wallet.add_args(parser)
    config = bt.config(parser)
    # Ensure the logging directory exists
    config.full_path = os.path.expanduser( "{}/{}/{}/netuid{}/{}".format( config.logging.logging_dir, config.wallet.name, config.wallet.hotkey, config.netuid, "validator",))
    return config

def main():
    wt = watchtower(get_config())
    while True:
        asyncio.run(wt.pog_orchastractor())
        time.sleep(100)
if __name__ == "__main__":
    main()