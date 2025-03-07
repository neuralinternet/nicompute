# The MIT License (MIT)
# Copyright © 2023 GitPhantomman

# Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
# documentation files (the “Software”), to deal in the Software without restriction, including without limitation
# the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software,
# and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all copies or substantial portions of
# the Software.

# THE SOFTWARE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO
# THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
# THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
# DEALINGS IN THE SOFTWARE.
# Step 1: Import necessary libraries and modules

import bittensor as bt
import base64
import os
from io import BytesIO

from neurons.Miner.container import kill_container, run_container, check_container
from neurons.Miner.schedule import start


# Register for given timeline and device_requirement
def register_allocation(timeline, device_requirement, public_key, docker_requirement: dict):
    try:
        kill_status = kill_container()

        # Extract requirements from device_requirement and format them
        cpu_count = device_requirement["cpu"]["count"]  # e.g 2
        cpu_assignment = "0-" + str(cpu_count - 1)  # e.g 0-1
        if cpu_count == 1:
            cpu_assignment = "0"
        ram_capacity = device_requirement["ram"]["capacity"]  # e.g 5g
        hard_disk_capacity = device_requirement["hard_disk"]["capacity"]  # e.g 100g
        testing = device_requirement.get("testing", False)
        if not device_requirement["gpu"]:
            gpu_capacity = 0
        else:
            gpu_capacity = device_requirement["gpu"]["capacity"]  # e.g all

        cpu_usage = {"assignment": cpu_assignment}
        gpu_usage = {"capacity": gpu_capacity}
        ram_usage = {"capacity": str(int(ram_capacity / 1073741824)) + "g"}
        hard_disk_usage = {"capacity": str(int(hard_disk_capacity / 1073741824)) + "g"}

        run_status = run_container(cpu_usage, ram_usage, hard_disk_usage, gpu_usage, public_key, docker_requirement, testing)

        if run_status["status"]:
            bt.logging.info("Successfully allocated container.")

        # Kill container when it meets timeline
        start(timeline)
        return run_status
    
    except Exception as e:
        bt.logging.info(f"Error allocating container {e}")
    return {"status": False}
def force_deregister():
    try:
        file_path = 'allocation_key'
        # Attempt to read the allocation key just for logging purposes (can be omitted if not needed)
        if os.path.exists(file_path):
            with open(file_path, 'r') as file:
                _ = file.read()
        
        # Force kill container without public key verification
        kill_status = kill_container()
        if kill_status:
            # Clear the allocation key file after successful de-allocation
            with open(file_path, 'w') as file:
                file.truncate(0)
            bt.logging.info("Forcefully de-allocated container.")
            return {"status": True}
        else:
            return {"status": False}
    except Exception as e:
        bt.logging.info(f"Error force de-allocating container: {e}")
        return {"status": False}

# Deregister allocation
def deregister_allocation(public_key):
    try:
        file_path = 'allocation_key'
        # Open the file in read mode ('r') and read the data
        with open(file_path, 'r') as file:
            allocation_key_encoded = file.read()

        # Decode the base64-encoded public key from the file
        allocation_key = base64.b64decode(allocation_key_encoded).decode('utf-8')

        # Kill container when the request is valid
        if allocation_key.strip() == public_key.strip():
            kill_status = kill_container()
            if kill_status:
                # Remove the key from the file after successful deallocation
                with open(file_path, 'w') as file:
                    file.truncate(0)  # Clear the file
                
                bt.logging.info("Successfully de-allocated container.")
                return {"status": True}
            else:
                return {"status": False}
        else:
            bt.logging.info(f"Permission denied.")
            return {"status": False}

    except Exception as e:
        bt.logging.info(f"Error de-allocating container {e}")
        return {"status": False}


# Check if miner is acceptable
def check_allocation(timeline, device_requirement):
    # Check if miner is already allocated
    if check_container() is True:
        return {"status": False}
    # Check if there is enough device
    return {"status": True}


def check_if_allocated(public_key):
    try:
        file_path = 'allocation_key'
        # Check if the file exists
        if not os.path.exists(file_path):
            return {"status": False}

        # Open the file in read mode ('r') and read the data
        with open(file_path, 'r') as file:
            allocation_key_encoded = file.read()

        # Check if the key is empty
        if not allocation_key_encoded.strip():
            return {"status": False}

        # Decode the base64-encoded public key from the file
        allocation_key = base64.b64decode(allocation_key_encoded).decode('utf-8')

        # Compare the decoded key with the public key
        if allocation_key.strip() != public_key.strip():
            return {"status": False}

        # Check if the container is running
        if not check_container():
            return {"status": False}

        # All checks passed, return True
        return {"status": True}
    except Exception as e:
        # Handle any exceptions that occur
        # Log the exception or handle it as needed
        return {"status": False}