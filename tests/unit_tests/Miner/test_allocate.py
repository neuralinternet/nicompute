import pytest
import allure
import os
import base64
from unittest.mock import patch, MagicMock, mock_open
from neurons.Miner.allocate import register_allocation, deregister_allocation, check_allocation, check_if_allocated

# --- Fixtures ---
@pytest.fixture
def device_requirement():
    """Returns a mock device requirement dictionary."""
    return {
        "cpu": {"count": 2},
        "gpu": {"capacity": "all"},
        "hard_disk": {"capacity": 1073741824},  # 1GB
        "ram": {"capacity": 1073741824},  # 1GB
        "testing": True
    }

@pytest.fixture
def device_requirement_single_cpu():
    """Returns a mock device requirement dictionary with single CPU."""
    return {
        "cpu": {"count": 1},
        "gpu": {"capacity": "all"},
        "hard_disk": {"capacity": 1073741824},  # 1GB
        "ram": {"capacity": 1073741824},  # 1GB
        "testing": True
    }

@pytest.fixture
def device_requirement_no_gpu():
    """Returns a mock device requirement dictionary without GPU."""
    return {
        "cpu": {"count": 2},
        "gpu": {},
        "hard_disk": {"capacity": 1073741824},  # 1GB
        "ram": {"capacity": 1073741824},  # 1GB
        "testing": True
    }

@pytest.fixture
def docker_requirement():
    """Returns a mock docker requirement dictionary."""
    return {
        "base_image": "test-image",
        "volume_path": "/test/volume",
        "ssh_key": "test-ssh-key",
        "ssh_port": 2222,
        "dockerfile": "echo 'test'"
    }

@pytest.fixture
def public_key():
    """Returns a mock public key."""
    return "test_public_key"

# --- Test Cases ---
@allure.feature("Allocation Management")
@allure.story("Register Allocation")
class TestRegisterAllocation:
    @allure.title("Test successful container registration")
    @patch('neurons.Miner.allocate.kill_container')
    @patch('neurons.Miner.allocate.run_container')
    @patch('neurons.Miner.allocate.start')
    def test_register_allocation_success(self, mock_start, mock_run_container, mock_kill_container,
                                      device_requirement, docker_requirement, public_key):
        """Test successful container registration with valid parameters."""
        mock_kill_container.return_value = True
        mock_run_container.return_value = {"status": True}
        mock_start.return_value = None

        result = register_allocation(
            timeline=1,
            device_requirement=device_requirement,
            public_key=public_key,
            docker_requirement=docker_requirement
        )

        assert result["status"] is True
        mock_kill_container.assert_called_once()
        mock_run_container.assert_called_once()
        mock_start.assert_called_once()

    @allure.title("Test container registration with single CPU")
    @patch('neurons.Miner.allocate.kill_container')
    @patch('neurons.Miner.allocate.run_container')
    @patch('neurons.Miner.allocate.start')
    def test_register_allocation_single_cpu(self, mock_start, mock_run_container, mock_kill_container,
                                         device_requirement_single_cpu, docker_requirement, public_key):
        """Test container registration with single CPU configuration."""
        mock_kill_container.return_value = True
        mock_run_container.return_value = {"status": True}
        mock_start.return_value = None

        result = register_allocation(
            timeline=1,
            device_requirement=device_requirement_single_cpu,
            public_key=public_key,
            docker_requirement=docker_requirement
        )

        assert result["status"] is True
        # Verify that run_container was called with correct CPU assignment
        args, kwargs = mock_run_container.call_args
        assert args[0]['assignment'] == "0"  # First argument is cpu_usage

    @allure.title("Test container registration without GPU")
    @patch('neurons.Miner.allocate.kill_container')
    @patch('neurons.Miner.allocate.run_container')
    @patch('neurons.Miner.allocate.start')
    def test_register_allocation_no_gpu(self, mock_start, mock_run_container, mock_kill_container,
                                     device_requirement_no_gpu, docker_requirement, public_key):
        """Test container registration without GPU configuration."""
        mock_kill_container.return_value = True
        mock_run_container.return_value = {"status": True}
        mock_start.return_value = None

        result = register_allocation(
            timeline=1,
            device_requirement=device_requirement_no_gpu,
            public_key=public_key,
            docker_requirement=docker_requirement
        )

        assert result["status"] is True
        # Verify that run_container was called with GPU capacity 0
        args, kwargs = mock_run_container.call_args
        assert args[3]['capacity'] == 0  # Second argument is gpu_usage

    @allure.title("Test container registration with kill failure")
    @patch('neurons.Miner.allocate.kill_container')
    def test_register_allocation_kill_failure(self, mock_kill_container,
                                            device_requirement, docker_requirement, public_key):
        """Test container registration when kill_container fails."""
        mock_kill_container.return_value = False

        result = register_allocation(
            timeline=1,
            device_requirement=device_requirement,
            public_key=public_key,
            docker_requirement=docker_requirement
        )

        assert result["status"] is False

    @allure.title("Test container registration with run failure")
    @patch('neurons.Miner.allocate.kill_container')
    @patch('neurons.Miner.allocate.run_container')
    def test_register_allocation_run_failure(self, mock_run_container, mock_kill_container,
                                          device_requirement, docker_requirement, public_key):
        """Test container registration when run_container fails."""
        mock_kill_container.return_value = True
        mock_run_container.return_value = {"status": False}

        result = register_allocation(
            timeline=1,
            device_requirement=device_requirement,
            public_key=public_key,
            docker_requirement=docker_requirement
        )

        assert result["status"] is False

    @allure.title("Test container registration with exception")
    @patch('neurons.Miner.allocate.kill_container', side_effect=Exception("Test error"))
    def test_register_allocation_exception(self, mock_kill_container,
                                        device_requirement, docker_requirement, public_key):
        """Test container registration when an exception occurs."""
        result = register_allocation(
            timeline=1,
            device_requirement=device_requirement,
            public_key=public_key,
            docker_requirement=docker_requirement
        )

        assert result["status"] is False

@allure.feature("Allocation Management")
@allure.story("Deregister Allocation")
class TestDeregisterAllocation:
    @allure.title("Test successful container deregistration")
    @patch('builtins.open', new_callable=mock_open, read_data=base64.b64encode(b"test_public_key").decode())
    @patch('neurons.Miner.allocate.kill_container')
    def test_deregister_allocation_success(self, mock_kill_container, mock_file,
                                        public_key):
        """Test successful container deregistration with valid public key."""
        mock_kill_container.return_value = True

        result = deregister_allocation(public_key)

        assert result["status"] is True
        mock_kill_container.assert_called_once()
        mock_file.assert_called_with('allocation_key', 'w')

    @allure.title("Test container deregistration with invalid key")
    @patch('builtins.open', new_callable=mock_open, read_data=base64.b64encode(b"different_key").decode())
    def test_deregister_allocation_invalid_key(self, mock_file, public_key):
        """Test container deregistration with invalid public key."""
        result = deregister_allocation(public_key)

        assert result["status"] is False

    @allure.title("Test container deregistration with file not found")
    @patch('builtins.open', side_effect=FileNotFoundError)
    def test_deregister_allocation_file_not_found(self, mock_file, public_key):
        """Test container deregistration when allocation key file is not found."""
        result = deregister_allocation(public_key)

        assert result["status"] is False

    @allure.title("Test container deregistration with kill failure")
    @patch('builtins.open', new_callable=mock_open, read_data=base64.b64encode(b"test_public_key").decode())
    @patch('neurons.Miner.allocate.kill_container')
    def test_deregister_allocation_kill_failure(self, mock_kill_container, mock_file,
                                             public_key):
        """Test container deregistration when kill_container fails."""
        mock_kill_container.return_value = False

        result = deregister_allocation(public_key)

        assert result["status"] is False

    @allure.title("Test container deregistration with exception")
    @patch('builtins.open', side_effect=Exception("Test error"))
    def test_deregister_allocation_exception(self, mock_file, public_key):
        """Test container deregistration when an exception occurs."""
        result = deregister_allocation(public_key)

        assert result["status"] is False

@allure.feature("Allocation Management")
@allure.story("Check Allocation")
class TestCheckAllocation:
    @allure.title("Test allocation check when container is not running")
    @patch('neurons.Miner.allocate.check_container')
    def test_check_allocation_no_container(self, mock_check_container, device_requirement):
        """Test allocation check when no container is running."""
        mock_check_container.return_value = False

        result = check_allocation(timeline=1, device_requirement=device_requirement)

        assert result["status"] is True

    @allure.title("Test allocation check when container is running")
    @patch('neurons.Miner.allocate.check_container')
    def test_check_allocation_container_running(self, mock_check_container, device_requirement):
        """Test allocation check when a container is already running."""
        mock_check_container.return_value = True

        result = check_allocation(timeline=1, device_requirement=device_requirement)

        assert result["status"] is False

@allure.feature("Allocation Management")
@allure.story("Check If Allocated")
class TestCheckIfAllocated:
    @allure.title("Test allocation check when container is allocated")
    @patch('os.path.exists')
    @patch('builtins.open', new_callable=mock_open, read_data=base64.b64encode(b"test_public_key").decode())
    @patch('neurons.Miner.allocate.check_container')
    def test_check_if_allocated_success(self, mock_check_container, mock_file, mock_exists,
                                     public_key):
        """Test successful allocation check with valid public key and running container."""
        mock_exists.return_value = True
        mock_check_container.return_value = True

        result = check_if_allocated(public_key)

        assert result["status"] is True

    @allure.title("Test allocation check when file does not exist")
    @patch('os.path.exists')
    def test_check_if_allocated_file_not_found(self, mock_exists, public_key):
        """Test allocation check when allocation key file is not found."""
        mock_exists.return_value = False

        result = check_if_allocated(public_key)

        assert result["status"] is False

    @allure.title("Test allocation check with invalid key")
    @patch('os.path.exists')
    @patch('builtins.open', new_callable=mock_open, read_data=base64.b64encode(b"different_key").decode())
    def test_check_if_allocated_invalid_key(self, mock_file, mock_exists, public_key):
        """Test allocation check with invalid public key."""
        mock_exists.return_value = True

        result = check_if_allocated(public_key)

        assert result["status"] is False

    @allure.title("Test allocation check when container is not running")
    @patch('os.path.exists')
    @patch('builtins.open', new_callable=mock_open, read_data=base64.b64encode(b"test_public_key").decode())
    @patch('neurons.Miner.allocate.check_container')
    def test_check_if_allocated_container_not_running(self, mock_check_container, mock_file,
                                                   mock_exists, public_key):
        """Test allocation check when container is not running."""
        mock_exists.return_value = True
        mock_check_container.return_value = False

        result = check_if_allocated(public_key)

        assert result["status"] is False

    @allure.title("Test allocation check with empty key file")
    @patch('os.path.exists')
    @patch('builtins.open', new_callable=mock_open, read_data="")
    def test_check_if_allocated_empty_key(self, mock_file, mock_exists, public_key):
        """Test allocation check when allocation key file is empty."""
        mock_exists.return_value = True

        result = check_if_allocated(public_key)

        assert result["status"] is False

    @allure.title("Test allocation check with exception")
    @patch('os.path.exists', side_effect=Exception("Test error"))
    def test_check_if_allocated_exception(self, mock_exists, public_key):
        """Test allocation check when an exception occurs."""
        result = check_if_allocated(public_key)

        assert result["status"] is False