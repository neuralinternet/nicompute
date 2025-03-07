import base64
import pytest
import allure
from unittest.mock import MagicMock, patch, mock_open

from neurons.Miner.container import (
    run_container,
    check_container,
    pause_container,
    unpause_container,
    get_docker,
    kill_container,
    set_docker_base_size
)

# --- Autouse Fixture to Patch Module-Level Container Names ---
@pytest.fixture(autouse=True)
def patch_container_names(monkeypatch):
    """
    Ensure that module-level variables for container names are set to known values.
    This helps the functions under test to correctly match container names.
    """
    from neurons.Miner import container as cnt
    monkeypatch.setattr(cnt, "container_name", "container")
    monkeypatch.setattr(cnt, "container_name_test", "test_container")

# --- Dummy Virtual Memory for psutil ---
class DummyVirtualMemory:
    available = 8 * 1024**3  # 8 GB

# --- Fixtures for common objects ---
@pytest.fixture
def allocation_key_fixture():
    """Returns a mock allocation key."""
    return "test_public_key"

@pytest.fixture
def running_container():
    """A regular container in 'running' state with expected name."""
    container = MagicMock()
    container.name = "container"
    container.status = "running"
    return container

@pytest.fixture
def exited_container():
    """A regular container in 'exited' state with expected name."""
    container = MagicMock()
    container.name = "container"
    container.status = "exited"
    return container

@pytest.fixture
def running_test_container():
    """A test container in 'running' state with expected test name."""
    container = MagicMock()
    container.name = "test_container"
    container.status = "running"
    return container

@pytest.fixture
def docker_client_with_container(running_container):
    """A Docker client that returns a regular container."""
    client = MagicMock()
    client.containers.list.return_value = [running_container]
    return client

@pytest.fixture
def docker_client_with_test_container(running_test_container):
    """A Docker client that returns a test container."""
    client = MagicMock()
    client.containers.list.return_value = [running_test_container]
    return client

# --- Grouped Tests using Allure ---

@allure.feature("Run Container")
class TestRunContainer:
    @allure.story("Run Container Success")
    @allure.step("Setup globals, simulate Docker client and run container")
    @patch('os.makedirs')
    @patch('builtins.open', new_callable=mock_open)
    @patch('neurons.Miner.container.rsa.encrypt_data')
    @patch('neurons.Miner.container.bt.logging.trace')
    @patch('neurons.Miner.container.bt.logging.info')
    @patch('neurons.Miner.container.psutil.virtual_memory', return_value=DummyVirtualMemory())
    @patch('neurons.Miner.container.build_sample_container')
    @patch('neurons.Miner.container.password_generator')
    @patch('neurons.Miner.container.get_docker')
    def test_run_container_success(self,
                                   mock_get_docker,
                                   mock_password_generator,
                                   mock_build_sample_container,
                                   mock_virtual_memory,
                                   mock_logging_info,
                                   mock_logging_trace,
                                   mock_encrypt_data,
                                   mock_open_fn,
                                   mock_makedirs):
        """
        run_container:
        Should successfully run a new container when all dependencies are met and
        container.status is 'created'. Returns a dict with status True and the encrypted info.
        """
        from neurons.Miner import container as cnt
        cnt.image_name_base = "dummy_base"
        cnt.image_name = "dummy_image"
        cnt.__version_as_int__ = 1

        dummy_container = MagicMock()
        dummy_container.status = "created"
        dummy_client = MagicMock()
        dummy_client.images.build.return_value = (None, None)
        dummy_client.containers.run.return_value = dummy_container
        mock_get_docker.return_value = (dummy_client, [])

        mock_password_generator.return_value = "testpwd"
        mock_encrypt_data.return_value = b"encrypted_data"

        cpu_usage = {"assignment": "0-1"}
        ram_usage = {"capacity": "5g"}
        hard_disk_usage = {"capacity": "100g"}
        gpu_usage = {"capacity": "all"}
        public_key = "dummy_public_key"
        docker_requirement = {
            "base_image": "dummy_base",
            "volume_path": "/dummy/volume",
            "ssh_key": "dummy_ssh_key",
            "ssh_port": 2222,
            "dockerfile": ""
        }
        testing = True

        result = run_container(cpu_usage, ram_usage, hard_disk_usage, gpu_usage,
                               public_key, docker_requirement, testing)

        dummy_client.images.build.assert_called_once()
        dummy_client.containers.run.assert_called_once()
        _, kwargs = dummy_client.containers.run.call_args
        assert kwargs.get("name") == "test_container"

        mock_open_fn.assert_called_with('allocation_key', 'w')
        expected_info = base64.b64encode(b"encrypted_data").decode("utf-8")
        assert result == {"status": True, "info": expected_info}


@allure.feature("Container Monitoring")
class TestCheckContainer:
    @allure.story("Verify Running Container")
    def test_check_container_running(self, running_container):
        """
        check_container:
        Returns True when a regular container (with name "container") is running.
        """
        with patch('neurons.Miner.container.get_docker') as mock_get_docker:
            client = MagicMock()
            client.containers.list.return_value = [running_container]
            mock_get_docker.return_value = (client, [running_container])
            assert check_container() is True

    @allure.story("Verify Test Container Running")
    def test_check_container_test_running(self, running_test_container):
        """
        check_container:
        Returns True when a test container (with name "test_container") is running.
        """
        with patch('neurons.Miner.container.get_docker') as mock_get_docker:
            client = MagicMock()
            client.containers.list.return_value = [running_test_container]
            mock_get_docker.return_value = (client, [running_test_container])
            assert check_container() is True

    @allure.story("Verify Container Not Found")
    def test_check_container_not_running(self, running_container):
        """
        check_container:
        Returns False when the container name does not match the expected value.
        """
        running_container.name = "other_container"
        with patch('neurons.Miner.container.get_docker') as mock_get_docker:
            client = MagicMock()
            client.containers.list.return_value = [running_container]
            mock_get_docker.return_value = (client, [running_container])
            assert check_container() is False

    @allure.story("Exception in Container Check")
    def test_check_container_exception(self):
        """
        check_container:
        Returns False when an exception is raised during Docker access.
        """
        with patch('neurons.Miner.container.get_docker', side_effect=Exception("Test error")) as mock_get_docker:
            assert check_container() is False


@allure.feature("Container Pause/Unpause")
class TestPauseContainer:
    @allure.story("Pause Container Success")
    def test_pause_container_success(self, allocation_key_fixture, running_container):
        """
        pause_container:
        Pauses the container when the allocation key is valid.
        """
        with patch('neurons.Miner.container.get_docker') as mock_get_docker, \
             patch('neurons.Miner.container.retrieve_allocation_key') as mock_retrieve_allocation_key:
            mock_retrieve_allocation_key.return_value = allocation_key_fixture
            client = MagicMock()
            client.containers.list.return_value = [running_container]
            mock_get_docker.return_value = (client, [running_container])
            result = pause_container(allocation_key_fixture)
            running_container.pause.assert_called_once()
            assert result == {"status": True}

    @allure.story("Pause Container No Allocation Key")
    def test_pause_container_no_allocation_key(self):
        """
        pause_container:
        Returns False if no allocation key is retrieved.
        """
        with patch('neurons.Miner.container.retrieve_allocation_key', return_value=None):
            result = pause_container("test_public_key")
            assert result == {"status": False}

    @allure.story("Pause Container Key Mismatch")
    def test_pause_container_key_mismatch(self, allocation_key_fixture):
        """
        pause_container:
        Returns False when the provided allocation key does not match.
        """
        with patch('neurons.Miner.container.retrieve_allocation_key') as mock_retrieve_allocation_key:
            mock_retrieve_allocation_key.return_value = allocation_key_fixture
            result = pause_container("invalid_key")
            assert result == {"status": False}

    @allure.story("Pause Container Not Found")
    def test_pause_container_not_found(self, allocation_key_fixture, running_container):
        """
        pause_container:
        Returns False when no container with the expected name is found.
        """
        running_container.name = "not_found"
        with patch('neurons.Miner.container.get_docker') as mock_get_docker, \
             patch('neurons.Miner.container.retrieve_allocation_key') as mock_retrieve_allocation_key:
            client = MagicMock()
            client.containers.list.return_value = [running_container]
            mock_get_docker.return_value = (client, [running_container])
            mock_retrieve_allocation_key.return_value = allocation_key_fixture
            result = pause_container(allocation_key_fixture)
            assert result == {"status": False}

    @allure.story("Pause Container Exception")
    def test_pause_container_exception(self, allocation_key_fixture):
        """
        pause_container:
        Returns False when an exception occurs in get_docker.
        """
        with patch('neurons.Miner.container.get_docker', side_effect=Exception("Test error")), \
             patch('neurons.Miner.container.retrieve_allocation_key') as mock_retrieve_allocation_key:
            mock_retrieve_allocation_key.return_value = allocation_key_fixture
            result = pause_container(allocation_key_fixture)
            assert result == {"status": False}


@allure.feature("Container Pause/Unpause")
class TestUnpauseContainer:
    @allure.story("Unpause Container Success")
    def test_unpause_container_success(self, allocation_key_fixture, running_container):
        """
        unpause_container:
        Unpauses the container when the allocation key is valid.
        """
        with patch('neurons.Miner.container.get_docker') as mock_get_docker, \
             patch('neurons.Miner.container.retrieve_allocation_key') as mock_retrieve_allocation_key:
            mock_retrieve_allocation_key.return_value = allocation_key_fixture
            client = MagicMock()
            client.containers.list.return_value = [running_container]
            mock_get_docker.return_value = (client, [running_container])
            result = unpause_container(allocation_key_fixture)
            running_container.unpause.assert_called_once()
            assert result == {"status": True}

    @allure.story("Unpause Container No Allocation Key")
    def test_unpause_container_no_allocation_key(self):
        """
        unpause_container:
        Returns False if no allocation key is retrieved.
        """
        with patch('neurons.Miner.container.retrieve_allocation_key', return_value=None):
            result = unpause_container("test_public_key")
            assert result == {"status": False}

    @allure.story("Unpause Container Key Mismatch")
    def test_unpause_container_key_mismatch(self, allocation_key_fixture):
        """
        unpause_container:
        Returns False when the provided allocation key does not match.
        """
        with patch('neurons.Miner.container.retrieve_allocation_key') as mock_retrieve_allocation_key:
            mock_retrieve_allocation_key.return_value = allocation_key_fixture
            result = unpause_container("invalid_key")
            assert result == {"status": False}

    @allure.story("Unpause Container Not Found")
    def test_unpause_container_not_found(self, allocation_key_fixture, running_container):
        """
        unpause_container:
        Returns False when no container with the expected name is found.
        """
        running_container.name = "not_found"
        with patch('neurons.Miner.container.get_docker') as mock_get_docker, \
             patch('neurons.Miner.container.retrieve_allocation_key') as mock_retrieve_allocation_key:
            client = MagicMock()
            client.containers.list.return_value = [running_container]
            mock_get_docker.return_value = (client, [running_container])
            mock_retrieve_allocation_key.return_value = allocation_key_fixture
            result = unpause_container(allocation_key_fixture)
            assert result == {"status": False}

    @allure.story("Unpause Container Exception")
    def test_unpause_container_exception(self, allocation_key_fixture):
        """
        unpause_container:
        Returns False when an exception occurs in get_docker.
        """
        with patch('neurons.Miner.container.get_docker', side_effect=Exception("Test error")), \
             patch('neurons.Miner.container.retrieve_allocation_key') as mock_retrieve_allocation_key:
            mock_retrieve_allocation_key.return_value = allocation_key_fixture
            result = unpause_container(allocation_key_fixture)
            assert result == {"status": False}


@allure.feature("Docker Client")
class TestGetDocker:
    @allure.story("Get Docker Success")
    def test_get_docker_success(self):
        """
        get_docker:
        Initializes the Docker client and lists containers successfully.
        """
        mock_client = MagicMock()
        mock_containers = [MagicMock(), MagicMock()]
        mock_client.containers.list.return_value = mock_containers
        with patch('docker.from_env', return_value=mock_client):
            client, containers = get_docker()
            assert client == mock_client
            assert containers == mock_containers
            mock_client.containers.list.assert_called_once_with(all=True)

    @allure.story("Get Docker Exception")
    def test_get_docker_exception(self):
        """
        get_docker:
        Raises an exception if Docker client initialization fails.
        """
        with patch('docker.from_env', side_effect=Exception("Docker error")):
            with pytest.raises(Exception):
                get_docker()

    @allure.story("Get Docker List Exception")
    def test_get_docker_list_exception(self):
        """
        get_docker:
        Raises an exception if listing containers fails.
        """
        mock_client = MagicMock()
        mock_client.containers.list.side_effect = Exception("List error")
        with patch('docker.from_env', return_value=mock_client):
            with pytest.raises(Exception):
                get_docker()


@allure.feature("Container Termination")
class TestKillContainer:
    @allure.story("Kill Test Container Running")
    def test_kill_container_test_running(self, docker_client_with_test_container, running_test_container):
        """
        kill_container:
        Kills a running test container.
        """
        with patch('neurons.Miner.container.get_docker') as mock_get_docker:
            docker_client_with_test_container.images.prune = MagicMock()
            mock_get_docker.return_value = (docker_client_with_test_container, [running_test_container])
            result = kill_container()
            running_test_container.exec_run.assert_called_once_with(cmd="kill -15 1")
            running_test_container.wait.assert_called_once()
            running_test_container.remove.assert_called_once()
            docker_client_with_test_container.images.prune.assert_called_once_with(filters={"dangling": True})
            assert result is True

    @allure.story("Kill Test Container Not Running")
    def test_kill_container_test_not_running(self, docker_client_with_test_container, running_test_container):
        """
        kill_container:
        Removes a test container that is not running.
        """
        running_test_container.status = "exited"
        with patch('neurons.Miner.container.get_docker') as mock_get_docker:
            docker_client_with_test_container.images.prune = MagicMock()
            mock_get_docker.return_value = (docker_client_with_test_container, [running_test_container])
            result = kill_container()
            running_test_container.exec_run.assert_not_called()
            running_test_container.wait.assert_not_called()
            running_test_container.remove.assert_called_once()
            docker_client_with_test_container.images.prune.assert_called_once_with(filters={"dangling": True})
            assert result is True

    @allure.story("Kill Regular Container Running")
    def test_kill_container_regular_running(self, docker_client_with_container, running_container):
        """
        kill_container:
        Kills a running regular container.
        """
        with patch('neurons.Miner.container.get_docker') as mock_get_docker:
            docker_client_with_container.images.prune = MagicMock()
            mock_get_docker.return_value = (docker_client_with_container, [running_container])
            result = kill_container()
            running_container.exec_run.assert_called_once_with(cmd="kill -15 1")
            running_container.wait.assert_called_once()
            running_container.remove.assert_called_once()
            docker_client_with_container.images.prune.assert_called_once_with(filters={"dangling": True})
            assert result is True

    @allure.story("Kill Regular Container Not Running")
    def test_kill_container_regular_not_running(self, docker_client_with_container, exited_container):
        """
        kill_container:
        Removes a regular container that is not running.
        """
        with patch('neurons.Miner.container.get_docker') as mock_get_docker:
            docker_client_with_container.images.prune = MagicMock()
            mock_get_docker.return_value = (docker_client_with_container, [exited_container])
            result = kill_container()
            exited_container.exec_run.assert_not_called()
            exited_container.wait.assert_not_called()
            exited_container.remove.assert_called_once()
            docker_client_with_container.images.prune.assert_called_once_with(filters={"dangling": True})
            assert result is True

    @allure.story("Kill Container Priority")
    def test_kill_container_priority(self):
        """
        kill_container:
        Prioritizes killing the test container over the regular container.
        """
        mock_regular_container = MagicMock()
        mock_regular_container.name = "container"
        mock_regular_container.status = "running"
        
        mock_test_container = MagicMock()
        mock_test_container.name = "test_container"
        mock_test_container.status = "running"
        
        client = MagicMock()
        client.images.prune = MagicMock()
        containers = [mock_regular_container, mock_test_container]
        
        with patch('neurons.Miner.container.get_docker', return_value=(client, containers)):
            result = kill_container()
            mock_test_container.exec_run.assert_called_once_with(cmd="kill -15 1")
            mock_test_container.wait.assert_called_once()
            mock_test_container.remove.assert_called_once()
            mock_regular_container.exec_run.assert_not_called()
            mock_regular_container.wait.assert_not_called()
            mock_regular_container.remove.assert_not_called()
            client.images.prune.assert_called_once_with(filters={"dangling": True})
            assert result is True

    @allure.story("Kill Container Not Found")
    def test_kill_container_not_found(self):
        """
        kill_container:
        Does nothing if no matching container is found.
        """
        mock_container = MagicMock()
        mock_container.name = "other_container"
        client = MagicMock()
        client.images.prune = MagicMock()
        containers = [mock_container]
        with patch('neurons.Miner.container.get_docker', return_value=(client, containers)):
            result = kill_container()
            mock_container.exec_run.assert_not_called()
            mock_container.wait.assert_not_called()
            mock_container.remove.assert_not_called()
            client.images.prune.assert_called_once_with(filters={"dangling": True})
            assert result is True

    @allure.story("Kill Container Exception")
    def test_kill_container_exception(self):
        """
        kill_container:
        Returns False when get_docker raises an exception.
        """
        with patch('neurons.Miner.container.get_docker', side_effect=Exception("Test error")):
            result = kill_container()
            assert result is False


@allure.feature("Docker Daemon Configuration")
class TestSetDockerBaseSize:
    @allure.story("Set Docker Base Size")
    def test_set_docker_base_size(self,):
        """
        set_docker_base_size:
        Verifies that the function writes the correct JSON content to /etc/docker/daemon.json
        and calls subprocess.run to restart Docker.
        """
        base_size = "100g"
        expected_file = "/etc/docker/daemon.json"
        expected_dict = {
            "storage-driver": "devicemapper",
            "storage-opts": ["dm.basesize=" + base_size]
        }
        with patch('neurons.Miner.container.subprocess.run') as mock_subprocess_run, \
             patch('neurons.Miner.container.json.dump') as mock_json_dump, \
             patch('builtins.open', new_callable=mock_open) as mock_open_fn:
            set_docker_base_size(base_size)
            mock_open_fn.assert_called_once_with(expected_file, "w")
            file_handle = mock_open_fn()
            mock_json_dump.assert_called_once_with(expected_dict, file_handle, indent=4)
            mock_subprocess_run.assert_called_once_with(["systemctl", "restart", "docker"])
