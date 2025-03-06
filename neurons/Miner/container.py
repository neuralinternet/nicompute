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

import base64
import json
import os
import secrets
import string
import subprocess
import psutil

import docker
from io import BytesIO
import sys
from docker.types import DeviceRequest
from compute import __version_as_int__
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(parent_dir)

import RSAEncryption as rsa

import bittensor as bt

# XXX: global constants should be capitalized or (better) avoided
image_name = "ssh-image"  # Docker image name
image_name_base = "ssh-image-base"  # Docker image name
container_name = "ssh-container"  # Docker container name
container_name_test = "ssh-test-container"
volume_name = "ssh-volume"  # Docker volumne name
volume_path = "/tmp"  # Path inside the container where the volume will be mounted
ssh_port = 4444  # Port to map SSH service on the host


# Initialize Docker client
def get_docker():
    client = docker.from_env()
    containers = client.containers.list(all=True)
    return client, containers


# Kill the currently running container
def kill_container():
    try:
        client, containers = get_docker()
        running_container_test = None
        running_container = None

        # Check for container_name_test first
        for container in containers:
            if container.name == container_name_test:
                running_container_test = container
                break

        # If container_name_test is not found, check for container_name
        if not running_container_test:
            for container in containers:
                if container.name == container_name:
                    running_container = container
                    break

        # Kill and remove the appropriate container
        if running_container_test:
            if running_container_test.status == "running":
                running_container_test.exec_run(cmd="kill -15 1")
                running_container_test.wait()
            running_container_test.remove()
            bt.logging.info(f"Container '{container_name_test}' was killed successfully")
        elif running_container:
            if running_container.status == "running":
                running_container.exec_run(cmd="kill -15 1")
                running_container.wait()
            running_container.remove()
            bt.logging.info(f"Container '{container_name}' was killed successfully")
        else:
            bt.logging.info("No running container found.")

        # Remove all dangling images
        client.images.prune(filters={"dangling": True})

        return True
    except Exception as e:
        bt.logging.info(f"Error killing container: {e}")
        return False

# Run a new docker container with the given docker_name, image_name and device information
def run_container(cpu_usage, ram_usage, hard_disk_usage, gpu_usage, public_key, docker_requirement: dict, testing: bool):
    try:
        client, containers = get_docker()
        # Configuration
        password = password_generator(10)
        cpu_assignment = cpu_usage["assignment"]  # e.g : 0-1
        ram_limit = ram_usage["capacity"]  # e.g : 5g
        hard_disk_capacity = hard_disk_usage["capacity"]  # e.g : 100g
        gpu_capacity = gpu_usage["capacity"]  # e.g : all

        docker_image = docker_requirement.get("base_image")
        # XXX: ^^ this is ignored in favor of ssh-image-base
        # the code needs some cleaning up (out of scope for the hotfix)
        docker_volume = docker_requirement.get("volume_path")
        docker_ssh_key = docker_requirement.get("ssh_key")
        docker_ssh_port = docker_requirement.get("ssh_port")
        docker_appendix = docker_requirement.get("dockerfile")

        # ensure base image exists
        build_sample_container()  # this is a no-op when already built

        bt.logging.info(f"Image: {image_name_base}")

        if docker_appendix is None or docker_appendix == "":
            docker_appendix = "echo 'Hello World!'"

        # Calculate 90% of free memory for shm_size
        available_memory = psutil.virtual_memory().available
        shm_size_gb = int(0.9 * available_memory / (1024**3))  # Convert to GB
        bt.logging.trace(f"Allocating {shm_size_gb}GB to /dev/shm")

        dockerfile_content = f"""
        FROM {image_name_base}:latest

        # Run additional Docker appendix commands
        RUN {docker_appendix}

        # Setup SSH authorized keys
        RUN mkdir -p /root/.ssh/ && echo '{docker_ssh_key}' > /root/.ssh/authorized_keys && chmod 600 /root/.ssh/authorized_keys
        RUN echo 'root:{password}' | chpasswd

        """

        # Ensure the tmp directory exists within the current directory
        tmp_dir_path = os.path.join('.', 'tmp')
        os.makedirs(tmp_dir_path, exist_ok=True)

        # Path for the Dockerfile within the tmp directory
        dockerfile_path = os.path.join(tmp_dir_path, 'dockerfile')
        with open(dockerfile_path, "w") as dockerfile:
            dockerfile.write(dockerfile_content)

        # Build the Docker image and remove the intermediate containers
        client.images.build(path=os.path.dirname(dockerfile_path), dockerfile=os.path.basename(dockerfile_path), tag=image_name,
                            rm=True)
        # Create the Docker volume with the specified size
        # client.volumes.create(volume_name, driver = 'local', driver_opts={'size': hard_disk_capacity})

        # Determine container name based on ssh key
        container_to_run = container_name_test if testing else container_name

        # Step 2: Run the Docker container
        device_requests = [DeviceRequest(count=-1, capabilities=[["gpu"]])]
        # if gpu_usage["capacity"] == 0:
        #    device_requests = []
        container = client.containers.run(
            image=image_name,
            name=container_to_run,
            detach=True,
            device_requests=device_requests,
            environment=["NVIDIA_VISIBLE_DEVICES=all"],
            ports={22: docker_ssh_port},
            init=True,
            shm_size=f"{shm_size_gb}g",  # Set the shared memory size to 2GB
            restart_policy={"Name": "on-failure", "MaximumRetryCount": 3},
#            volumes={ docker_volume: {'bind': '/root/workspace/', 'mode': 'rw'}},
        )

        # Check the status to determine if the container ran successfully
        if container.status == "created":
            bt.logging.info("Container was created successfully.")
            info = {"username": "root", "password": password, "port": docker_ssh_port, "version" : __version_as_int__}
            info_str = json.dumps(info)
            public_key = public_key.encode("utf-8")
            encrypted_info = rsa.encrypt_data(public_key, info_str)
            encrypted_info = base64.b64encode(encrypted_info).decode("utf-8")

            # The path to the file where you want to store the data
            file_path = 'allocation_key'
            allocation_key = base64.b64encode(public_key).decode("utf-8")

            # Open the file in write mode ('w') and write the data
            with open(file_path, 'w') as file:
                file.write(allocation_key)

            return {"status": True, "info": encrypted_info}
        else:
            bt.logging.info(f"Container falied with status : {container.status}")
            return {"status": False}
    except Exception as e:
        bt.logging.info(f"Error running container {e}")
        return {"status": False}


# Check if the container exists
def check_container():
    try:
        client, containers = get_docker()
        for container in containers:
            if container.name == container_name_test and container.status == "running":
                return True
            if container.name == container_name and container.status == "running":
                return True
        return False
    except Exception as e:
        bt.logging.info(f"Error checking container {e}")
        return False


# Set the base size of docker, daemon
def set_docker_base_size(base_size):  # e.g 100g
    docker_daemon_file = "/etc/docker/daemon.json"

    # Modify the daemon.json file to set the new base size
    storage_options = {"storage-driver": "devicemapper", "storage-opts": ["dm.basesize=" + base_size]}

    with open(docker_daemon_file, "w") as json_file:
        json.dump(storage_options, json_file, indent=4)

    # Restart Docker
    subprocess.run(["systemctl", "restart", "docker"])


# Randomly generate password for given length
def password_generator(length):
    alphabet = string.ascii_letters + string.digits  # You can customize this as needed
    random_str = "".join(secrets.choice(alphabet) for _ in range(length))
    return random_str

def build_check_container(image_name: str, container_name: str):
    try:
        client = docker.from_env()
        dockerfile = '''
        FROM pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime
        CMD echo "compute-subnet"
        '''

        # Create a file-like object from the Dockerfile
        f = BytesIO(dockerfile.encode('utf-8'))

        # Build the Docker image
        bt.logging.info("Building the Docker image... this may take a few minutes during the initial installation.")
        image, _ = client.images.build(fileobj=f, tag=image_name)
        bt.logging.trace(f"Docker image '{image_name}' built successfully.")

        # Create the container from the built image
        container = client.containers.create(image_name, name=container_name)
        bt.logging.trace(f"Container '{container_name}' created successfully.")
        return container

    except docker.errors.BuildError as e:
        pass
    except docker.errors.APIError as e:
        pass
    except Exception as e:
        bt.logging.error(
            "Insufficient permissions to execute Docker commands. Please ensure the current user is added to the 'docker' group "
            "and has the necessary privileges. Run 'sudo usermod -aG docker $USER' and restart your session."
        )
    finally:
        try:
            client.close()
        except Exception as close_error:
            bt.logging.warning(f"Error closing the Docker client: {close_error}")

def build_sample_container():
    """
    Build a sample container to speed up the process of building the container

    Sample container image is tagged as ssh-image-base:latest
    """
    try:
        client = docker.from_env()
        images = client.images.list(all=True)

        for image in images:
            if image.tags:
                if image_name_base in image.tags[0]:
                    bt.logging.info("Sample container image already exists.")
                    return {"status": True}

        password = password_generator(10)

        # Step 1: Build the Docker image with an SSH server
        # Step 1: Build the Docker image with SSH server and install numpy
        dockerfile_content = f"""
        FROM pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime

        # Prevent interactive prompts during package installation
        ENV DEBIAN_FRONTEND=noninteractive

        # Install SSH server and necessary packages
        RUN apt-get update && \\
            apt-get install -y --no-install-recommends openssh-server python3-pip build-essential && \\
            mkdir /var/run/sshd && \\
            echo 'root:{password}' | chpasswd && \\
            sed -i 's/#PermitRootLogin prohibit-password/PermitRootLogin yes/' /etc/ssh/sshd_config && \\
            sed -i 's/#PasswordAuthentication yes/PasswordAuthentication yes/' /etc/ssh/sshd_config && \\
            sed -i 's/#PubkeyAuthentication yes/PubkeyAuthentication yes/' /etc/ssh/sshd_config && \\
            sed -i 's/#ListenAddress 0.0.0.0/ListenAddress 0.0.0.0/' /etc/ssh/sshd_config
        RUN mkdir -p /root/.ssh/ && echo '{""}' > /root/.ssh/authorized_keys && chmod 600 /root/.ssh/authorized_keys

        # Ensure PATH includes Conda binaries
        ENV PATH="/opt/conda/bin:$PATH"

        # Activate Conda environment on shell startup (for interactive shells)
        RUN echo "source /opt/conda/etc/profile.d/conda.sh && conda activate base" >> /root/.bashrc

        # Force "python3" to be the conda Python
        RUN ln -sf /opt/conda/bin/python /usr/local/bin/python3

        # Install numpy
        RUN pip3 install --upgrade pip && \\
            pip3 install numpy==1.24.3 && \\
            apt-get clean && \\
            rm -rf /var/lib/apt/lists/*

        # Start SSH daemon
        CMD ["/usr/sbin/sshd", "-D"]
        """
        # dockerfile_content = (
        #     """
        #     FROM ubuntu
        #     RUN apt-get update && apt-get install -y openssh-server
        #     RUN mkdir -p /run/sshd && echo 'root:'{}'' | chpasswd
        #     RUN sed -i 's/#PermitRootLogin prohibit-password/PermitRootLogin yes/' /etc/ssh/sshd_config && \
        #         sed -i 's/#PasswordAuthentication yes/PasswordAuthentication yes/' /etc/ssh/sshd_config && \
        #         sed -i 's/#PubkeyAuthentication yes/PubkeyAuthentication yes/' /etc/ssh/sshd_config && \
        #         sed -i 's/#ListenAddress 0.0.0.0/ListenAddress 0.0.0.0/' /etc/ssh/sshd_config
        #     RUN mkdir -p /root/.ssh/ && echo '{}' > /root/.ssh/authorized_keys && chmod 600 /root/.ssh/authorized_keys
        #     CMD ["/usr/sbin/sshd", "-D"]
        #     """.format(password, "")
        # )

        # Ensure the tmp directory exists within the current directory
        tmp_dir_path = os.path.join('.', 'tmp')
        os.makedirs(tmp_dir_path, exist_ok=True)

        # Path for the Dockerfile within the tmp directory
        dockerfile_path = os.path.join(tmp_dir_path, 'dockerfile')
        with open(dockerfile_path, "w") as dockerfile:
            dockerfile.write(dockerfile_content)

        # Build the Docker image and remove the intermediate containers
        client.images.build(path=os.path.dirname(dockerfile_path), dockerfile=os.path.basename(dockerfile_path),
                            tag=image_name_base, rm=True)
        # Create the Docker volume with the specified size
        # client.volumes.create(volume_name, driver = 'local', driver_opts={'size': hard_disk_capacity})

        bt.logging.info("Sample container image was created successfully.")
        return {"status": True}
    except Exception as e:
        bt.logging.info(f"Error build sample container {e}")
        return {"status": False}

def retrieve_allocation_key():
    try:
        file_path = 'allocation_key'
         # Open the file in read mode ('r') and read the data
        with open(file_path, 'r') as file:
            allocation_key_encoded = file.read()

        # Decode the base64-encoded public key from the file
        allocation_key = base64.b64decode(allocation_key_encoded).decode('utf-8')
        return allocation_key
    except Exception as e:
        bt.logging.info(f"Error retrieving allocation key.")
        return None

def restart_container(public_key:str):
    try:
        allocation_key = retrieve_allocation_key()
        if allocation_key is None:
            bt.logging.info("Failed to retrieve allocation key.")
            return {"status": False}
        # compare public_key to the local saved allocation key for security
        if allocation_key.strip() == public_key.strip():
            client, containers = get_docker()
            ssh_container = None
            for container in containers:
                if container_name in container.name:
                    ssh_container = container
                    break
            if ssh_container:
                # stop and remove the container by using the SIGTERM signal to PID 1 (init) process in the container
                if ssh_container.status == "running":
                    ssh_container.exec_run(cmd="kill -15 1")
                    ssh_container.wait()
                # Restart container
                ssh_container.restart()
                # Reload the container to get updated information
                ssh_container.reload()
                if ssh_container.status == "running":
                    return {"status": True}
                else:
                    return {"status": False}
            else:
                bt.logging.info("No running container.")
                return {"status": False}
        else:
            bt.logging.info(f"Permission denied.")
            return {"status":False}
    except Exception as e:
        bt.logging.info(f"Error restart container: {e}")
        return {"status": False}

def pause_container(public_key:str):
    try:
        allocation_key = retrieve_allocation_key()
        if allocation_key is None:
            bt.logging.info("Failed to retrieve allocation key.")
            return {"status": False}
        # compare public_key to the local saved allocation key for security
        if allocation_key.strip() == public_key.strip():
            client, containers = get_docker()
            running_container = None
            for container in containers:
                if container_name in container.name:
                    running_container = container
                    break
            if running_container:
                running_container.pause()
                return {"status": True}
            else:
                bt.logging.info("Unable to find container")
                return {"status": False}
        else:
            bt.logging.info(f"Permission denied.")
            return {"status": False}
    except Exception as e:
        bt.logging.info(f"Error pausing container {e}")
        return {"status": False}

def unpause_container(public_key:str):
    try:
        allocation_key = retrieve_allocation_key()
        if allocation_key is None:
            bt.logging.info("Failed to retrieve allocation key.")
            return {"status": False}
        # compare public_key to the local saved allocation key for security
        if allocation_key.strip() == public_key.strip():
            client, containers = get_docker()
            running_container = None
            for container in containers:
                if container_name in container.name:
                    running_container = container
                    break
            if running_container:
                running_container.unpause()
                return {"status": True}
            else:
                bt.logging.info("Unable to find container")
                return {"status": False}
        else:
            bt.logging.info(f"Permission denied.")
            return {"status": False}
    except Exception as e:
        bt.logging.info(f"Error unpausing container {e}")
        return {"status": False}

def exchange_key_container(new_ssh_key: str, public_key: str, key_type: str = "user" ):
    try:
        allocation_key = retrieve_allocation_key()
        if allocation_key is None:
            bt.logging.info("Failed to retrieve allocation key.")
            return {"status": False}
        # compare public_key to the local saved allocation key for security
        if allocation_key.strip() == public_key.strip():
            client, containers = get_docker()
            running_container = None
            for container in containers:
                if container_name in container.name:
                    running_container = container
                    break
            if running_container:
                # stop and remove the container by using the SIGTERM signal to PID 1 (init) process in the container
                if running_container.status == "running":
                    exist_key = running_container.exec_run(cmd="cat /root/.ssh/authorized_keys")
                    exist_key = exist_key.output.decode("utf-8").split("\n")
                    user_key = exist_key[0]
                    terminal_key = ""
                    if len(exist_key) > 1:
                        terminal_key = exist_key[1]
                    if key_type == "terminal":
                        terminal_key = new_ssh_key
                    elif key_type == "user":
                        user_key = new_ssh_key
                    else:
                        bt.logging.debug("Invalid key type to swap the SSH key")
                        return {"status": False}
                    key_list = user_key + "\n" + terminal_key
                    # bt.logging.debug(f"New SSH key: {key_list}")
                    running_container.exec_run(cmd=f"bash -c \"echo '{key_list}' > /root/.ssh/authorized_keys & sync & sleep 1\"")
                    running_container.exec_run(cmd="kill -15 1")
                    running_container.wait()
                    running_container.restart()
                return {"status": True}
            else:
                bt.logging.info("Unable to find container")
                return {"status": False}
        else:
            bt.logging.info(f"Permission denied.")
            return {"status": False}
    except Exception as e:
        bt.logging.info(f"Error changing SSH key on container {e}")
        return {"status": False}
